"""Comandi ``ingest`` e ``sources``: raccolta degli annunci e gestione delle fonti."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Source
from ..models.enums import RunStatus, WorkMode

if TYPE_CHECKING:
    from ..pipeline.ingest import IngestReport
    from ..pipeline.salary import Salary

console = Console()

sources_app = typer.Typer(
    name="sources",
    help="Fonti di annunci: elenco, attivazione, board ATS seguite.",
    no_args_is_help=True,
)

_MODE_LABEL = {
    WorkMode.REMOTE: "[green]remote[/]",
    WorkMode.HYBRID: "[cyan]ibrido[/]",
    WorkMode.ON_SITE: "[yellow]in sede[/]",
    WorkMode.UNKNOWN: "[dim]?[/]",
}

_STATUS_LABEL = {
    RunStatus.OK: "[green]ok[/]",
    RunStatus.PARTIAL: "[yellow]parziale[/]",
    RunStatus.FAILED: "[red]fallita[/]",
    RunStatus.RUNNING: "in corso",
}


def ingest_command(
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--commit", help="Stampa senza scrivere sul database.")
    ] = True,
    source: Annotated[
        list[str] | None, typer.Option("--source", "-s", help="Limita a una o piu' fonti.")
    ] = None,
    keyword: Annotated[
        list[str] | None, typer.Option("--keyword", "-k", help="Sovrascrive i termini di ricerca.")
    ] = None,
    country: Annotated[
        list[str] | None, typer.Option("--country", "-c", help="Sovrascrive i paesi (ISO alpha-2).")
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Massimo di risultati per termine e fonte.")
    ] = None,
    show: Annotated[int, typer.Option("--show", help="Quanti annunci elencare.")] = 25,
) -> None:
    """Raccoglie annunci dalle fonti attive, li normalizza e li deduplica."""
    # Import esplicito della funzione: ``pipeline`` riesporta ``ingest``, quindi
    # ``from ..pipeline import ingest`` darebbe la funzione dove serve il modulo.
    from ..pipeline.ingest import ingest as run_ingest

    with session_scope() as session:
        report = run_ingest(
            session,
            only=source,
            keywords=keyword,
            countries=country,
            limit=limit,
            dry_run=dry_run,
        )

        console.print(
            f"ricerca: [bold]{', '.join(report.query.keywords)}[/] "
            f"in [bold]{', '.join(report.query.countries)}[/] "
            f"(ultimi {report.query.posted_within_days} giorni)\n"
        )
        _render_outcomes(report)
        _render_jobs(report, show)

        duplicati = report.fetched - len(report.groups)
        console.print(
            f"\n[bold]{report.fetched}[/] annunci raccolti, "
            f"[bold]{len(report.groups)}[/] distinti "
            f"({duplicati} uniti dalla dedup), {report.api_calls} chiamate API"
        )
        if dry_run:
            console.print(
                "[yellow]--dry-run: niente e' stato scritto.[/] "
                "Ripeti con [bold]--commit[/] per salvare."
            )
        else:
            console.print(
                f"[green]salvati:[/] {report.persisted_new} nuovi, "
                f"{report.persisted_updated} aggiornati"
            )

        if report.status is RunStatus.FAILED:
            raise typer.Exit(1)


def _render_outcomes(report: IngestReport) -> None:
    table = Table(title="Fonti", header_style="bold")
    table.add_column("Fonte")
    table.add_column("Esito")
    table.add_column("Annunci", justify="right")
    table.add_column("Chiamate", justify="right")
    table.add_column("Tempo", justify="right")
    table.add_column("Errore", overflow="fold")

    for esito in report.outcomes:
        table.add_row(
            esito.slug,
            _STATUS_LABEL.get(esito.status, str(esito.status)),
            str(esito.fetched),
            str(esito.api_calls),
            f"{esito.elapsed:.1f}s",
            esito.error or "",
        )
    console.print(table)


def _render_jobs(report: IngestReport, limit: int) -> None:
    if not report.groups:
        console.print("[yellow]Nessun annuncio.[/]")
        return

    table = Table(title=f"Annunci (primi {min(limit, len(report.groups))})", header_style="bold")
    table.add_column("Ruolo", overflow="ellipsis", max_width=38)
    table.add_column("Azienda", overflow="ellipsis", max_width=22)
    table.add_column("Luogo", overflow="ellipsis", max_width=18)
    table.add_column("Mod.")
    table.add_column("RAL", justify="right")
    # La colonna mostra `job_family`, non il tipo di contratto: chiamarla
    # "Tipo" faceva sembrare un errore di normalizzazione una riga corretta.
    table.add_column("Famiglia", overflow="ellipsis", max_width=20)
    table.add_column("Fonti")

    # Prima gli annunci visti da piu' fonti: sono quelli su cui la dedup ha
    # lavorato, cioe' quelli su cui vale la pena controllare che abbia ragione.
    ordinati = sorted(report.groups, key=lambda g: -len(g.variants))
    for gruppo in ordinati[:limit]:
        job = gruppo.canonical
        table.add_row(
            job.title,
            job.company,
            ", ".join(p for p in (job.city, job.country) if p) or "—",
            _MODE_LABEL.get(job.work_mode, "?"),
            _salary_label(job.salary),
            job.job_family or "[dim]?[/]",
            ", ".join(gruppo.sources),
        )
    console.print(table)


def _salary_label(salary: Salary) -> str:
    if not salary.is_stated:
        # La promessa fatta alla dashboard: mai una stima al posto di un dato.
        return "[dim]n.d.[/]"
    valuta = salary.currency or ""
    periodo = {"hourly": "/h", "daily": "/g", "monthly": "/mese", "yearly": ""}.get(
        salary.period.value if salary.period else "", ""
    )
    if salary.min and salary.max:
        return f"{salary.min:,}-{salary.max:,} {valuta}{periodo}".replace(",", ".")
    importo = salary.min or salary.max or 0
    return f"{importo:,} {valuta}{periodo}".replace(",", ".")


# --- gestione delle fonti -----------------------------------------------------


@sources_app.command("list")
def list_sources() -> None:
    """Elenca le fonti registrate, con stato e configurazione."""
    from ..config import get_settings
    from ..pipeline.ingest import sync_sources
    from ..sources import get_adapter_class

    settings = get_settings()
    with session_scope() as session:
        righe = sync_sources(session)

        table = Table(title="Fonti", header_style="bold")
        table.add_column("Slug")
        table.add_column("Nome")
        table.add_column("Stato")
        table.add_column("Chiavi")
        table.add_column("Board / config", overflow="fold")
        table.add_column("Ultima run")

        for riga in righe:
            adapter = get_adapter_class(riga.adapter)(settings, riga.config)
            mancanti = adapter.missing_settings()
            boards = riga.config.get("boards") or []
            table.add_row(
                riga.adapter,
                riga.display_name,
                "[green]attiva[/]" if riga.enabled else "[dim]spenta[/]",
                "[red]" + ", ".join(mancanti) + "[/]" if mancanti else "[green]ok[/]",
                ", ".join(str(b) for b in boards) if boards else "",
                riga.last_run_at.strftime("%Y-%m-%d %H:%M") if riga.last_run_at else "mai",
            )
        console.print(table)
        console.print(
            "\nPer seguire una board aziendale: "
            "[bold]jobboard sources boards greenhouse --add nomeazienda[/]"
        )


@sources_app.command("enable")
def enable_source(
    slug: Annotated[str, typer.Argument(help="Slug della fonte.")],
    off: Annotated[bool, typer.Option("--off", help="Spegne invece di accendere.")] = False,
) -> None:
    """Accende o spegne una fonte."""
    with session_scope() as session:
        riga = _find_source(session, slug)
        riga.enabled = not off
        console.print(f"{slug}: {'[dim]spenta[/]' if off else '[green]attiva[/]'}")


@sources_app.command("boards")
def manage_boards(
    slug: Annotated[str, typer.Argument(help="greenhouse, lever, ashby o workable.")],
    add: Annotated[list[str] | None, typer.Option("--add", help="Token da seguire.")] = None,
    remove: Annotated[list[str] | None, typer.Option("--remove", help="Token da togliere.")] = None,
) -> None:
    """Gestisce le board aziendali seguite da un adapter ATS.

    Il token e' il nome dell'azienda nell'URL della sua pagina lavora-con-noi:
    ``boards.greenhouse.io/stripe`` -> ``stripe``,
    ``jobs.lever.co/ro`` -> ``ro``, ``jobs.ashbyhq.com/ramp`` -> ``ramp``.
    """
    with session_scope() as session:
        riga = _find_source(session, slug)
        config = dict(riga.config)
        boards = [str(b) for b in (config.get("boards") or [])]
        for token in add or []:
            if token not in boards:
                boards.append(token)
        for token in remove or []:
            if token in boards:
                boards.remove(token)

        config["boards"] = boards
        # JSONB non traccia le mutazioni: senza riassegnare il campo, SQLAlchemy
        # non si accorge del cambiamento e non emette l'UPDATE.
        riga.config = config
        console.print(f"{slug}: {len(boards)} board seguite — {', '.join(boards) or 'nessuna'}")


def _find_source(session: Session, slug: str) -> Source:
    """Cerca la fonte, registrando prima quelle nuove.

    Senza il sync, configurare una board prima della prima raccolta fallirebbe
    con "fonte sconosciuta" pur essendo un adapter perfettamente esistente.
    """
    from ..pipeline.ingest import sync_sources

    for riga in sync_sources(session):
        if riga.adapter == slug:
            return riga
    console.print(f"[red]Fonte sconosciuta:[/] {slug}")
    raise typer.Exit(1)
