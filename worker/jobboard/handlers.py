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

from sqlalchemy.orm import Session

from .db import session_scope
from .models import Application, ApplicationEvent, Job, Match, WorkerHeartbeat
from .models.base import utcnow
from .models.enums import (
    TIER_A_ATS,
    ApplicationEventType,
    ApplicationStatus,
    ApplicationTier,
    RunStatus,
    TaskType,
)
from .queue import Contesto, TaskError, handler
from .store import load_profile, save_profile
from .store.objects import download, upload

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


@handler(TaskType.GENERATE_CV)
def generate_cv(ctx: Contesto) -> dict[str, Any]:
    """Scrive il CV su misura per un annuncio e lo mette nel bucket (Fase 6).

    E' la meta' locale del bottone "Candidati": una chiamata LLM da decine di
    secondi, un browser che impagina e un PDF da caricare, cioe' tre cose che su
    una funzione serverless non stanno.

    **Il documento non parte se il validatore lo boccia.** Un CV con
    un'affermazione che il profilo non sostiene non e' un CV imperfetto: e' un
    CV che non si puo' spedire, e produrlo lo stesso vorrebbe dire rimettere a
    Filippo il lavoro di rileggerlo riga per riga contro l'originale.

    **Tre transazioni separate**, per la stessa ragione di ``run_pipeline``: fra
    la lettura e la scrittura ci sono minuti di chiamate LLM e di rendering, e
    tenere aperta una transazione per tutto quel tempo bloccherebbe le righe su
    Supabase e impedirebbe al battito di scriversi.
    """
    match_id = ctx.payload.get("match_id")
    if not isinstance(match_id, int):
        raise TaskError("payload senza match_id", definitivo=True)

    # Import ritardati: Jinja2, Playwright e il client LLM non devono pesare su
    # un worker che sta solo scrivendo il battito.
    from .ai.client import get_provider
    from .config import get_settings
    from .cv.generate import GenerationError, generate, storage_path_for

    settings = get_settings()

    ctx.avanza(5, "leggo annuncio e profilo")
    with session_scope() as session:
        match = session.get(Match, match_id)
        if match is None:
            raise TaskError(f"il match {match_id} non esiste", definitivo=True)
        job = session.get(Job, match.job_id)
        if job is None:  # pragma: no cover - la FK lo impedisce
            raise TaskError(f"il match {match_id} punta a un annuncio sparito", definitivo=True)

        salvato = load_profile(session)
        if salvato is None:
            raise TaskError("nessun profilo sul database: carica prima un CV", definitivo=True)
        if not salvato.reviewed:
            # Stesso guardrail del matching: un profilo non confermato genera un
            # CV che afferma cose mai rilette da nessuno.
            raise TaskError(
                "il profilo non e' stato confermato: aprilo nella pagina CV e premi Conferma",
                definitivo=True,
            )
        profilo = salvato.profile
        gaps = list(match.gaps or [])

    # Gli oggetti restano leggibili fuori dalla sessione: la factory e'
    # configurata con expire_on_commit=False proprio per questo.
    percorso_locale = settings.data_dir / "cv" / f"match-{match_id}.pdf"

    try:
        risultato = generate(
            get_provider(settings),
            profilo,
            job,
            percorso_locale,
            gaps=gaps,
            settings=settings,
            avanza=ctx.avanza,
        )
    except GenerationError as exc:
        # Definitivo: il tentativo successivo ripartirebbe dallo stesso profilo e
        # dallo stesso annuncio. Se il modello ha inventato tre volte di fila
        # sapendo cosa aveva sbagliato, a cambiare deve essere il profilo o il
        # prompt, non il numero di tentativi.
        raise TaskError(str(exc), definitivo=True) from exc

    ctx.avanza(85, "carico il PDF")
    percorso_remoto = storage_path_for(job.id, profilo)
    upload(percorso_remoto, risultato.pdf)

    ctx.avanza(95, "salvo")
    with session_scope() as session:
        candidatura = _application_per(session, match_id, job)
        candidatura.cv_storage_path = percorso_remoto[:512]
        candidatura.cv_payload = risultato.cv.model_dump()
        candidatura.cv_language = risultato.lingua[:5]
        candidatura.cv_fit_iterations = risultato.fit.compressioni
        candidatura.error = None
        if candidatura.status is ApplicationStatus.DRAFT:
            # Solo da DRAFT: se la candidatura era gia' approvata o inviata,
            # rigenerare il CV non deve riportarla indietro nel ciclo di vita.
            candidatura.status = ApplicationStatus.CV_READY
        session.flush()

        session.add(
            ApplicationEvent(
                application_id=candidatura.id,
                event_type=ApplicationEventType.CV_GENERATED,
                occurred_at=utcnow(),
                note=f"{risultato.pagine} pagina/e, {risultato.lingua}",
                payload={
                    "tentativi": risultato.tentativi,
                    "compressioni": risultato.fit.compressioni,
                    "densita_pt": risultato.fit.densita.punto,
                    "llm_calls": risultato.llm_calls,
                },
            )
        )

    log.info(
        "CV per il match %d: %d pagine, %d tentativi, %d chiamate",
        match_id,
        risultato.pagine,
        risultato.tentativi,
        risultato.llm_calls,
    )
    return {
        "match_id": match_id,
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "storage_path": percorso_remoto,
        "language": risultato.lingua,
        "pages": risultato.pagine,
        "attempts": risultato.tentativi,
        "compressions": risultato.fit.compressioni,
        "llm_calls": risultato.llm_calls,
        "tokens": risultato.input_tokens + risultato.output_tokens,
        "top_keywords": list(risultato.cv.top_keywords[:5]),
        # Detto qui perche' finisce in `task.result` e la dashboard lo mostra.
        "next": "Rivedi il CV nella pagina dell'annuncio, poi approvalo.",
    }


def _application_per(session: Session, match_id: int, job: Job) -> Application:
    """La candidatura di questo match, creata se non c'e'.

    Il vincolo di unicita' su ``match_id`` e' l'idempotenza della Fase 7: qui la
    si rispetta cercando prima e inserendo solo se serve, cosi' rigenerare un CV
    aggiorna la riga esistente invece di far fallire il task su una violazione
    di vincolo.
    """
    candidatura = session.query(Application).filter(Application.match_id == match_id).one_or_none()
    if candidatura is not None:
        return candidatura

    # ``status`` esplicito e non lasciato al ``default=`` del modello. In
    # SQLAlchemy quel default e' lato Python e lo applica il *flush*: fino ad
    # allora l'attributo vale ``None``, quindi il controllo "promuovi solo se
    # e' ancora DRAFT" che sta nel chiamante non scattava mai e ogni CV appena
    # generato restava `draft`. Effetto visibile: il bottone Approva della
    # dashboard non si accendeva.
    candidatura = Application(
        match_id=match_id,
        tier=_tier_provvisorio(job),
        status=ApplicationStatus.DRAFT,
    )
    session.add(candidatura)
    return candidatura


def _tier_provvisorio(job: Job) -> ApplicationTier:
    """Il tier con cui nasce la candidatura.

    Provvisorio di proposito: il router vero e' la Fase 7.1, che guarda anche se
    il form e' raggiungibile e se serve un login. Qui serve solo perche' la
    colonna e' NOT NULL, e la scelta piu' onesta a questo punto e' "automatico se
    l'ATS e' uno dei quattro che sappiamo gia' compilare, assistito altrimenti".
    """
    return ApplicationTier.A_AUTO if job.ats_type in TIER_A_ATS else ApplicationTier.B_ASSISTED
