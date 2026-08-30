"""Il consumer della coda: il ponte fra la dashboard e questo PC.

La dashboard su Vercel non puo' chiamare il PC di casa — non ha un indirizzo, e
meta' del tempo e' spento. Inserisce quindi una riga in ``task`` e questo
processo la raccoglie.

**Tre proprieta' che non sono dettagli.**

*Il prelievo e' esclusivo.* ``SELECT ... FOR UPDATE SKIP LOCKED`` fa si' che due
processi che partono insieme prendano due task diversi invece dello stesso.
Serve gia' oggi: basta lanciare ``jb work`` due volte per sbaglio, o averlo sia
in Task Scheduler sia in un terminale.

*Il prelievo e' una transazione a se'.* Si marca ``running`` e si chiude subito.
Tenere aperta la transazione per tutta la durata del lavoro — che per un CV vuol
dire una chiamata LLM da decine di secondi — significa tenere un lock di riga su
Supabase per tutto quel tempo, e impedire al battito di scriversi.

*Il fallimento non e' definitivo al primo colpo.* ``attempts`` cresce a ogni
presa; finche' resta sotto ``max_attempts`` il task torna in coda. Una API che
risponde 503 una volta non deve costare il ricaricamento manuale di un CV.
"""

from __future__ import annotations

import datetime as dt
import logging
import platform
import signal
import time
from collections.abc import Callable
from types import FrameType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .db import session_scope
from .models import Task, WorkerHeartbeat
from .models.base import utcnow
from .models.enums import TaskStatus, TaskType

log = logging.getLogger(__name__)

#: Firma di un gestore: riceve il payload, restituisce quello che finira' in
#: ``task.result``. Il progresso si scrive con ``avanza``.
Handler = Callable[["Contesto"], dict[str, Any]]

#: Ogni quanto il battito viene riscritto. La dashboard considera offline un
#: worker fermo da due minuti: trenta secondi lasciano margine a un ritardo di
#: rete senza dichiarare acceso un PC spento.
HEARTBEAT_SECONDS = 30


class TaskError(RuntimeError):
    """Errore del gestore che vale la pena mostrare in dashboard.

    ``definitivo`` spegne il ritentativo. Serve perche' il criterio "riprova tre
    volte" e' giusto solo per i guasti passeggeri: una API che risponde 503 va
    ritentata, un profilo non ancora confermato no — la seconda e la terza presa
    troverebbero lo stesso profilo e fallirebbero allo stesso modo. Su
    ``run_pipeline`` non e' nemmeno gratis: ogni ritentativo rifa' la raccolta,
    e le chiamate JSearch sono ~200 al mese.
    """

    def __init__(self, messaggio: str, *, definitivo: bool = False) -> None:
        super().__init__(messaggio)
        self.definitivo = definitivo


class Contesto:
    """Quello che un gestore riceve: il payload e un modo per dire a che punto e'."""

    def __init__(self, task_id: int, task_type: TaskType, payload: dict[str, Any]) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.payload = payload

    def avanza(self, percentuale: int, messaggio: str) -> None:
        """Aggiorna la barra in dashboard, in una transazione tutta sua.

        Breve e separata di proposito: il progresso deve essere visibile *mentre*
        il lavoro e' in corso, e una scrittura dentro la transazione del lavoro
        si vedrebbe solo alla fine, cioe' quando non serve piu'.
        """
        with session_scope() as session:
            riga = session.get(Task, self.task_id)
            if riga is not None:
                riga.progress = max(0, min(100, percentuale))
                riga.progress_message = messaggio[:300]
        log.info("task %d: %d%% — %s", self.task_id, percentuale, messaggio)


HANDLERS: dict[TaskType, Handler] = {}


def handler(tipo: TaskType) -> Callable[[Handler], Handler]:
    """Registra il gestore di un tipo di task."""

    def decoratore(fn: Handler) -> Handler:
        HANDLERS[tipo] = fn
        return fn

    return decoratore


# --- accodamento ----------------------------------------------------------------


def enqueue_task(
    session: Session, task_type: TaskType, payload: dict[str, Any] | None = None
) -> tuple[Task, bool]:
    """Accoda un task, a meno che uno identico non sia gia' in attesa o in corso.

    Specchio Python di ``web/src/lib/tasks.ts::enqueueTask``: stessa regola,
    stesso motivo. Chi accoda da qui non e' solo il bottone della dashboard —
    e' anche ``jb work trigger``, pensato per un trigger giornaliero di Task
    Scheduler che potrebbe sovrapporsi a un run gia' in corso (un catch-up dopo
    il PC spento, o un "Aggiorna adesso" premuto a mano lo stesso giorno).
    Restituisce ``(task, True)`` se ne ha trovato uno esistente invece di
    inserirne un secondo.

    Il confronto sul payload e' nella ``WHERE``, non fatto in Python dopo aver
    letto la riga: JSONB in Postgres confronta per struttura, non per byte, e
    l'uguaglianza a livello di query e' quindi gia' insensibile all'ordine delle
    chiavi — la stessa proprieta' che il lato web sfrutta con ``::jsonb =``.
    """
    payload = payload or {}
    aperto = session.scalars(
        select(Task)
        .where(
            Task.task_type == task_type,
            Task.status.in_((TaskStatus.PENDING, TaskStatus.RUNNING)),
            Task.payload == payload,
        )
        .order_by(Task.created_at.desc())
        .limit(1)
    ).first()
    if aperto is not None:
        return aperto, True

    nuovo = Task(task_type=task_type, status=TaskStatus.PENDING, payload=payload)
    session.add(nuovo)
    session.flush()
    return nuovo, False


# --- prelievo -----------------------------------------------------------------


def claim(session: Session, tipi: tuple[TaskType, ...] | None = None) -> Contesto | None:
    """Prende un task in attesa e lo marca ``running``. ``None`` se non ce n'e'."""
    query = (
        select(Task)
        .where(
            Task.status == TaskStatus.PENDING,
            Task.attempts < Task.max_attempts,
        )
        .order_by(Task.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if tipi:
        query = query.where(Task.task_type.in_(tipi))

    riga = session.scalars(query).first()
    if riga is None:
        return None

    riga.status = TaskStatus.RUNNING
    riga.claimed_at = utcnow()
    riga.attempts += 1
    riga.error = None
    riga.progress = 0
    riga.progress_message = "in avvio"

    return Contesto(riga.id, riga.task_type, dict(riga.payload or {}))


def _concludi(task_id: int, risultato: dict[str, Any]) -> None:
    with session_scope() as session:
        riga = session.get(Task, task_id)
        if riga is None:
            return
        riga.status = TaskStatus.DONE
        riga.result = risultato
        riga.progress = 100
        riga.progress_message = "fatto"
        riga.finished_at = utcnow()


def _fallisci(task_id: int, errore: str, *, definitivo: bool = False) -> bool:
    """Segna l'errore. Restituisce ``True`` se il task tornera' in coda."""
    with session_scope() as session:
        riga = session.get(Task, task_id)
        if riga is None:
            return False

        riga.error = errore[:4000]
        if not definitivo and riga.attempts < riga.max_attempts:
            riga.status = TaskStatus.PENDING
            riga.progress_message = f"tentativo {riga.attempts} fallito, riprova"
            return True

        riga.status = TaskStatus.FAILED
        riga.progress_message = "non riuscito"
        riga.finished_at = utcnow()
        return False


# --- battito ------------------------------------------------------------------


def heartbeat(session: Session) -> None:
    """Scrive il battito. E' quello che accende il pallino in dashboard."""
    riga = session.get(WorkerHeartbeat, 1)
    if riga is None:
        riga = WorkerHeartbeat(id=1, last_seen_at=utcnow())
        session.add(riga)
    riga.last_seen_at = utcnow()
    riga.version = __version__[:32]
    riga.hostname = platform.node()[:128]


# --- ciclo --------------------------------------------------------------------


def run_once(tipi: tuple[TaskType, ...] | None = None) -> bool:
    """Esegue al piu' un task. ``True`` se ne ha trovato uno."""
    # Importato qui e non in testa al modulo: ``handlers`` importa ``queue`` per
    # il decoratore, quindi in testa sarebbe un ciclo. Importarlo dentro la
    # funzione registra i gestori la prima volta che servono davvero, e lascia
    # che chi importa la coda solo per leggere un battito non si tiri dietro
    # fastembed e il client LLM.
    from . import handlers  # noqa: F401

    with session_scope() as session:
        contesto = claim(session, tipi)
    if contesto is None:
        return False

    gestore = HANDLERS.get(contesto.task_type)
    if gestore is None:
        # Un tipo che il codice non conosce non e' un errore da ritentare tre
        # volte: e' una fase non ancora scritta, e ritentarla non la scrivera'.
        with session_scope() as session:
            riga = session.get(Task, contesto.task_id)
            if riga is not None:
                riga.status = TaskStatus.FAILED
                riga.error = f"nessun gestore per {contesto.task_type}: fase non ancora sviluppata"
                riga.finished_at = utcnow()
        log.warning("task %d di tipo %s senza gestore", contesto.task_id, contesto.task_type)
        return True

    log.info("task %d (%s) preso in carico", contesto.task_id, contesto.task_type)
    try:
        risultato = gestore(contesto)
    except Exception as exc:
        log.exception("task %d fallito", contesto.task_id)
        # Il messaggio di un TaskError e' scritto per essere letto in dashboard:
        # anteporgli "TaskError:" aggiungerebbe al lettore l'unico dettaglio che
        # non lo riguarda. Per tutto il resto il tipo dell'eccezione e' meta'
        # della diagnosi e resta.
        riprova = _fallisci(
            contesto.task_id,
            str(exc) if isinstance(exc, TaskError) else f"{type(exc).__name__}: {exc}",
            definitivo=isinstance(exc, TaskError) and exc.definitivo,
        )
        log.info("task %d: %s", contesto.task_id, "torna in coda" if riprova else "abbandonato")
    else:
        _concludi(contesto.task_id, risultato)
        log.info("task %d concluso", contesto.task_id)
    return True


def serve(poll_seconds: int = 30, tipi: tuple[TaskType, ...] | None = None) -> None:
    """Il ciclo: batte, svuota la coda, aspetta, ricomincia.

    Si ferma con Ctrl+C **al termine del task in corso**, non a meta': un CV
    interrotto fra l'estrazione e il salvataggio lascerebbe la coda con un task
    ``running`` che nessuno riprendera' piu'.
    """
    fermati = False

    def chiedi_stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal fermati
        if fermati:
            raise KeyboardInterrupt
        fermati = True
        log.info("arresto richiesto: finisco il task in corso e mi fermo (Ctrl+C di nuovo forza)")

    signal.signal(signal.SIGINT, chiedi_stop)

    ultimo_battito = 0.0
    log.info("worker in ascolto, polling ogni %d s", poll_seconds)

    while not fermati:
        adesso = time.monotonic()
        if adesso - ultimo_battito >= HEARTBEAT_SECONDS:
            try:
                with session_scope() as session:
                    heartbeat(session)
                ultimo_battito = adesso
            except Exception:
                # Il battito e' un'informazione, non il lavoro: se il database
                # non risponde si riprova al giro dopo invece di uscire.
                log.warning("battito non scritto, riprovo", exc_info=True)

        try:
            lavorato = run_once(tipi)
        except Exception:
            log.exception("errore nel ciclo, continuo")
            lavorato = False

        if not lavorato and not fermati:
            # Il sonno e' spezzettato per poter rispondere a Ctrl+C entro un
            # secondo invece che entro mezzo minuto.
            for _ in range(poll_seconds):
                if fermati:
                    break
                time.sleep(1)

    log.info("worker fermo")


def ultimo_battito() -> dt.datetime | None:
    with session_scope() as session:
        riga = session.get(WorkerHeartbeat, 1)
        return riga.last_seen_at if riga else None
