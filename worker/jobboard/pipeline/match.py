"""Orchestrazione dell'imbuto a tre stadi e persistenza dei punteggi.

    Stadio 0  filtri duri, costo zero          ~150 -> ~60
    Stadio 1  coseno + BM25, costo zero         ~60 -> 40
    Stadio 2  rubrica LLM, una chiamata a testa  40 -> punteggio finale

Ogni stadio esiste per proteggere quello dopo. Senza lo Stadio 0 si spenderebbero
chiamate su annunci per cui non si è candidabili; senza lo Stadio 1 si
spenderebbero su annunci fuori tema. Con entrambi, la spesa quotidiana è una
quarantina di chiamate: un numero che sta dentro un free tier e che non cresce
se un giorno le fonti restituiscono il triplo degli annunci.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.client import LLMError, LLMProvider, get_provider
from ..ai.embeddings import Embedder, Vector, get_embedder
from ..ai.rubric import JobAssessment, assess, weighted_total
from ..config import Settings, get_settings
from ..models import Job, JobRequirements, JobSourceLink, Match, Source
from ..models.enums import MatchStatus
from ..schemas import MasterProfile
from . import filters
from .criteria import MatchCriteria, load_criteria
from .filters import FilterResult, Rejection
from .progress import Progress, avanza
from .rank import Ranked, ensure_embeddings, rank

log = logging.getLogger(__name__)

#: Pausa minima fra due chiamate allo Stadio 2. Il free tier di Gemini conta le
#: richieste al minuto: quaranta chiamate consecutive senza pausa si mangiano la
#: quota in venti secondi e le restanti tornano 429. Quattro secondi tengono il
#: ritmo sotto le 15 richieste al minuto e allungano la run di due minuti, che
#: per un processo notturno non è un costo.
MIN_SECONDS_BETWEEN_CALLS = 4.0


class MatchingError(RuntimeError):
    """Il matching non può partire: manca il profilo o non è stato rivisto."""


@dataclass
class Scored:
    """Un annuncio arrivato in fondo all'imbuto."""

    ranked: Ranked
    assessment: JobAssessment
    score: int
    model: str

    @property
    def job(self) -> Job:
        return self.ranked.job


@dataclass
class MatchReport:
    criteria: MatchCriteria
    filtered: FilterResult = field(default_factory=FilterResult)
    ranked: list[Ranked] = field(default_factory=list)
    scored: list[Scored] = field(default_factory=list)
    embedded: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: ``(job_id, messaggio)`` per gli annunci su cui lo Stadio 2 ha fallito. Non
    #: interrompono la run: gli altri trentanove annunci vengono valutati lo stesso.
    errors: list[tuple[int, str]] = field(default_factory=list)
    dry_run: bool = True
    persisted: int = 0
    #: Quanti finalisti sono davvero entrati allo Stadio 2 — merito piu' riserva. Non
    #: coincide sempre con ``stage2_top_n``: la riserva puo' trovare meno annunci a
    #: budget di quanti gliene chiederebbe, e in quel caso il totale e' piu' basso.
    stage2_entered: int = 0
    #: Id degli annunci valutati che **non avevano gia'** una riga ``match`` prima
    #: di questo salvataggio. La distingue da ``scored`` perche' il digest (Fase
    #: 8.3) deve segnalare un annuncio una volta sola: un ``--rescore`` che
    #: ripassa lo stesso annuncio dalla rubrica non deve generare una seconda
    #: notifica identica alla prima. Valorizzato da :func:`persist`, resta vuoto
    #: in dry-run perche' senza scrittura "nuovo" non ha risposta.
    new_job_ids: set[int] = field(default_factory=set)

    @property
    def examined(self) -> int:
        return self.filtered.examined

    def above(self, threshold: int) -> list[Scored]:
        """Gli annunci sopra soglia. La soglia è ``MATCH_THRESHOLD``, non una costante qui."""
        return [s for s in self.scored if s.score >= threshold]

    def top(self, n: int = 10) -> list[Scored]:
        return sorted(self.scored, key=lambda s: -s.score)[:n]


def run_matching(
    session: Session,
    *,
    rescore: bool = False,
    limit: int | None = None,
    top_n: int | None = None,
    use_llm: bool = True,
    dry_run: bool = True,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    embedder: Embedder | None = None,
    progress: Progress | None = None,
) -> MatchReport:
    """Esegue l'imbuto completo e salva i risultati."""
    settings = settings or get_settings()
    profilo, vettore = _load_reviewed_profile(session, embedder, settings)
    criteri = load_criteria(session, profile=profilo)
    report = MatchReport(criteria=criteri, dry_run=dry_run)

    for avviso in criteri.inactive:
        log.warning("filtro inattivo — %s", avviso)

    avanza(progress, 5, "filtri")
    candidati = filters.candidates(session, rescore=rescore, limit=limit)
    report.filtered = filters.apply_filters(candidati, criteri)
    log.info(
        "stadio 0: %d esaminati, %d passati, scarti %s",
        report.examined,
        len(report.filtered.passed),
        dict(report.filtered.counts),
    )

    if report.filtered.passed:
        avanza(progress, 20, "embedding")
        embedder = embedder or get_embedder()
        report.embedded = ensure_embeddings(session, report.filtered.passed, embedder)

        avanza(progress, 35, "stadio 1")
        report.ranked = rank(report.filtered.passed, profilo, vettore)

    quanti = top_n if top_n is not None else criteri.stage2_top_n
    budget_ids = _budgeted_source_job_ids(session, [r.job.id for r in report.ranked])
    finalisti = select_finalists(report.ranked, quanti, criteri.stage2_reserved_floor, budget_ids)
    report.stage2_entered = len(finalisti)

    if use_llm and finalisti:
        _run_stage2(report, finalisti, profilo, settings, provider, progress)

    avanza(progress, 90, "salvataggio")
    if not dry_run:
        report.persisted = persist(session, report)

    avanza(progress, 100, "fatto")
    return report


def select_finalists(
    ranked: Sequence[Ranked], quanti: int, reserved_n: int, budget_ids: set[int]
) -> list[Ranked]:
    """I finalisti per lo Stadio 2: merito puro, piu' una riserva per chi ha un tetto.

    Senza riserva un annuncio JSearch/LinkedIn deve superare per punteggio ibrido
    *l'intero arretrato* non ancora valutato — che le sette fonti senza budget
    riempiono molto piu' in fretta di quanto JSearch, a sei chiamate al giorno,
    riesca a competere. Il risultato osservato e' che quasi non ne passa mai
    nessuno, indipendentemente da quanto siano buoni i suoi annunci.

    La riserva viene **tolta** dal tetto giornaliero, non aggiunta sopra: il costo di
    una run resta prevedibile — sempre al piu' ``quanti`` chiamate LLM, mai di piu'.
    Se in coda ci sono meno annunci a budget di quanti la riserva ne chiederebbe, si
    prende quel che c'e': non si inventano posti per arrivare al numero.

    Un annuncio a budget che vince gia' un posto per merito non consuma la riserva —
    la riserva serve solo a chi altrimenti resterebbe fuori.
    """
    if reserved_n <= 0 or not budget_ids:
        return list(ranked[:quanti])

    merito = list(ranked[: max(quanti - reserved_n, 0)])
    scelti = {r.job.id for r in merito}

    riserva: list[Ranked] = []
    for r in ranked:
        if len(riserva) >= reserved_n:
            break
        if r.job.id in scelti or r.job.id not in budget_ids:
            continue
        riserva.append(r)

    return merito + riserva


def _budgeted_source_job_ids(session: Session, job_ids: Sequence[int]) -> set[int]:
    """Gli id degli annunci arrivati (anche) da una fonte con un tetto di chiamate.

    Il criterio e' "ha un ``daily_call_budget``", non il nome dell'adapter: quando
    arrivera' una seconda fonte a consumo la riserva la copre da sola, senza
    toccare :func:`select_finalists`. Un annuncio arrivato anche da una fonte senza
    tetto conta comunque, perche' la domanda e' "esiste un modo di raccoglierlo che
    costa un budget", non "arriva *solo* da li'".
    """
    if not job_ids:
        return set()
    righe = session.execute(
        select(JobSourceLink.job_id)
        .join(Source, Source.id == JobSourceLink.source_id)
        .where(JobSourceLink.job_id.in_(job_ids), Source.daily_call_budget.is_not(None))
    ).scalars()
    return set(righe)


def _run_stage2(
    report: MatchReport,
    finalisti: Sequence[Ranked],
    profilo: MasterProfile,
    settings: Settings,
    provider: LLMProvider | None,
    progress: Progress | None,
) -> None:
    provider = provider or get_provider(settings)
    modello = settings.model_scoring
    ultima = 0.0

    for indice, candidato in enumerate(finalisti, start=1):
        attesa = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - ultima)
        if ultima and attesa > 0:
            time.sleep(attesa)
        ultima = time.monotonic()

        avanza(
            progress,
            35 + int(55 * indice / len(finalisti)),
            f"stadio 2: {indice}/{len(finalisti)}",
        )
        try:
            risultato = assess(provider, profilo, candidato.job, model=modello)
        except LLMError as exc:
            # Un annuncio che il modello non digerisce non deve costare gli altri
            # trentanove: si registra e si va avanti.
            log.warning("job %s non valutato: %s", candidato.job.id, exc)
            report.errors.append((candidato.job.id, f"{type(exc).__name__}: {exc}"))
            continue

        valutazione = risultato.value
        report.llm_calls += 1
        report.input_tokens += risultato.usage.input_tokens
        report.output_tokens += risultato.usage.output_tokens
        report.scored.append(
            Scored(
                ranked=candidato,
                assessment=valutazione,
                score=weighted_total(valutazione.subscores()),
                model=risultato.usage.model,
            )
        )


def _load_reviewed_profile(
    session: Session, embedder: Embedder | None, settings: Settings
) -> tuple[MasterProfile, Vector]:
    """Il profilo e il suo vettore, con i controlli che rendono sensato il resto.

    Il flag ``reviewed`` non è burocrazia: un profilo estratto male produce
    punteggi sbagliati su ogni annuncio, tutti i giorni, e nessuno se ne accorge
    perché i numeri sembrano numeri. Meglio un comando che si rifiuta di partire.
    """
    from ..store import load_profile

    stored = load_profile(session)
    if stored is None:
        raise MatchingError(
            "nessun profilo sul database. Esegui prima: jobboard profile import <cv.pdf>"
        )
    if not stored.reviewed:
        raise MatchingError(
            # Il messaggio si legge anche in dashboard, da quando la run si può
            # chiedere con un bottone (Fase 5.4): la prima via indicata è quella
            # che si può seguire dal telefono, dov'è arrivato l'errore.
            "il profilo non è stato confermato: rileggilo nella pagina CV e premi "
            "Conferma, oppure correggi data/cv/master_profile.json ed esegui "
            "jobboard profile load"
        )

    if stored.embedding_is_current(settings.embedding_model):
        assert stored.embedding is not None  # garantito da embedding_is_current
        return stored.profile, stored.embedding

    log.info("embedding del profilo assente o di un altro modello: lo ricalcolo")
    embedder = embedder or get_embedder()
    vettore = embedder.embed_profile(stored.profile.to_embedding_text())

    from ..store import save_profile

    save_profile(
        session,
        profile=stored.profile,
        embedding=vettore,
        embedding_model=embedder.model_name,
        reviewed=stored.reviewed,
    )
    return stored.profile, vettore


# --- persistenza --------------------------------------------------------------


def persist(session: Session, report: MatchReport) -> int:
    """Scrive i ``match``, un annuncio per riga. Ritorna quante righe ha toccato."""
    esistenti = _existing_matches(session, report)
    # Va letto **prima** dei tre cicli sotto: scrivono dentro lo stesso dizionario
    # via `_row`, quindi da quel momento in poi non distingue piu' una riga
    # che c'era gia' da una appena creata in questa stessa run.
    report.new_job_ids = _new_scored_ids(report.scored, set(esistenti))
    adesso = dt.datetime.now(dt.UTC)
    toccate = 0

    for scarto in report.filtered.rejected:
        _write_rejection(session, esistenti, scarto)
        toccate += 1

    valutati = {s.job.id for s in report.scored}
    for candidato in report.ranked:
        if candidato.job.id in valutati:
            continue
        _write_stage1(session, esistenti, candidato)
        toccate += 1

    for valutato in report.scored:
        _write_stage2(session, esistenti, valutato, adesso)
        toccate += 1

    session.flush()
    return toccate


def _new_scored_ids(scored: Sequence[Scored], pre_existing_ids: set[int]) -> set[int]:
    """Quali valutati non avevano gia' una riga ``match``. Pura, per essere testabile senza DB."""
    return {s.job.id for s in scored if s.job.id not in pre_existing_ids}


def _existing_matches(session: Session, report: MatchReport) -> dict[int, Match]:
    ids = {r.job.id for r in report.filtered.rejected} | {r.job.id for r in report.ranked}
    if not ids:
        return {}
    righe = session.execute(select(Match).where(Match.job_id.in_(ids))).scalars()
    return {riga.job_id: riga for riga in righe}


def _row(session: Session, esistenti: dict[int, Match], job_id: int) -> Match:
    """La riga di questo annuncio, creandola se non c'è.

    ``reached_stage`` e ``gaps`` vengono valorizzati a mano benché la colonna
    dichiari un ``default``: quel default lo applica Postgres al momento della
    INSERT, non il costruttore Python. Fino al flush valgono ``None``, e
    ``max(None, 1)`` è un ``TypeError`` a metà di una run che ha appena speso
    quaranta chiamate LLM.
    """
    riga = esistenti.get(job_id)
    if riga is None:
        riga = Match(job_id=job_id, status=MatchStatus.NEW, reached_stage=0, gaps=[])
        session.add(riga)
        esistenti[job_id] = riga
    return riga


def _write_rejection(session: Session, esistenti: dict[int, Match], scarto: Rejection) -> None:
    """Registra lo scarto **senza cancellare un punteggio già dato**.

    Le due informazioni rispondono a domande diverse: ``reached_stage`` dice dove
    è arrivato l'annuncio in *questa* run, ``score`` qual è stato l'ultimo
    giudizio. La dashboard mostra ciò che ha ``reached_stage >= 1``, quindi un
    annuncio che oggi non supera un filtro duro sparisce dalla tabella pur
    conservando la sua storia per la calibrazione.
    """
    riga = _row(session, esistenti, scarto.job.id)
    riga.reached_stage = 0
    riga.filtered_reason = scarto.reason


def _write_stage1(session: Session, esistenti: dict[int, Match], candidato: Ranked) -> None:
    riga = _row(session, esistenti, candidato.job.id)
    riga.semantic_score = candidato.semantic
    riga.keyword_score = candidato.keyword
    riga.hybrid_score = candidato.hybrid
    riga.reached_stage = max(riga.reached_stage, 1)
    riga.filtered_reason = None


def _write_stage2(
    session: Session, esistenti: dict[int, Match], valutato: Scored, adesso: dt.datetime
) -> None:
    riga = _row(session, esistenti, valutato.job.id)
    riga.semantic_score = valutato.ranked.semantic
    riga.keyword_score = valutato.ranked.keyword
    riga.hybrid_score = valutato.ranked.hybrid

    riga.score = valutato.score
    riga.subscores = valutato.assessment.subscores()
    riga.rationale = valutato.assessment.rationale
    riga.gaps = list(valutato.assessment.gaps)
    riga.scored_with = valutato.model
    riga.scored_at = adesso
    riga.reached_stage = 2
    riga.filtered_reason = None

    _write_requirements(session, valutato, adesso)


def _write_requirements(session: Session, valutato: Scored, adesso: dt.datetime) -> None:
    """Salva i requisiti estratti, sovrascrivendo quelli della valutazione precedente."""
    campi = valutato.assessment.requirement_fields()
    # Ricerca per ``job_id``, non ``session.get``: la chiave primaria della
    # tabella è ``id``, e passarle un job_id restituirebbe allegramente i
    # requisiti di un altro annuncio.
    riga = session.execute(
        select(JobRequirements).where(JobRequirements.job_id == valutato.job.id)
    ).scalar_one_or_none()

    if riga is None:
        riga = JobRequirements(
            job_id=valutato.job.id, extracted_with=valutato.model, extracted_at=adesso
        )
        session.add(riga)

    for nome, valore in campi.items():
        setattr(riga, nome, valore)
    riga.extracted_with = valutato.model
    riga.extracted_at = adesso
