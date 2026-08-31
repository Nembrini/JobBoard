"""Comandi ``profile`` e ``candidate``: dal PDF al database.

Il flusso e' in tre passi, e il passo di mezzo e' umano:

1. ``profile import CV.pdf``  estrae, struttura con l'LLM, calcola l'embedding,
   salva sul database e scrive il JSON. Il profilo resta **non rivisto**.
2. correggi ``data/cv/master_profile.json`` a mano.
3. ``profile load``  rilegge il JSON, rifa' l'embedding e lo segna come rivisto.

Il passo 2 non e' burocrazia: da questo JSON derivano tutti i punteggi di
compatibilita' e ogni CV su misura. Un errore qui si propaga a valle per
settimane senza che nulla lo segnali.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..config import get_settings
from ..db import session_scope
from ..models.enums import LlmUsagePurpose
from ..schemas import CandidateAnswers, MasterProfile
from ..store import (
    StoredProfile,
    load_candidate,
    load_profile,
    record_llm_usage,
    save_candidate,
    save_profile,
)

console = Console()

profile_app = typer.Typer(
    name="profile",
    help="Profilo professionale: estrazione dal CV, revisione, embedding.",
    no_args_is_help=True,
)
candidate_app = typer.Typer(
    name="candidate",
    help="Risposte standard ai form di candidatura.",
    no_args_is_help=True,
)


def _profile_json_path() -> Path:
    return get_settings().data_dir / "cv" / "master_profile.json"


def _candidate_json_path() -> Path:
    return get_settings().data_dir / "cv" / "candidate_profile.json"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _show_warnings(warnings: list[str], title: str) -> None:
    if not warnings:
        console.print(f"[green]{title}: nessun avvertimento[/]")
        return
    console.print(f"\n[yellow]{title}[/]")
    for warning in warnings:
        console.print(f"  [yellow]-[/] {warning}")


# --- profile -----------------------------------------------------------------


@profile_app.command("import")
def import_cv(
    path: Annotated[Path, typer.Argument(help="CV in PDF o DOCX.")],
    save: Annotated[
        bool, typer.Option("--save/--no-save", help="Scrive anche sul database.")
    ] = True,
    json_out: Annotated[
        Path | None, typer.Option("--json-out", help="Dove scrivere il JSON da rivedere.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Sovrascrive il JSON gia' presente.")
    ] = False,
) -> None:
    """Estrae il CV, lo struttura con l'LLM e lo salva come **non rivisto**."""
    from ..ai.embeddings import get_embedder
    from ..cv import extract, structure

    # Il JSON e' il file che correggi a mano, e la correzione e' il passaggio piu'
    # lungo di tutta la Fase 1: una nuova estrazione non deve poterla cancellare
    # perche' hai rieseguito il comando per sbaglio.
    target = json_out or _profile_json_path()
    if target.exists() and not force:
        console.print(
            f"[yellow]{target} esiste gia'[/] e contiene forse le tue correzioni.\n"
            "Usa [bold]--force[/] per sovrascriverlo, oppure [bold]--json-out ALTRO.json[/] "
            "per confrontare la nuova estrazione con quella che hai gia'."
        )
        raise typer.Exit(1)

    document = extract(path)
    console.print(
        f"estratti [bold]{document.char_count}[/] caratteri da {document.source_name} "
        f"con {document.method} (lingua: {document.language or 'sconosciuta'})"
    )

    profile, warnings, usage = structure(document)

    embedder = get_embedder()
    embedding = embedder.embed_profile(profile.to_embedding_text())
    console.print(
        f"embedding calcolato: {embedder.dim} dimensioni con [bold]{embedder.model_name}[/]"
    )

    _write_json(target, profile.model_dump(mode="json"))
    console.print(f"profilo scritto in [bold]{target}[/]")

    if save:
        with session_scope() as session:
            stored = save_profile(
                session,
                profile=profile,
                embedding=embedding,
                embedding_model=embedder.model_name,
                reviewed=False,
                raw_text=document.text,
                source_file_name=document.source_name,
            )
            # Stessa registrazione del gestore ``reparse_profile``: due strade
            # verso ``structure()`` non devono produrre due contabilita' diverse.
            record_llm_usage(
                session,
                purpose=LlmUsagePurpose.CV_STRUCTURE,
                model=usage.model,
                calls=1,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        _render_profile(stored)
    else:
        _render_summary(profile)

    _show_warnings(warnings, "Da controllare nel JSON")
    console.print(
        f"\n[bold]Ora:[/] apri {target}, correggilo, poi esegui "
        "[bold]jobboard profile load[/] per confermarlo."
    )


@profile_app.command("load")
def load_reviewed(
    path: Annotated[Path | None, typer.Argument(help="JSON del profilo.")] = None,
    reviewed: Annotated[
        bool,
        typer.Option(
            "--reviewed/--not-reviewed",
            help="Segna il profilo come rivisto a mano. E' il flag che sblocca il matching.",
        ),
    ] = True,
) -> None:
    """Ricarica il JSON corretto a mano, ricalcola l'embedding e lo conferma."""
    from ..ai.embeddings import get_embedder

    target = path or _profile_json_path()
    if not target.exists():
        console.print(f"[red]{target} non esiste.[/] Esegui prima 'jobboard profile import'.")
        raise typer.Exit(1)

    profile = MasterProfile.model_validate_json(target.read_text(encoding="utf-8"))

    embedder = get_embedder()
    embedding = embedder.embed_profile(profile.to_embedding_text())

    with session_scope() as session:
        stored = save_profile(
            session,
            profile=profile,
            embedding=embedding,
            embedding_model=embedder.model_name,
            reviewed=reviewed,
        )
    _render_profile(stored)


@profile_app.command("embed")
def reembed() -> None:
    """Ricalcola l'embedding del profilo salvato, senza toccare il resto.

    Serve dopo un cambio di ``EMBEDDING_MODEL``: vettori prodotti da modelli
    diversi non sono confrontabili fra loro.
    """
    from ..ai.embeddings import get_embedder

    embedder = get_embedder()
    with session_scope() as session:
        current = load_profile(session)
        if current is None:
            console.print("[red]Nessun profilo salvato.[/] Esegui 'jobboard profile import'.")
            raise typer.Exit(1)
        stored = save_profile(
            session,
            profile=current.profile,
            embedding=embedder.embed_profile(current.profile.to_embedding_text()),
            embedding_model=embedder.model_name,
            reviewed=current.reviewed,
        )
    _render_profile(stored)


@profile_app.command("show")
def show_profile(
    dump: Annotated[
        bool, typer.Option("--json", help="Stampa il JSON completo invece del riepilogo.")
    ] = False,
) -> None:
    """Mostra il profilo salvato sul database."""
    with session_scope() as session:
        stored = load_profile(session)
    if stored is None:
        console.print("[yellow]Nessun profilo sul database.[/] Esegui 'jobboard profile import'.")
        raise typer.Exit(1)

    if dump:
        console.print_json(stored.profile.model_dump_json())
        return

    _render_profile(stored)
    settings = get_settings()
    if not stored.embedding_is_current(settings.embedding_model):
        console.print(
            f"[yellow]L'embedding non e' aggiornato[/] "
            f"(salvato: {stored.embedding_model or 'nessuno'}, "
            f"configurato: {settings.embedding_model}). Esegui 'jobboard profile embed'."
        )


def _render_profile(stored: StoredProfile) -> None:
    _render_summary(stored.profile)

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_row(
        "revisione",
        "[green]rivisto a mano[/]" if stored.reviewed else "[yellow]NON rivisto[/]",
    )
    if stored.reviewed_at:
        table.add_row("", stored.reviewed_at.strftime("%Y-%m-%d %H:%M UTC"))
    table.add_row(
        "embedding",
        f"{len(stored.embedding)} dimensioni, {stored.embedding_model}"
        if stored.embedding is not None
        else "[yellow]assente[/]",
    )
    table.add_row("origine", stored.source_file_name)
    table.add_row("aggiornato", stored.updated_at.strftime("%Y-%m-%d %H:%M UTC"))
    console.print(table)


def _render_summary(profile: MasterProfile) -> None:
    bullets = [b for e in profile.experiences for b in e.bullets]
    with_result = sum(1 for b in bullets if b.result)

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_row("nome", profile.contact.full_name)
    table.add_row("headline", profile.headline or "—")
    table.add_row("email", profile.contact.email or "[yellow]assente[/]")
    table.add_row("esperienze", str(len(profile.experiences)))
    table.add_row("bullet", f"{len(bullets)}, con risultato misurabile: {with_result}")
    table.add_row("formazione", str(len(profile.education)))
    table.add_row("progetti", str(len(profile.projects)))
    table.add_row("skill hard", str(len(profile.skills.hard)))
    table.add_row(
        "lingue",
        ", ".join(f"{lang.code} {lang.level}" for lang in profile.languages)
        or "[yellow]nessuna[/]",
    )
    console.print(table)


# --- candidate ---------------------------------------------------------------


@candidate_app.command("init")
def init_candidate(
    force: Annotated[bool, typer.Option("--force", help="Sovrascrive il file esistente.")] = False,
) -> None:
    """Crea la bozza delle risposte ai form, partendo dal profilo salvato."""
    target = _candidate_json_path()
    if target.exists() and not force:
        console.print(
            f"[yellow]{target} esiste gia'.[/] Modificalo a mano, oppure usa --force "
            "per rigenerarlo dal profilo (perdendo quello che c'e' dentro)."
        )
        raise typer.Exit(1)

    with session_scope() as session:
        stored = load_profile(session)
    if stored is None:
        console.print("[red]Nessun profilo salvato.[/] Esegui prima 'jobboard profile import'.")
        raise typer.Exit(1)

    answers = CandidateAnswers.from_master_profile(stored.profile)
    _write_json(target, answers.model_dump(mode="json"))
    console.print(f"bozza scritta in [bold]{target}[/]")
    _render_candidate(answers)
    _show_warnings(answers.warnings(), "Da compilare a mano")
    console.print(
        f"\n[bold]Ora:[/] apri {target}, compila i campi mancanti, poi esegui "
        "[bold]jobboard candidate load[/]."
    )


@candidate_app.command("load")
def load_candidate_file(
    path: Annotated[Path | None, typer.Argument(help="JSON delle risposte.")] = None,
) -> None:
    """Valida e salva le risposte ai form sul database."""
    target = path or _candidate_json_path()
    if not target.exists():
        console.print(f"[red]{target} non esiste.[/] Esegui prima 'jobboard candidate init'.")
        raise typer.Exit(1)

    answers = CandidateAnswers.model_validate_json(target.read_text(encoding="utf-8"))
    with session_scope() as session:
        save_candidate(session, answers)

    console.print("[green]Risposte salvate.[/]")
    _render_candidate(answers)
    _show_warnings(answers.warnings(), "Ancora mancante")


@candidate_app.command("show")
def show_candidate(
    dump: Annotated[
        bool, typer.Option("--json", help="Stampa il JSON completo invece del riepilogo.")
    ] = False,
) -> None:
    """Mostra le risposte salvate sul database."""
    with session_scope() as session:
        stored = load_candidate(session)
    if stored is None:
        console.print("[yellow]Nessuna risposta salvata.[/] Esegui 'jobboard candidate init'.")
        raise typer.Exit(1)

    if dump:
        console.print_json(stored.answers.model_dump_json())
        return

    _render_candidate(stored.answers)
    console.print(f"aggiornato: {stored.updated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    _show_warnings(stored.answers.warnings(), "Ancora mancante")


def _render_candidate(answers: CandidateAnswers) -> None:
    salary = "—"
    if answers.salary_expectation_min or answers.salary_expectation_max:
        lo = f"{answers.salary_expectation_min:,}" if answers.salary_expectation_min else "?"
        hi = f"{answers.salary_expectation_max:,}" if answers.salary_expectation_max else "?"
        salary = f"{lo} - {hi} {answers.salary_currency}"

    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_row("nome", answers.full_name)
    table.add_row("email", answers.email)
    table.add_row("telefono", answers.phone or "[yellow]assente[/]")
    table.add_row(
        "residenza", ", ".join(p for p in (answers.city, answers.country) if p) or "[yellow]—[/]"
    )
    table.add_row("LinkedIn", answers.linkedin_url or "[yellow]assente[/]")
    table.add_row("GitHub", answers.github_url or "—")
    table.add_row(
        "diritto al lavoro",
        ", ".join(f"{c}: {s}" for c, s in sorted(answers.work_authorization.items()))
        or "[yellow]non dichiarato[/]",
    )
    table.add_row("disponibile a trasferirsi", "sì" if answers.willing_to_relocate else "no")
    table.add_row(
        "preavviso",
        f"{answers.notice_period_days} giorni"
        if answers.notice_period_days is not None
        else "[yellow]—[/]",
    )
    table.add_row("RAL attesa", salary)
    table.add_row(
        "lingue",
        ", ".join(f"{c} {lvl}" for c, lvl in sorted(answers.languages.items()))
        or "[yellow]nessuna[/]",
    )
    console.print(table)
