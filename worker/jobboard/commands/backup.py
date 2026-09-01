"""Comando ``backup``: esportazione CSV del database, con rotazione (Fase 10.3)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

console = Console()

backup_app = typer.Typer(
    name="backup",
    help="Backup del database come CSV, in data/backups/.",
    no_args_is_help=True,
)


@backup_app.command("run")
def run_backup_command(
    keep: Annotated[
        int | None,
        typer.Option("--keep", help="Quanti archivi tenere. Default: BACKUP_KEEP_COUNT."),
    ] = None,
    scheduled: Annotated[
        bool,
        typer.Option(
            "--scheduled",
            help="Rispetta l'interruttore 'Backup notturno' della pagina Impostazioni.",
        ),
    ] = False,
) -> None:
    """Esporta ogni tabella in un CSV, comprime, ruota i backup piu' vecchi.

    E' lo stesso comando che ``setup-scheduler`` accoda ogni notte: eseguirlo a
    mano serve solo per una prova, o per un backup fuori programma prima di un
    cambio rischioso (una migration, una modifica ai criteri di matching).

    ``--scheduled`` e' il flag che ``setup-scheduler.cmd`` passa nell'azione di
    "JobBoard - backup notturno": solo con quel flag il comando legge
    l'interruttore di Impostazioni e puo' non fare nulla. Lanciato a mano, senza
    il flag, il backup parte sempre — "fallo prima di questa migration" non deve
    dipendere da un interruttore pensato per il solo tick automatico.
    """
    from ..config import get_settings
    from ..db import session_scope

    settings = get_settings()

    if scheduled:
        from ..queue_settings import load_backup_settings

        with session_scope() as session:
            automatico = load_backup_settings(session).enabled
        if not automatico:
            console.print("[dim]backup notturno spento nelle Impostazioni[/]")
            return

    from ..backup import run_backup

    quanti = keep if keep is not None else settings.backup_keep_count

    with session_scope() as session:
        risultato = run_backup(session, data_dir=settings.data_dir, keep=quanti)

    console.print(f"[green]Backup scritto[/] in {risultato.path}")
    console.print(f"{risultato.rows_total} righe totali, {risultato.size_bytes // 1024} KB")
    if risultato.removed:
        console.print(f"[dim]rimossi per rotazione (tengo gli ultimi {quanti}):[/]")
        for file in risultato.removed:
            console.print(f"  [dim]- {file.name}[/]")


@backup_app.command("list")
def list_backups() -> None:
    """Gli archivi presenti in ``data/backups/``, dal piu' recente."""
    from ..config import get_settings

    cartella = get_settings().data_dir / "backups"
    if not cartella.exists():
        console.print("[yellow]Nessun backup ancora: la cartella non esiste.[/]")
        return

    archivi = sorted(cartella.glob("*.zip"), reverse=True)
    if not archivi:
        console.print("[yellow]Nessun backup trovato.[/]")
        return

    tabella = Table(title="Backup disponibili", header_style="bold")
    tabella.add_column("File")
    tabella.add_column("Dimensione", justify="right")
    for file in archivi:
        tabella.add_row(file.name, f"{file.stat().st_size // 1024} KB")
    console.print(tabella)


__all__ = ["backup_app"]
