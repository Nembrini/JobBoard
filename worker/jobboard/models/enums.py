"""Enum del dominio.

Sono persistiti come VARCHAR + CHECK constraint (``native_enum=False``) e non come
tipi ENUM nativi di Postgres: aggiungere un valore a un ENUM nativo richiede un
``ALTER TYPE`` che Alembic non sa autogenerare, e questi elenchi cresceranno.
"""

from __future__ import annotations

from enum import StrEnum


class WorkMode(StrEnum):
    ON_SITE = "on_site"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class ContractType(StrEnum):
    PERMANENT = "permanent"  # indeterminato
    FIXED_TERM = "fixed_term"  # determinato
    CONTRACT = "contract"  # freelance / P.IVA
    INTERNSHIP = "internship"  # stage / tirocinio
    APPRENTICESHIP = "apprenticeship"  # apprendistato
    PART_TIME = "part_time"
    UNKNOWN = "unknown"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        """Posizione ordinale, per confronti "entro +/-1 livello"."""
        return _SENIORITY_RANK[self]


_SENIORITY_RANK: dict[Seniority, int] = {
    Seniority.INTERN: 0,
    Seniority.JUNIOR: 1,
    Seniority.MID: 2,
    Seniority.SENIOR: 3,
    Seniority.LEAD: 4,
    Seniority.PRINCIPAL: 5,
    Seniority.UNKNOWN: -1,
}


class SalaryPeriod(StrEnum):
    """Periodo dichiarato nell'annuncio, prima della normalizzazione a RAL annua."""

    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class AtsType(StrEnum):
    """Applicant Tracking System che ospita il form di candidatura.

    I primi quattro abilitano il Tier A: selettori dedicati invece
    dell'euristica generica del Tier B. **Non un invio via API**, come diceva
    il piano originale — la Fase 7 l'ha scoperto non praticabile a esecuzione
    (vedi ARCHITECTURE.md, decisione "Tier A senza API diretta"): Greenhouse
    protegge il form pubblico con reCAPTCHA Enterprise, e Lever/Workable
    richiedono una chiave API che solo il datore di lavoro puo' generare.
    """

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKABLE = "workable"
    RECRUITEE = "recruitee"
    SMARTRECRUITERS = "smartrecruiters"
    WORKDAY = "workday"
    TALEO = "taleo"
    OTHER = "other"
    UNKNOWN = "unknown"


#: ATS su cui il worker sa inviare la candidatura senza intervento umano.
TIER_A_ATS: frozenset[AtsType] = frozenset(
    {AtsType.GREENHOUSE, AtsType.LEVER, AtsType.ASHBY, AtsType.WORKABLE}
)


class MatchStatus(StrEnum):
    NEW = "new"
    SEEN = "seen"
    SHORTLIST = "shortlist"
    HIDDEN = "hidden"
    APPLIED = "applied"


class ApplicationTier(StrEnum):
    #: ATS noto (Greenhouse/Lever/Ashby/Workable): Playwright headful con
    #: selettori dedicati per quella piattaforma. **Si ferma comunque prima del
    #: submit** — vedi la nota su ``TIER_A_ATS`` per il motivo del cambio rispetto
    #: al piano originale ("POST diretto all'API").
    A_AUTO = "a_auto"
    #: ATS sconosciuto ma con un ``apply_url`` diretto: stesso Playwright
    #: headful, precompilazione euristica su label e attributi invece di
    #: selettori dedicati. Ferma prima del submit.
    B_ASSISTED = "b_assisted"
    C_MANUAL = "c_manual"  # nessun apply_url diretto: solo apertura dell'URL


class ApplicationStatus(StrEnum):
    DRAFT = "draft"  # CV non ancora generato
    CV_READY = "cv_ready"  # CV generato, in attesa di approvazione
    APPROVED = "approved"  # approvato, in coda per l'invio
    #: Form precompilato e aperto nel browser sul PC (Tier A o B), oppure solo
    #: il link pronto da aprire (Tier C): serve il tuo click per spedirla
    #: davvero. Nessun tier la supera da solo — vedi ``apply/router.py``.
    NEEDS_HUMAN = "needs_human"
    #: Segnata a mano dalla dashboard dopo che l'hai spedita tu nel browser.
    #: Nessun codice del worker scrive questo stato da solo.
    SUBMITTED = "submitted"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"
    # --- esiti post-candidatura ---
    ACKNOWLEDGED = "acknowledged"  # conferma automatica ricevuta
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"


#: Stati che chiudono il ciclo di vita: non generano piu' promemoria di follow-up.
TERMINAL_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.REJECTED,
        ApplicationStatus.OFFER,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.FAILED,
    }
)


class ApplicationEventType(StrEnum):
    CREATED = "created"
    CV_GENERATED = "cv_generated"
    APPROVED = "approved"
    #: Il worker ha aperto il form (o l'URL, per il Tier C) e si e' fermato
    #: prima del submit: e' il momento in cui la candidatura passa a
    #: ``NEEDS_HUMAN``.
    PREPARED = "prepared"
    #: Il tentativo di preparare il form e' fallito (pagina non raggiungibile,
    #: campi non trovati). Non e' un ``submit_failed``: non si e' nemmeno
    #: arrivati a un form da compilare.
    PREPARE_FAILED = "prepare_failed"
    SUBMITTED = "submitted"
    SUBMIT_FAILED = "submit_failed"
    EMAIL_RECEIVED = "email_received"
    STATUS_CHANGED = "status_changed"
    FOLLOW_UP_DUE = "follow_up_due"


class EmailClass(StrEnum):
    """Classificazione LLM delle risposte dei recruiter."""

    INTERVIEW = "interview"
    REJECTION = "rejection"
    ACK = "ack"
    REQUEST_INFO = "request_info"
    OTHER = "other"


class TaskType(StrEnum):
    RUN_PIPELINE = "run_pipeline"
    GENERATE_CV = "generate_cv"
    APPLY = "apply"
    REPARSE_PROFILE = "reparse_profile"
    CHECK_EMAIL = "check_email"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"  # alcune fonti hanno fallito
    FAILED = "failed"
