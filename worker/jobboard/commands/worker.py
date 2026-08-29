"""Comandi del consumer della coda."""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console

from ..config import get_settings
from ..db import session_scope
from ..queue import heartbeat, run_once, serve

console = Console()
work_app = typer.Typer(name="work", help="Consumer della coda: esegue i task accodati dalla UI.")


@work_app.callback(invoke_without_command=True)
def work(
    ctx: typer.Context,
    once: Annotated[
        bool,
        typer.Option("--once", help="Esegue un solo task e termina, invece di restare in ascolto."),
    ] = False,
    poll: Annotated[
        int | None,
        typer.Option("--poll", help="Secondi fra un controllo e l'altro della coda."),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log piu' dettagliato.")] = False,
) -> None:
    """Resta in ascolto sulla coda ed esegue i task che arrivano dalla dashboard.

    E' il processo che rende vero l'indicatore online/offline in testata: finche'
    gira, scrive un battito ogni trenta secondi. Da fermare con Ctrl+C, che
    aspetta la fine del task in corso.
    """
    if ctx.invoked_subcommand is not None:
        return

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if once:
        # Il battito si scrive anche qui. `--once` e' la forma che userebbe Task
        # Scheduler, e un worker che ha appena svuotato la coda ma risulta "mai
        # visto" in dashboard e' un'informazione sbagliata, non mancante.
        with session_scope() as session:
            heartbeat(session)
        trovato = run_once()
        console.print("[green]un task eseguito[/]" if trovato else "[dim]coda vuota[/]")
        return

    intervallo = poll if poll is not None else get_settings().task_poll_seconds
    console.print(
        f"In ascolto sulla coda, controllo ogni [bold]{intervallo}[/] s. "
        "Ctrl+C per fermarsi al termine del task in corso."
    )
    serve(poll_seconds=intervallo)
