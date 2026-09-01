"""Comandi del consumer della coda."""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console

from ..config import get_settings
from ..db import session_scope
from ..models.enums import TaskType
from ..queue import enqueue_task, heartbeat, run_once, serve
from ..queue_settings import load_auto_worker_settings

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
        # `--once` e' la forma che userebbe Task Scheduler (`.\setup-scheduler`
        # crea "JobBoard - worker", un tick ogni minuto): prima di reclamare
        # qualunque cosa, legge l'interruttore che la pagina Impostazioni
        # scrive. Acceso e' il default — vedi `queue_settings` — quindi non
        # cambia nulla per chi non ha mai aperto quella pagina. Spento a mano,
        # un tick non tocca la coda e non scrive il battito: "worker offline"
        # deve restare vero finche' un bottone premuto in dashboard non verra'
        # preso in carico da solo, e con l'interruttore spento e' esattamente
        # cosi'. Non riguarda `serve()`: un `jb work` lanciato a mano resta
        # un'azione esplicita, non il tick automatico.
        with session_scope() as session:
            automatico = load_auto_worker_settings(session).enabled
        if not automatico:
            console.print("[dim]avvio automatico spento nelle Impostazioni[/]")
            return

        # Il battito si scrive anche qui. Un worker che ha appena svuotato la
        # coda ma risulta "mai visto" in dashboard e' un'informazione
        # sbagliata, non mancante.
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


@work_app.command("trigger")
def trigger() -> None:
    """Accoda una run completa (raccolta + matching), senza eseguirla qui.

    Pensato per un'attivita' giornaliera di Task Scheduler: fa la stessa cosa
    del bottone "Aggiorna adesso" della dashboard — accoda un ``run_pipeline`` —
    cosi' che chi lo esegue davvero resti sempre ``jb work``, con barra di
    avanzamento e ultima raccolta aggiornate in dashboard come per un click
    manuale. Se un run e' gia' in coda o in corso non ne accoda un secondo: due
    trigger vicini (un catch-up dopo il PC spento, o un click manuale lo stesso
    giorno) non devono raddoppiare la raccolta.
    """
    with session_scope() as session:
        _, gia_in_coda = enqueue_task(session, TaskType.RUN_PIPELINE)

    console.print(
        "[dim]una raccolta era gia' in coda o in corso, non ne ho accodata un'altra[/]"
        if gia_in_coda
        else "[green]raccolta accodata[/]: jb work la prendera' entro mezzo minuto"
    )
