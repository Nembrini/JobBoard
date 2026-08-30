"""Comando ``apply``: prepara a mano la candidatura per un annuncio approvato.

Come ``jb cv generate``/``jb cv check``, esegue lo stesso codice del gestore
accodato dalla dashboard (``jobboard.handlers.apply_to_job``): costruire un
:class:`~jobboard.queue.Contesto` con un ``task_id`` fittizio e chiamarlo
direttamente evita di avere due strade che compilano il form in due modi
leggermente diversi. ``Contesto.avanza`` tollera un ``task_id`` che non
corrisponde a nessuna riga — cerca la riga, non la trova, non scrive niente —
quindi qui la barra di avanzamento in dashboard resta semplicemente ferma.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()
apply_app = typer.Typer(
    name="apply",
    help="Candidatura: prepara il form nel browser, senza inviarlo.",
    no_args_is_help=True,
)


@apply_app.command("send")
def send_command(
    match_id: Annotated[int, typer.Argument(help="Id del match, da 'jobboard matches list'.")],
    confirm_new_company: Annotated[
        bool,
        typer.Option(
            "--confirm-new-company",
            help="Conferma la preparazione verso un'azienda mai contattata prima.",
        ),
    ] = False,
) -> None:
    """Apre il form (o segna il link, per il Tier C) e si ferma prima dell'invio.

    Richiede una candidatura gia' ``approved`` — approvala prima dalla pagina
    CV della dashboard, o con ``jobboard matches show``. **Non spedisce
    niente**: guarda ``jobboard.apply`` per il perche'.
    """
    from ..handlers import apply_to_job
    from ..models.enums import TaskType
    from ..queue import Contesto, TaskError

    ctx = Contesto(
        task_id=0,
        task_type=TaskType.APPLY,
        payload={"match_id": match_id, "confirmed_new_company": confirm_new_company},
    )
    try:
        risultato = apply_to_job(ctx)
    except TaskError as exc:
        console.print(f"[red]{exc}[/]")
        if "prima candidatura verso questa azienda" in str(exc):
            console.print("Ripeti con [bold]--confirm-new-company[/] se e' voluto.")
        raise typer.Exit(1) from exc

    _render_esito(risultato)


def _render_esito(risultato: dict[str, Any]) -> None:
    tabella = Table(title="Candidatura preparata", header_style="bold")
    tabella.add_column("Voce")
    tabella.add_column("Valore", overflow="fold")

    tabella.add_row("Annuncio", f"{risultato.get('title')} — {risultato.get('company')}")
    tabella.add_row("Tier", str(risultato.get("tier")))
    tabella.add_row("Dry-run", "si'" if risultato.get("dry_run") else "no")
    if risultato.get("apply_url"):
        tabella.add_row("URL", str(risultato["apply_url"]))
    if "fields_filled" in risultato:
        tabella.add_row("Campi compilati", ", ".join(risultato["fields_filled"]) or "nessuno")
    if risultato.get("fields_unmatched"):
        tabella.add_row("Campi non trovati", ", ".join(risultato["fields_unmatched"]))
    if "resume_uploaded" in risultato:
        tabella.add_row("CV caricato", "si'" if risultato["resume_uploaded"] else "no")
    if risultato.get("screenshot_path"):
        tabella.add_row("Screenshot", str(risultato["screenshot_path"]))
    console.print(tabella)

    if risultato.get("next"):
        console.print(f"\n[yellow]{risultato['next']}[/]")
