"""Comandi ``match`` e ``matches``: esecuzione dell'imbuto e lettura dei risultati."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from ..db import session_scope
from ..models import Job, Match, Setting
from ..models.enums import MatchStatus, Seniority

if TYPE_CHECKING:
    from ..pipeline.match import MatchReport

console = Console()

matches_app = typer.Typer(
    name="matches",
    help="Punteggi di compatibilita': elenco, dettaglio, criteri dello Stadio 0.",
    no_args_is_help=True,
)


def _score_style(score: int) -> str:
    if score >= 75:
        return "bold green"
    if score >= 60:
        return "yellow"
    return "dim"


def match_command(
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--commit", help="Calcola senza scrivere sul database.")
    ] = True,
    rescore: Annotated[
        bool, typer.Option("--rescore", help="Rivaluta anche gli annunci gia' valutati.")
    ] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Massimo di annunci da esaminare.")
    ] = None,
    top: Annotated[
        int | None, typer.Option("--top", help="Quanti annunci passano alla rubrica LLM.")
    ] = None,
    use_llm: Annotated[
        bool,
        typer.Option(
            "--llm/--no-llm",
            help="Con --no-llm si ferma allo Stadio 1: nessuna chiamata, nessun punteggio finale.",
        ),
    ] = True,
    show: Annotated[int, typer.Option("--show", help="Quante righe elencare.")] = 15,
) -> None:
    """Calcola i punteggi di compatibilita' sugli annunci non ancora valutati."""
    from ..config import get_settings
    from ..pipeline.match import MatchingError, run_matching

    settings = get_settings()
    with session_scope() as session:
        try:
            report = run_matching(
                session,
                rescore=rescore,
                limit=limit,
                top_n=top,
                use_llm=use_llm,
                dry_run=dry_run,
            )
        except MatchingError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(1) from exc

        _render_funnel(report)
        if report.criteria.inactive:
            _render_inactive(report)
        _render_rejections(report)

        if report.scored:
            _render_scored(report, show, settings.match_threshold)
        elif report.ranked:
            _render_ranked(report, show)
        else:
            console.print("[yellow]Nessun annuncio ha superato i filtri.[/]")

        if report.errors:
            console.print(f"\n[red]{len(report.errors)} annunci non valutati:[/]")
            for job_id, errore in report.errors[:5]:
                console.print(f"  job {job_id}: {errore}")

        if dry_run:
            # Precisione voluta: gli embedding **vengono** salvati anche in
            # dry-run. Sono una cache derivata dall'annuncio, non una decisione:
            # buttarli via costringerebbe a ricalcolarli a ogni prova. Quello che
            # --dry-run trattiene sono i punteggi.
            console.print(
                "\n[yellow]--dry-run: nessun punteggio e' stato salvato.[/] "
                "Gli embedding calcolati restano in cache sul database. "
                "Ripeti con [bold]--commit[/] per salvare i match."
            )
        else:
            console.print(f"\n[green]salvati:[/] {report.persisted} match")


def _render_funnel(report: MatchReport) -> None:
    passati = len(report.filtered.passed)
    table = Table(title="Imbuto", header_style="bold")
    table.add_column("Stadio")
    table.add_column("Entrati", justify="right")
    table.add_column("Usciti", justify="right")
    table.add_column("Costo")

    table.add_row("0 · filtri duri", str(report.examined), str(passati), "zero")
    table.add_row("1 · coseno + BM25", str(passati), str(len(report.ranked)), "zero")
    table.add_row(
        "2 · rubrica LLM",
        str(report.stage2_entered),
        str(len(report.scored)),
        f"{report.llm_calls} chiamate, {report.input_tokens + report.output_tokens} token",
    )
    console.print(table)
    if report.embedded:
        console.print(f"[dim]{report.embedded} embedding calcolati e salvati.[/]")


def _render_inactive(report: MatchReport) -> None:
    testo = "\n".join(f"· {avviso}" for avviso in report.criteria.inactive)
    console.print(
        Panel(
            testo,
            title="Filtri spenti per mancanza di dati",
            border_style="yellow",
            title_align="left",
        )
    )


def _render_rejections(report: MatchReport) -> None:
    conteggi = report.filtered.counts
    if not conteggi:
        return
    riga = ", ".join(f"{motivo} {quanti}" for motivo, quanti in conteggi.most_common())
    console.print(f"[dim]scartati allo Stadio 0 — {riga}[/]")


def _render_scored(report: MatchReport, limit: int, threshold: int) -> None:
    table = Table(title=f"Punteggi (soglia {threshold})", header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Ruolo", overflow="ellipsis", max_width=34)
    table.add_column("Azienda", overflow="ellipsis", max_width=20)
    table.add_column("Luogo", overflow="ellipsis", max_width=16)
    table.add_column("Match", justify="right")
    table.add_column("Ibrido", justify="right")
    table.add_column("Gap principali", overflow="ellipsis", max_width=40)

    for posizione, valutato in enumerate(report.top(limit), start=1):
        job = valutato.job
        table.add_row(
            str(posizione),
            job.title,
            job.company,
            ", ".join(p for p in (job.city, job.country) if p) or "—",
            f"[{_score_style(valutato.score)}]{valutato.score}[/]",
            f"{valutato.ranked.hybrid:.2f}",
            "; ".join(valutato.assessment.gaps[:2]) or "[green]nessuno[/]",
        )
    console.print(table)

    sopra = report.above(threshold)
    console.print(f"[bold]{len(sopra)}[/] annunci sopra la soglia di {threshold}.")


def _render_ranked(report: MatchReport, limit: int) -> None:
    table = Table(title="Stadio 1 (nessuna valutazione LLM)", header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Ruolo", overflow="ellipsis", max_width=40)
    table.add_column("Azienda", overflow="ellipsis", max_width=22)
    table.add_column("Ibrido", justify="right")
    table.add_column("Coseno", justify="right")
    table.add_column("BM25", justify="right")

    for posizione, candidato in enumerate(report.ranked[:limit], start=1):
        table.add_row(
            str(posizione),
            candidato.job.title,
            candidato.job.company,
            f"{candidato.hybrid:.3f}",
            f"{candidato.semantic:.3f}",
            f"{candidato.keyword:.2f}",
        )
    console.print(table)
    console.print(
        "[dim]Il coseno assoluto vive schiacciato fra 0.79 e 0.92: conta l'ordine, "
        "non il valore.[/]"
    )


# --- lettura dei risultati salvati -------------------------------------------


@matches_app.command("list")
def list_matches(
    threshold: Annotated[
        int | None, typer.Option("--min", help="Punteggio minimo da mostrare.")
    ] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="new, seen, shortlist, hidden, applied.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Quante righe.")] = 20,
) -> None:
    """Elenca i match salvati, dal punteggio piu' alto."""
    from ..config import get_settings

    minimo = threshold if threshold is not None else get_settings().match_threshold

    with session_scope() as session:
        stmt = (
            select(Match, Job)
            .join(Job, Match.job_id == Job.id)
            .where(Match.score.is_not(None), Match.score >= minimo)
            .order_by(Match.score.desc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(Match.status == MatchStatus(status))

        righe = list(session.execute(stmt))
        if not righe:
            console.print(
                f"[yellow]Nessun match con punteggio >= {minimo}.[/] "
                "Esegui [bold]jobboard match --commit[/]."
            )
            return

        table = Table(title=f"Match (punteggio >= {minimo})", header_style="bold")
        table.add_column("id", justify="right")
        table.add_column("Ruolo", overflow="ellipsis", max_width=34)
        table.add_column("Azienda", overflow="ellipsis", max_width=20)
        table.add_column("Luogo", overflow="ellipsis", max_width=16)
        table.add_column("Mod.")
        table.add_column("Match", justify="right")
        table.add_column("Stato")

        for match, job in righe:
            punteggio = match.score or 0
            table.add_row(
                str(match.id),
                job.title,
                job.company,
                ", ".join(p for p in (job.city, job.country) if p) or "—",
                job.work_mode.value,
                f"[{_score_style(punteggio)}]{punteggio}[/]",
                match.status.value,
            )
        console.print(table)


@matches_app.command("show")
def show_match(
    match_id: Annotated[int, typer.Argument(help="id del match, dalla colonna della lista.")],
) -> None:
    """Mostra un match nel dettaglio: sotto-punteggi, motivazione, gap, requisiti."""
    from ..ai.rubric import RUBRIC_WEIGHTS

    with session_scope() as session:
        match = session.get(Match, match_id)
        if match is None:
            console.print(f"[red]Match {match_id} inesistente.[/]")
            raise typer.Exit(1)

        job = session.get(Job, match.job_id)
        assert job is not None  # vincolo di chiave esterna

        luogo = ", ".join(p for p in (job.city, job.region, job.country) if p)
        punteggio = match.score if match.score is not None else "n.d."
        console.print(
            Panel(
                f"[bold]{job.title}[/] — {job.company}\n"
                f"{luogo or 'luogo non detto'}"
                f" · {job.work_mode.value} · {job.contract_type.value} · {job.seniority.value}\n"
                f"{job.apply_url or job.url}",
                title=f"Match {match.id} — punteggio {punteggio}",
                border_style=_score_style(match.score or 0),
                title_align="left",
            )
        )

        if match.reached_stage == 0:
            console.print(f"[yellow]Scartato allo Stadio 0:[/] {match.filtered_reason}")
            return

        table = Table(title="Rubrica", header_style="bold")
        table.add_column("Criterio")
        table.add_column("Peso", justify="right")
        table.add_column("Punteggio", justify="right")
        for nome, peso in RUBRIC_WEIGHTS.items():
            valore = (match.subscores or {}).get(nome)
            table.add_row(nome, f"{peso:.0%}", "—" if valore is None else str(valore))
        table.add_row(
            "[dim]stadio 1 (ibrido)[/]",
            "",
            f"[dim]{match.hybrid_score:.3f}[/]" if match.hybrid_score else "—",
        )
        console.print(table)

        if match.rationale:
            console.print(Panel(match.rationale, title="Motivazione", title_align="left"))
        if match.gaps:
            console.print("[bold]Gap:[/]")
            for gap in match.gaps:
                console.print(f"  · {gap}")

        _render_requirements(job)


def _render_requirements(job: Job) -> None:
    requisiti = job.requirements
    if requisiti is None:
        return
    console.print("\n[bold]Requisiti estratti[/]")
    if requisiti.must_have:
        console.print(f"  obbligatori: {', '.join(requisiti.must_have)}")
    if requisiti.nice_to_have:
        console.print(f"  graditi: {', '.join(requisiti.nice_to_have)}")
    if requisiti.tech_stack:
        console.print(f"  stack: {', '.join(requisiti.tech_stack)}")
    if requisiti.min_years_experience is not None:
        console.print(f"  esperienza richiesta: {requisiti.min_years_experience}+ anni")
    if requisiti.languages_required:
        lingue = ", ".join(f"{k} {v}" for k, v in requisiti.languages_required.items())
        console.print(f"  lingue: {lingue}")
    if requisiti.remote_policy:
        console.print(f"  presenza: {requisiti.remote_policy}")
    if requisiti.red_flags:
        console.print(f"  [red]segnali negativi:[/] {', '.join(requisiti.red_flags)}")


@matches_app.command("criteria")
def edit_criteria(
    seniority: Annotated[
        str | None,
        typer.Option("--seniority", help="Il tuo livello: junior, mid, senior, lead."),
    ] = None,
    tolerance: Annotated[
        int | None, typer.Option("--tolerance", help="Livelli di distanza ammessi.")
    ] = None,
    top_n: Annotated[
        int | None, typer.Option("--top-n", help="Quanti annunci passano alla rubrica LLM.")
    ] = None,
    reserved_floor: Annotated[
        int | None,
        typer.Option(
            "--reserved-floor",
            help="Minimo riservato agli annunci di una fonte a budget (es. JSearch/LinkedIn).",
        ),
    ] = None,
    max_age: Annotated[
        int | None, typer.Option("--max-age", help="Eta' massima dell'annuncio in giorni.")
    ] = None,
    add_country: Annotated[
        list[str] | None, typer.Option("--add-country", help="Aggiunge un mercato (ISO alpha-2).")
    ] = None,
    remove_country: Annotated[
        list[str] | None, typer.Option("--remove-country", help="Toglie un mercato.")
    ] = None,
    block: Annotated[
        list[str] | None, typer.Option("--block", help="Azienda da non proporre piu'.")
    ] = None,
    unblock: Annotated[
        list[str] | None, typer.Option("--unblock", help="Toglie il blocco.")
    ] = None,
) -> None:
    """Mostra e modifica i criteri dello Stadio 0."""
    from ..pipeline.criteria import MATCHING_SETTING_KEY, load_criteria
    from ..pipeline.text import normalize_company

    with session_scope() as session:
        criteri = load_criteria(session)
        riga = session.get(Setting, MATCHING_SETTING_KEY)
        assert riga is not None  # load_criteria la crea se manca
        valori: dict[str, Any] = dict(riga.value)

        if seniority:
            valori["seniority"] = Seniority(seniority).value
        if tolerance is not None:
            valori["seniority_tolerance"] = tolerance
        if top_n is not None:
            valori["stage2_top_n"] = top_n
        if reserved_floor is not None:
            valori["stage2_reserved_floor"] = reserved_floor
        if max_age is not None:
            valori["max_age_days"] = max_age

        paesi = {str(c).upper() for c in valori.get("countries", [])}
        paesi |= {c.upper() for c in add_country or []}
        paesi -= {c.upper() for c in remove_country or []}
        valori["countries"] = sorted(paesi)

        bloccate = {str(c) for c in valori.get("blocked_companies", [])}
        bloccate |= {normalize_company(c) for c in block or []}
        bloccate -= {normalize_company(c) for c in unblock or []}
        valori["blocked_companies"] = sorted(bloccate)

        # JSONB non traccia le mutazioni: senza riassegnare, l'UPDATE non parte.
        riga.value = valori
        criteri = load_criteria(session)

        table = Table(title="Criteri dello Stadio 0", header_style="bold")
        table.add_column("Voce")
        table.add_column("Valore", overflow="fold")
        table.add_row("livello", f"{criteri.seniority.value} +/-{criteri.seniority_tolerance}")
        table.add_row("mercati", ", ".join(sorted(criteri.countries)) or "ovunque")
        table.add_row("remote fuori mercato", "ammesso" if criteri.remote_ignores_country else "no")
        table.add_row("lingue", ", ".join(sorted(criteri.languages)) or "[yellow]non dichiarate[/]")
        table.add_row(
            "autorizzazione al lavoro",
            ", ".join(sorted(criteri.authorized_countries)) or "[yellow]non dichiarata[/]",
        )
        table.add_row("eta' massima", f"{criteri.max_age_days} giorni")
        table.add_row("RAL minima", str(criteri.min_salary_eur_year or "nessuna"))
        table.add_row("aziende bloccate", ", ".join(sorted(criteri.blocked_companies)) or "nessuna")
        table.add_row("finalisti per la rubrica", str(criteri.stage2_top_n))
        table.add_row("riserva fonti a budget", str(criteri.stage2_reserved_floor))
        console.print(table)

        for avviso in criteri.inactive:
            console.print(f"[yellow]![/] {avviso}")
