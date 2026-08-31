"""Comando ``email``: controlla a mano le risposte dei recruiter (Fase 9).

Come ``jb apply send``, esegue lo stesso codice del gestore accodato dalla
dashboard (``jobboard.handlers.check_email``) passando da un
:class:`~jobboard.queue.Contesto` con un ``task_id`` fittizio: due strade non
devono produrre due risultati diversi.
"""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()
email_app = typer.Typer(
    name="email",
    help="Tracciamento post-candidatura: lettura IMAP e classificazione delle risposte.",
    no_args_is_help=True,
)


@email_app.command("check")
def check_command() -> None:
    """Legge la posta, classifica le risposte nuove, aggiorna gli stati.

    Richiede il tracciamento attivo nella pagina Impostazioni: se e'
    disattivato il comando lo dice e non apre nessuna connessione IMAP.
    """
    from ..handlers import check_email
    from ..models.enums import TaskType
    from ..queue import Contesto, TaskError

    ctx = Contesto(task_id=0, task_type=TaskType.CHECK_EMAIL, payload={})
    try:
        risultato = check_email(ctx)
    except TaskError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    if not risultato["attivo"]:
        console.print("[dim]tracciamento disattivato nelle Impostazioni: nessuna casella aperta[/]")
        return

    console.print(
        f"[green]{risultato['candidature_controllate']}[/] candidature controllate, "
        f"[bold]{risultato['mail_nuove']}[/] mail nuove, "
        f"[bold]{risultato['cambi_stato']}[/] cambi di stato, "
        f"[bold]{risultato['promemoria_inviati']}[/] promemoria inviati "
        f"(di {risultato['promemoria_dovuti']} dovuti)"
    )
    if risultato.get("promemoria_errore"):
        console.print(f"[yellow]promemoria non inviato: {risultato['promemoria_errore']}[/]")
