"""Il canale con cui la pipeline dice a che punto e'.

Un modulo a se' e non un alias dentro ``match`` o ``ingest``: lo usano entrambi,
e un ``run_pipeline`` che li esegue in fila deve poter passare loro **la stessa
firma** dopo averne riscalato la percentuale. Qui non si importa niente del
resto della pipeline, quindi nessuno dei due si tira dietro l'altro.

Chi non ha una barra da aggiornare passa ``None``: la pipeline da riga di
comando non paga niente per una funzionalita' della dashboard.
"""

from __future__ import annotations

from collections.abc import Callable

#: Percentuale (0-100) e messaggio breve. Il messaggio finisce in
#: ``task.progress_message``, che e' un VARCHAR(300) mostrato per intero.
Progress = Callable[[int, str], None]


def avanza(progress: Progress | None, percentuale: int, messaggio: str) -> None:
    """Segnala l'avanzamento, se qualcuno sta ascoltando."""
    if progress:
        progress(percentuale, messaggio)


def fascia(progress: Progress | None, da: int, a: int) -> Progress | None:
    """Comprime un avanzamento 0-100 nell'intervallo ``da``-``a``.

    ``run_pipeline`` esegue raccolta e matching di seguito, e ognuna delle due
    conta da 0 a 100 per conto suo. Senza questa compressione la barra della
    dashboard arriverebbe in fondo a meta' lavoro e ripartirebbe da zero, che e'
    il modo piu' rapido di far credere che qualcosa sia andato storto.
    """
    if progress is None:
        return None

    ampiezza = a - da

    def scalato(percentuale: int, messaggio: str) -> None:
        limitata = max(0, min(100, percentuale))
        progress(da + round(ampiezza * limitata / 100), messaggio)

    return scalato
