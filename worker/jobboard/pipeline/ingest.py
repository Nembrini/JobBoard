"""Orchestrazione della raccolta: dalle fonti al database.

Il flusso è: interroga le fonti attive, normalizza, raggruppa i duplicati,
scrivi. Ogni fonte è isolata — se Adzuna va giù, le altre otto finiscono
comunque il loro lavoro e la riga ``run`` dice quale ha fallito e perché. Una
run che fallisce del tutto perché una API di terzi ha singhiozzato sarebbe
inutilizzabile come processo notturno.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Job, JobSourceLink, Run, Setting, Source
from ..models.base import utcnow
from ..models.enums import AtsType, ContractType, RunStatus, Seniority, WorkMode
from ..schemas import MasterProfile
from ..sources import SearchQuery, SourceError, all_adapter_classes, get_adapter_class
from . import dedup
from .dedup import JobGroup
from .normalize import NormalizedJob, job_family, normalize
from .progress import Progress, avanza, fascia
from .text import to_signed_64

log = logging.getLogger(__name__)

#: Chiave della riga ``settings`` che contiene i parametri di ricerca.
SEARCH_SETTING_KEY = "search"

#: Usati solo se non c'è né una configurazione salvata né un profilo da cui
#: dedurli: il sistema deve poter girare anche prima della Fase 1.
FALLBACK_KEYWORDS = ("software developer", "backend developer")
FALLBACK_COUNTRIES = ("it", "de", "nl", "es")


@dataclass
class SourceOutcome:
    """Com'è andata una singola fonte."""

    slug: str
    status: RunStatus
    fetched: int = 0
    new: int = 0
    duplicate: int = 0
    api_calls: int = 0
    elapsed: float = 0.0
    error: str | None = None


@dataclass
class IngestReport:
    batch_id: str
    query: SearchQuery
    outcomes: list[SourceOutcome] = field(default_factory=list)
    groups: list[JobGroup] = field(default_factory=list)
    persisted_new: int = 0
    persisted_updated: int = 0
    dry_run: bool = True

    @property
    def status(self) -> RunStatus:
        falliti = [o for o in self.outcomes if o.status is RunStatus.FAILED]
        if not falliti:
            return RunStatus.OK
        return RunStatus.FAILED if len(falliti) == len(self.outcomes) else RunStatus.PARTIAL

    @property
    def fetched(self) -> int:
        return sum(o.fetched for o in self.outcomes)

    @property
    def api_calls(self) -> int:
        return sum(o.api_calls for o in self.outcomes)


# --- registrazione delle fonti ------------------------------------------------


def sync_sources(session: Session) -> list[Source]:
    """Allinea la tabella ``source`` agli adapter registrati nel codice.

    Le righe esistenti non vengono toccate: contengono le board seguite e il
    flag ``enabled``, che sono scelte dell'utente. Qui si aggiungono soltanto
    gli adapter nuovi.
    """
    esistenti = {s.adapter: s for s in session.scalars(select(Source))}
    for slug, cls in sorted(all_adapter_classes().items()):
        if slug in esistenti:
            continue
        riga = Source(
            adapter=slug,
            display_name=cls.display_name,
            # Una fonte senza le sue chiavi resta spenta: accenderla produrrebbe
            # solo un errore a ogni run.
            enabled=not cls.required_settings,
            config={},
            rate_limit_per_min=cls.default_rate_limit_per_min,
            daily_call_budget=cls.default_daily_budget,
        )
        session.add(riga)
        esistenti[slug] = riga
        log.info("registrata la fonte %s", slug)

    session.flush()
    return sorted(esistenti.values(), key=lambda s: s.adapter)


# --- parametri di ricerca -----------------------------------------------------


def build_query(
    session: Session,
    *,
    keywords: Sequence[str] | None = None,
    countries: Sequence[str] | None = None,
    limit: int | None = None,
) -> SearchQuery:
    """Compone la ricerca: argomenti espliciti, poi impostazioni, poi profilo."""
    salvate = session.get(Setting, SEARCH_SETTING_KEY)
    valori: dict[str, object] = dict(salvate.value) if salvate else {}

    if not valori:
        valori = _seed_from_profile(session)
        session.add(
            Setting(
                key=SEARCH_SETTING_KEY,
                value=valori,
                description="Parametri della ricerca giornaliera, modificabili dalla dashboard",
            )
        )
        session.flush()
        log.info("parametri di ricerca inizializzati dal profilo: %s", valori)

    return SearchQuery(
        keywords=tuple(keywords)
        if keywords
        else _as_words(valori.get("keywords"), FALLBACK_KEYWORDS),
        countries=tuple(countries)
        if countries
        else _as_words(valori.get("countries"), FALLBACK_COUNTRIES),
        max_results_per_keyword=limit or _as_int(valori.get("max_results_per_keyword"), 50),
        posted_within_days=_as_int(valori.get("posted_within_days"), 21),
        remote_only=bool(valori.get("remote_only") or False),
    )


def _as_words(value: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Il valore arriva da una colonna JSONB: puo' essere qualunque cosa."""
    if isinstance(value, list | tuple) and value:
        return tuple(str(v) for v in value)
    return fallback


def _as_int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return fallback


def _seed_from_profile(session: Session) -> dict[str, object]:
    """Ricava i termini di ricerca dal CV, che è l'unica fonte di verità su cosa cercare."""
    from ..store import load_profile

    stored = load_profile(session)
    keywords = _keywords_from_profile(stored.profile) if stored else ()
    return {
        "keywords": list(keywords or FALLBACK_KEYWORDS),
        "countries": list(FALLBACK_COUNTRIES),
        "max_results_per_keyword": 50,
        "posted_within_days": 21,
        "remote_only": False,
    }


#: Equivalente italiano dei ruoli tecnici. Serve perché un annuncio milanese si
#: intitola "Sviluppatore Backend", non "Backend Developer": cercando solo in
#: inglese metà del mercato italiano — quello principale — resta invisibile.
_SYNONYMS_IT = {
    "software developer": "sviluppatore software",
    "backend developer": "sviluppatore backend",
    "frontend developer": "sviluppatore frontend",
    "fullstack developer": "sviluppatore full stack",
    "mobile developer": "sviluppatore mobile",
    "data engineer": "ingegnere dei dati",
}

#: Oltre questo numero le fonti a budget (JSearch, ~6 chiamate al giorno) si
#: esauriscono prima di aver coperto tutti i mercati.
_MAX_KEYWORDS = 6


def _keywords_from_profile(profile: MasterProfile) -> tuple[str, ...]:
    """Headline e famiglie dei ruoli svolti, che è ciò per cui si è candidabili."""
    inglesi: list[str] = []
    if profile.headline:
        inglesi.append(profile.headline.lower())
    for esperienza in profile.experiences:
        if famiglia := job_family(esperienza.role):
            inglesi.append(famiglia.lower())

    # I termini inglesi vengono prima: sono quelli che le fonti a budget
    # consumeranno per primi, e coprono i mercati non italiani.
    ordinati = list(dict.fromkeys(inglesi))
    italiani = [_SYNONYMS_IT[t] for t in ordinati if t in _SYNONYMS_IT]
    return tuple(dict.fromkeys([*ordinati, *italiani]))[:_MAX_KEYWORDS]


# --- raccolta -----------------------------------------------------------------


def collect(
    sources: Sequence[Source],
    query: SearchQuery,
    settings: Settings | None = None,
    progress: Progress | None = None,
) -> tuple[list[NormalizedJob], list[SourceOutcome]]:
    """Interroga le fonti indicate. Nessuna scrittura sul database."""
    settings = settings or get_settings()
    raccolti: list[NormalizedJob] = []
    esiti: list[SourceOutcome] = []

    for indice, source in enumerate(sources, start=1):
        # L'avanzamento si annuncia *prima* di interrogare la fonte, non dopo:
        # quello che serve sapere guardando la dashboard e' su chi si e' fermi,
        # e una fonte che non risponde tiene il turno per tutto il timeout.
        avanza(
            progress,
            round(100 * (indice - 1) / len(sources)),
            f"{source.adapter} ({indice}/{len(sources)})",
        )
        inizio = time.perf_counter()
        esito = SourceOutcome(slug=source.adapter, status=RunStatus.OK)
        try:
            adapter = get_adapter_class(source.adapter)(
                settings, source.config, rate_limit_per_min=source.rate_limit_per_min
            )
            if missing := adapter.missing_settings():
                raise SourceError(f"configurazione incompleta: manca {', '.join(missing)}")

            with adapter.new_client() as http:
                for grezzo in adapter.fetch(query, http):
                    raccolti.append(normalize(grezzo))
                    esito.fetched += 1
                esito.api_calls = http.calls
        except Exception as exc:
            esito.status = RunStatus.FAILED
            esito.error = f"{type(exc).__name__}: {exc}"
            log.warning("fonte %s fallita: %s", source.adapter, esito.error)

        esito.elapsed = time.perf_counter() - inizio
        esiti.append(esito)
        log.info(
            "%s: %d annunci in %.1fs (%d chiamate)",
            source.adapter,
            esito.fetched,
            esito.elapsed,
            esito.api_calls,
        )

    return raccolti, esiti


# --- persistenza --------------------------------------------------------------


def persist(
    session: Session, groups: Sequence[JobGroup], sources: Sequence[Source]
) -> tuple[int, int]:
    """Scrive i gruppi sul database. Ritorna (nuovi, aggiornati)."""
    per_slug = {s.adapter: s for s in sources}
    adesso = utcnow()
    nuovi = aggiornati = 0

    for gruppo in groups:
        esistente = _find_existing(session, gruppo.canonical)
        if esistente is None:
            job = _insert(session, gruppo.canonical, adesso)
            nuovi += 1
        else:
            job = _refresh(esistente, gruppo.canonical, adesso)
            aggiornati += 1

        session.flush()  # serve job.id per i link
        for variante in gruppo.variants:
            if (source := per_slug.get(variante.source)) is not None:
                _upsert_link(session, job, source, variante, adesso)

    session.flush()
    return nuovi, aggiornati


def _find_existing(session: Session, job: NormalizedJob) -> Job | None:
    """Cerca l'annuncio già presente: prima per chiave, poi per contenuto."""
    per_chiave = session.scalars(
        select(Job).where(Job.canonical_key == job.canonical_key).limit(1)
    ).first()
    if per_chiave is not None:
        return per_chiave

    # Stessa azienda, titolo diverso: il confronto è sul SimHash. La ricerca è
    # ristretta all'azienda perché due annunci di aziende diverse con testo
    # simile sono due annunci, non uno.
    if len(job.description_clean) < dedup._MIN_CHARS_FOR_SIMHASH:
        return None
    candidati = session.scalars(
        select(Job)
        .where(Job.company_normalized == job.company_normalized, Job.is_active.is_(True))
        .limit(300)
    ).all()
    for candidato in candidati:
        if candidato.simhash is None:
            continue
        from .text import from_signed_64, hamming

        if hamming(from_signed_64(candidato.simhash), job.simhash) <= dedup.MAX_HAMMING_DISTANCE:
            return candidato
    return None


def _insert(session: Session, job: NormalizedJob, now: dt.datetime) -> Job:
    riga = Job(
        title=job.title,
        company=job.company,
        company_normalized=job.company_normalized,
        canonical_key=job.canonical_key,
        simhash=to_signed_64(job.simhash),
        content_hash=job.content_hash,
        location_raw=job.location_raw,
        city=job.city,
        region=job.region,
        country=job.country,
        work_mode=job.work_mode,
        salary_is_stated=job.salary.is_stated,
        salary_min=job.salary.min,
        salary_max=job.salary.max,
        salary_currency=job.salary.currency,
        salary_period=job.salary.period,
        salary_eur_year_min=job.salary.eur_year_min,
        salary_eur_year_max=job.salary.eur_year_max,
        contract_type=job.contract_type,
        seniority=job.seniority,
        job_family=job.job_family,
        description_raw=job.description_raw,
        description_clean=job.description_clean,
        lang=job.lang,
        url=job.url,
        apply_url=job.apply_url,
        ats_type=job.ats_type,
        ats_board_token=job.ats_board_token,
        ats_job_id=job.ats_job_id,
        posted_at=job.posted_at,
        first_seen_at=now,
        last_seen_at=now,
        is_active=True,
    )
    session.add(riga)
    return riga


def _refresh(existing: Job, job: NormalizedJob, now: dt.datetime) -> Job:
    """Aggiorna un annuncio già noto senza perdere quello che si sa già.

    Si sovrascrive solo dove la versione nuova è **migliore**: una descrizione
    più lunga, un link ATS dove prima c'era un aggregatore, una RAL dove prima
    non c'era. Il contrario — un aggregatore povero che sovrascrive i dati buoni
    di una board ATS il giorno dopo — degraderebbe il database a ogni run.
    """
    existing.last_seen_at = now
    existing.is_active = True

    if len(job.description_clean) > len(existing.description_clean or ""):
        existing.description_raw = job.description_raw
        existing.description_clean = job.description_clean
        existing.content_hash = job.content_hash
        existing.simhash = to_signed_64(job.simhash)
        existing.lang = job.lang

    if job.salary.is_stated and not existing.salary_is_stated:
        existing.salary_is_stated = True
        existing.salary_min = job.salary.min
        existing.salary_max = job.salary.max
        existing.salary_currency = job.salary.currency
        existing.salary_period = job.salary.period
        existing.salary_eur_year_min = job.salary.eur_year_min
        existing.salary_eur_year_max = job.salary.eur_year_max

    if job.ats_type is not AtsType.UNKNOWN and existing.ats_type is AtsType.UNKNOWN:
        existing.ats_type = job.ats_type
        existing.ats_board_token = job.ats_board_token
        existing.ats_job_id = job.ats_job_id
        existing.apply_url = job.apply_url or existing.apply_url
        existing.url = job.url

    if job.posted_at and (existing.posted_at is None or job.posted_at < existing.posted_at):
        existing.posted_at = job.posted_at
    if job.city and not existing.city:
        existing.city = job.city
    if job.country and not existing.country:
        existing.country = job.country

    _refresh_classification(existing, job)
    return existing


def _refresh_classification(existing: Job, job: NormalizedJob) -> None:
    """Riporta le classificazioni a quello che dice il codice di oggi.

    Le regole di ``normalize`` cambiano — una famiglia aggiunta, un pattern
    corretto — e senza questo passaggio gli annunci gia' in tabella resterebbero
    classificati con le regole del giorno in cui sono stati visti la prima volta,
    finche' non scadono. E' successo davvero: dopo aver insegnato al classificatore
    i nomi composti tedeschi, ventidue annunci continuavano a non avere famiglia.

    Si sovrascrive solo con un valore **informativo**: un ``UNKNOWN`` di oggi non
    deve cancellare una modalita' di lavoro riconosciuta ieri.
    """
    if job.job_family:
        existing.job_family = job.job_family
    if job.work_mode is not WorkMode.UNKNOWN:
        existing.work_mode = job.work_mode
    if job.seniority is not Seniority.UNKNOWN:
        existing.seniority = job.seniority
    if job.contract_type is not ContractType.UNKNOWN:
        existing.contract_type = job.contract_type
    if job.title:
        existing.title = job.title


def _upsert_link(
    session: Session, job: Job, source: Source, variant: NormalizedJob, now: dt.datetime
) -> None:
    link = session.scalars(
        select(JobSourceLink)
        .where(
            JobSourceLink.source_id == source.id,
            JobSourceLink.external_id == variant.external_id,
        )
        .limit(1)
    ).first()

    if link is None:
        session.add(
            JobSourceLink(
                job_id=job.id,
                source_id=source.id,
                external_id=variant.external_id,
                url=variant.url,
                fetched_at=now,
                publisher=variant.publisher,
                raw=variant.raw or None,
            )
        )
        return

    link.fetched_at = now
    link.url = variant.url
    link.publisher = variant.publisher or link.publisher
    link.raw = variant.raw or link.raw
    # Lo stesso external_id puntava a un altro Job: succede quando la dedup
    # unisce due annunci che prima erano separati.
    link.job_id = job.id


# --- pipeline completa --------------------------------------------------------


def ingest(
    session: Session,
    *,
    only: Sequence[str] | None = None,
    keywords: Sequence[str] | None = None,
    countries: Sequence[str] | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    progress: Progress | None = None,
) -> IngestReport:
    """Raccolta completa: fonti -> normalizzazione -> dedup -> database."""
    sources = sync_sources(session)
    attive = [s for s in sources if s.enabled and (not only or s.adapter in set(only))]
    if only:
        sconosciute = set(only) - {s.adapter for s in sources}
        if sconosciute:
            raise SourceError(f"fonti sconosciute: {', '.join(sorted(sconosciute))}")

    query = build_query(session, keywords=keywords, countries=countries, limit=limit)
    report = IngestReport(batch_id=str(uuid.uuid4()), query=query, dry_run=dry_run)

    raccolti, report.outcomes = collect(
        attive, query, get_settings(), progress=fascia(progress, 0, 85)
    )
    avanza(progress, 90, "unisco i duplicati")
    report.groups = dedup.group(raccolti)

    duplicati = len(raccolti) - len(report.groups)
    for esito in report.outcomes:
        # Il conteggio dei duplicati è di lotto, non di fonte: un annuncio è
        # duplicato *rispetto a un altro*, e attribuirlo a una delle due fonti
        # sarebbe arbitrario. Si distribuisce in proporzione a quanto raccolto.
        esito.duplicate = round(duplicati * esito.fetched / len(raccolti)) if raccolti else 0

    if not dry_run:
        report.persisted_new, report.persisted_updated = persist(session, report.groups, sources)
        _write_run_rows(session, report, attive)
        for source in attive:
            ultimo = next((o for o in report.outcomes if o.slug == source.adapter), None)
            if ultimo is not None:
                source.last_run_at = utcnow()
                source.last_error = ultimo.error

    return report


def _write_run_rows(session: Session, report: IngestReport, sources: Sequence[Source]) -> None:
    per_slug = {s.adapter: s for s in sources}
    fine = utcnow()
    for esito in report.outcomes:
        source = per_slug.get(esito.slug)
        session.add(
            Run(
                batch_id=report.batch_id,
                source_id=source.id if source else None,
                status=esito.status,
                started_at=fine - dt.timedelta(seconds=esito.elapsed),
                finished_at=fine,
                jobs_fetched=esito.fetched,
                jobs_new=esito.new,
                jobs_duplicate=esito.duplicate,
                api_calls=esito.api_calls,
                error=esito.error,
            )
        )
    session.flush()
