"""I gestori dei task accodati dalla dashboard.

Uno per tipo, registrati con ``@handler``. Importare questo modulo li iscrive:
lo fa :func:`jobboard.queue.serve` all'avvio, non l'import di ``queue``, cosi'
importare la coda per leggere un battito non tira dentro fastembed e il client
LLM.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .db import session_scope
from .models import WorkerHeartbeat
from .models.base import utcnow
from .models.enums import RunStatus, TaskType
from .queue import Contesto, TaskError, handler
from .store import load_profile, save_profile
from .store.objects import download

if TYPE_CHECKING:
    from .pipeline.ingest import IngestReport
    from .pipeline.match import MatchReport

log = logging.getLogger(__name__)


@handler(TaskType.REPARSE_PROFILE)
def reparse_profile(ctx: Contesto) -> dict[str, Any]:
    """Rilegge un CV caricato dalla dashboard e ne rifa' il profilo.

    E' la meta' locale del bottone "Sostituisci": la dashboard mette il file su
    Supabase e accoda: estrarre il testo da un PDF, farlo strutturare a un LLM e
    calcolare l'embedding sono le tre cose che su una funzione serverless non ci
    stanno, ne' come dipendenze ne' come tempo.

    **Il profilo esce ``reviewed=False``.** Un'estrazione automatica non e' una
    revisione, e il matching si rifiuta di girare su un profilo non rivisto: e'
    il guardrail della Fase 1.3, e vale anche quando a innescare l'estrazione e'
    stato un click invece di un comando. La revisione ora pero' si fa dalla
    pagina CV invece che su un file JSON.
    """
    percorso = str(ctx.payload.get("storage_path") or "")
    nome = str(ctx.payload.get("file_name") or "").strip() or "cv"
    if not percorso:
        raise TaskError("payload senza storage_path", definitivo=True)

    # Import ritardati: fastembed carica un modello ONNX da 120 MB e il client
    # LLM legge la configurazione. Nessuna delle due cose serve a un worker che
    # sta solo scrivendo il battito.
    from .ai.embeddings import get_embedder
    from .cv import extract, structure

    suffisso = Path(nome).suffix.lower() or ".pdf"

    with tempfile.TemporaryDirectory(prefix="jobboard-cv-") as cartella:
        locale = Path(cartella) / f"cv{suffisso}"

        ctx.avanza(10, "scarico il file")
        download(percorso, locale)

        ctx.avanza(25, "estraggo il testo")
        documento = extract(locale)
        if documento.char_count < 200:
            # Un PDF fatto di immagini scansionate estrae quattro caratteri di
            # metadati. Fermarsi qui e dirlo e' molto meglio che far strutturare
            # il nulla a un LLM e salvare un profilo vuoto sopra quello buono.
            raise TaskError(
                f"dal file sono usciti solo {documento.char_count} caratteri: "
                "e' una scansione senza testo selezionabile? Serve un PDF con testo vero.",
                # Lo stesso file dara' lo stesso risultato al secondo e al terzo
                # tentativo: quello che manca e' un altro file, non un'altra presa.
                definitivo=True,
            )

        ctx.avanza(45, f"{documento.char_count} caratteri estratti, struttura in corso")
        profilo, avvisi = structure(documento)

        ctx.avanza(80, "calcolo il vettore del profilo")
        embedder = get_embedder()
        embedding = embedder.embed_profile(profilo.to_embedding_text())

        ctx.avanza(95, "salvo")
        with session_scope() as session:
            precedente = load_profile(session)
            save_profile(
                session,
                profile=profilo,
                embedding=embedding,
                embedding_model=embedder.model_name,
                reviewed=False,
                raw_text=documento.text,
                # Il nome vero del file caricato, non quello del temporaneo.
                source_file_name=nome[:255],
                source_storage_path=percorso[:512],
            )

    log.info("profilo rigenerato da %s (%d avvisi)", nome, len(avvisi))
    return {
        "file_name": nome,
        "characters": documento.char_count,
        "experiences": len(profilo.experiences),
        "bullets": sum(len(e.bullets) for e in profilo.experiences),
        "warnings": avvisi,
        "replaced": precedente is not None,
        # Detto qui perche' finisce in `task.result` e la dashboard lo mostra:
        # il matching resta fermo finche' il profilo non e' confermato.
        "next": "Rivedi il profilo nella pagina CV: il matching riparte quando e' confermato.",
    }


@handler(TaskType.RUN_PIPELINE)
def run_pipeline(ctx: Contesto) -> dict[str, Any]:
    """La run completa — raccolta e poi matching — chiesta dal bottone della dashboard.

    E' lo stesso lavoro di ``jb ingest --commit`` seguito da ``jb match --commit``,
    e resta scritto in due passaggi separati per la stessa ragione per cui i
    comandi sono due: **la raccolta e' utile anche se il matching non parte**. Se
    il profilo non e' confermato gli annunci nuovi restano comunque in banca
    dati, pronti per essere valutati appena lo sara'.

    Le due meta' girano in **due transazioni distinte**. Tenerne una sola aperta
    dall'inizio della raccolta alla fine dello Stadio 2 vorrebbe dire un lock su
    Supabase per i cinque minuti buoni della rubrica LLM, e il battito che non
    riesce a scriversi: l'indicatore in testata direbbe "offline" proprio mentre
    il worker sta lavorando.
    """
    # Import ritardati come sopra: fastembed e il client LLM non devono pesare
    # su un worker che sta solo scrivendo il battito.
    from .config import get_settings
    from .pipeline.ingest import ingest
    from .pipeline.match import MatchingError, run_matching
    from .pipeline.progress import fascia

    settings = get_settings()

    ctx.avanza(2, "raccolgo dalle fonti attive")
    with session_scope() as session:
        raccolta = ingest(session, dry_run=False, progress=fascia(ctx.avanza, 2, 55))

    if raccolta.status is RunStatus.FAILED:
        # Tutte le fonti giu' insieme e' quasi sempre la rete di casa, non nove
        # API rotte contemporaneamente: questo e' il caso in cui il ritentativo
        # automatico della coda serve davvero, quindi non e' definitivo.
        _segna_run(RunStatus.FAILED)
        raise TaskError(f"nessuna fonte ha risposto: {_primo_errore(raccolta)}")

    log.info(
        "raccolta: %d annunci, %d nuovi, %d aggiornati, %d chiamate",
        raccolta.fetched,
        raccolta.persisted_new,
        raccolta.persisted_updated,
        raccolta.api_calls,
    )

    ctx.avanza(57, f"{raccolta.persisted_new} annunci nuovi, valuto la compatibilita'")
    try:
        with session_scope() as session:
            valutazione = run_matching(session, dry_run=False, progress=fascia(ctx.avanza, 57, 100))
    except MatchingError as exc:
        # Manca il profilo o non e' stato confermato. Il messaggio e' gia'
        # scritto per essere letto da chi guarda la dashboard, e ripetere il
        # tentativo lo troverebbe identico: la raccolta pero' e' salva, ed e'
        # quello che dice la seconda meta' del messaggio.
        _segna_run(RunStatus.PARTIAL)
        raise TaskError(
            f"{exc}. La raccolta e' comunque riuscita: "
            f"{raccolta.persisted_new} annunci nuovi sono gia' in banca dati.",
            definitivo=True,
        ) from exc

    _segna_run(raccolta.status)
    return _riepilogo(raccolta, valutazione, settings.match_threshold)


def _riepilogo(raccolta: IngestReport, valutazione: MatchReport, soglia: int) -> dict[str, Any]:
    """Quello che finisce in ``task.result`` e che la dashboard mostra a fine run.

    Numeri, non frasi: la frase la compone la UI, che sa quanto spazio ha. Le
    fonti fallite si nominano tutte — una raccolta "parziale" senza dire *quale*
    fonte e' caduta manda a cercare la differenza confrontando due elenchi.
    """
    cadute = [o.slug for o in raccolta.outcomes if o.status is RunStatus.FAILED]
    return {
        "fonti": len(raccolta.outcomes),
        "fonti_fallite": cadute,
        "annunci_raccolti": raccolta.fetched,
        "annunci_nuovi": raccolta.persisted_new,
        "annunci_aggiornati": raccolta.persisted_updated,
        "chiamate_api": raccolta.api_calls,
        "esaminati": valutazione.examined,
        "valutati": len(valutazione.scored),
        "sopra_soglia": len(valutazione.above(soglia)),
        "soglia": soglia,
        "chiamate_llm": valutazione.llm_calls,
        "token": valutazione.input_tokens + valutazione.output_tokens,
        "non_valutati": len(valutazione.errors),
    }


def _primo_errore(raccolta: IngestReport) -> str:
    for esito in raccolta.outcomes:
        if esito.error:
            return esito.error
    return "nessuna fonte attiva"


def _segna_run(esito: RunStatus) -> None:
    """Scrive esito e ora dell'ultima run sul battito.

    Sta sulla riga del battito e non su ``run`` perche' risponde a una domanda
    diversa: ``run`` e' il registro per fonte, questa e' l'unica riga che la
    testata legge gia' per l'indicatore online. Una query in meno per la
    dashboard, che le fa a ogni caricamento.
    """
    with session_scope() as session:
        riga = session.get(WorkerHeartbeat, 1)
        if riga is None:
            riga = WorkerHeartbeat(id=1, last_seen_at=utcnow())
            session.add(riga)
        riga.last_run_at = utcnow()
        riga.last_run_status = esito
