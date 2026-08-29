"""Da :class:`RawJob` a annuncio canonico.

Ogni fonte descrive le stesse cose con parole proprie: "Full-time" e "Tempo
pieno", "Remote" e "Smart working", "Mid-Senior level" e "3+ years". Qui
diventano gli enum del dominio, una volta sola, così che il matching e la
dashboard non debbano mai più sapere da dove arriva un annuncio.

Regola trasversale: **quando il segnale non c'è, il valore è ``UNKNOWN``**. Un
annuncio senza modalità dichiarata non è on-site per default — quella sarebbe
un'invenzione che poi filtra via annunci buoni.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..models.enums import AtsType, ContractType, Seniority, WorkMode
from ..sources.base import RawJob
from . import salary as salary_mod
from .text import content_hash, html_to_text, normalize_company, normalize_key, simhash


@dataclass(frozen=True)
class NormalizedJob:
    """Un annuncio pronto per il database, indipendente dalla fonte."""

    source: str
    external_id: str

    title: str
    company: str
    company_normalized: str
    canonical_key: str
    content_hash: str
    simhash: int

    location_raw: str | None
    city: str | None
    region: str | None
    country: str | None
    work_mode: WorkMode

    salary: salary_mod.Salary

    contract_type: ContractType
    seniority: Seniority
    job_family: str | None

    description_raw: str
    description_clean: str
    lang: str | None

    url: str
    apply_url: str | None
    ats_type: AtsType
    ats_board_token: str | None
    ats_job_id: str | None

    posted_at: datetime | None
    #: Il portale che pubblica davvero l'annuncio, quando la fonte e' un
    #: aggregatore. Passa da qui senza essere toccato: e' un nome proprio, e
    #: normalizzarlo vorrebbe dire riscrivere "LinkedIn" a modo nostro.
    publisher: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def normalize(job: RawJob) -> NormalizedJob:
    """Traduce un annuncio grezzo nella forma canonica."""
    clean = html_to_text(job.description)
    title = tidy_title(job.title)
    city, region, country = split_location(job.location, job.country)

    return NormalizedJob(
        source=job.source,
        external_id=job.external_id,
        title=title,
        company=job.company.strip(),
        company_normalized=normalize_company(job.company),
        canonical_key=canonical_key(job.company, title, city),
        content_hash=content_hash(f"{title}\n{clean}"),
        simhash=simhash(clean or title),
        location_raw=job.location,
        city=city,
        region=region,
        country=country,
        work_mode=work_mode(job, clean),
        salary=_salary(job),
        contract_type=contract_type(job, clean),
        seniority=seniority(job),
        job_family=job_family(title),
        description_raw=job.description,
        description_clean=clean,
        lang=detect_language(clean or title),
        url=job.url,
        apply_url=job.apply_url,
        ats_type=job.ats_type,
        ats_board_token=job.ats_board_token,
        ats_job_id=job.ats_job_id,
        posted_at=job.posted_at,
        publisher=job.publisher,
        raw=job.raw,
    )


def canonical_key(company: str, title: str, city: str | None) -> str:
    """Chiave di primo livello per la dedup: azienda + ruolo + città.

    Non include la fonte, ovviamente: serve proprio a far collidere lo stesso
    annuncio visto da fonti diverse.
    """
    return "|".join((normalize_company(company), normalize_key(title), normalize_key(city)))


# --- titolo -------------------------------------------------------------------

#: Suffissi di genere obbligatori negli annunci in area tedesca e francese.
_TITLE_NOISE = re.compile(
    # Il separatore e' opzionale: "Softwareentwickler m/w/d" senza trattino ne'
    # parentesi e' altrettanto comune di "Softwareentwickler (m/w/d)".
    r"\s*[-–|(]?\s*(?:m/w/d|w/m/d|m/f/d|f/m/d|m/f/x|d/f/m|h/f|m/f|m/w)\s*\)?\s*$",  # noqa: RUF001
    re.IGNORECASE,
)


def tidy_title(title: str) -> str:
    """Toglie i suffissi di genere, che sporcano ogni confronto.

    "Softwareentwickler (m/w/d)" e "Softwareentwickler" sono lo stesso ruolo, ma
    con il suffisso la chiave canonica non collide e l'embedding spende token su
    una formula legale.
    """
    return _TITLE_NOISE.sub("", title).strip(" -–|")  # noqa: RUF001


# --- modalità di lavoro -------------------------------------------------------

_HYBRID = re.compile(r"\b(hybrid|ibrid[oa]|misto|part[- ]?remote)\b", re.IGNORECASE)
_REMOTE = re.compile(
    r"\b(remote|remoto|da remoto|smart[- ]working|telelavoro|work from home)\b",
    re.IGNORECASE,
)
_ONSITE = re.compile(
    r"\b(on[- ]?site|in sede|in presenza|presso la sede|office[- ]based)\b",
    re.IGNORECASE,
)


def work_mode(job: RawJob, description: str) -> WorkMode:
    """Modalità di lavoro, in ordine di affidabilità del segnale.

    L'ordine conta: il campo strutturato della fonte batte il testo, e il titolo
    batte la descrizione. Cercare "remote" nella descrizione è l'ultima risorsa
    perché mezza Silicon Valley scrive "we are a remote-friendly company" in
    fondo ad annunci rigorosamente on-site.
    """
    testa = f"{job.title}\n{job.location or ''}"
    # Un annuncio marcato remoto che parla di ibrido è ibrido: è il caso comune
    # degli aggregatori, che appiattiscono tutto su una spunta sì/no.
    if _HYBRID.search(testa):
        return WorkMode.HYBRID
    if job.is_remote is True:
        return WorkMode.HYBRID if _HYBRID.search(description[:1500]) else WorkMode.REMOTE
    if _REMOTE.search(testa):
        return WorkMode.REMOTE
    if _ONSITE.search(testa):
        return WorkMode.ON_SITE
    if job.is_remote is False:
        return WorkMode.ON_SITE

    inizio = description[:1500]
    if _HYBRID.search(inizio):
        return WorkMode.HYBRID
    if _REMOTE.search(inizio):
        return WorkMode.REMOTE
    return WorkMode.UNKNOWN


# --- contratto ----------------------------------------------------------------

#: Ordine significativo: si ferma alla prima corrispondenza, e le voci più
#: specifiche vengono prima. "Full-time internship" è uno stage, non un
#: indeterminato.
_CONTRACT_PATTERNS: tuple[tuple[ContractType, str], ...] = (
    (ContractType.INTERNSHIP, r"\b(intern|internship|stage|tirocin\w*|praktikum)\b"),
    (ContractType.APPRENTICESHIP, r"\b(apprendistato|apprenticeship|ausbildung)\b"),
    (ContractType.CONTRACT, r"\b(freelance|contractor|partita iva|p\.? ?iva|b2b|contract)\b"),
    (ContractType.FIXED_TERM, r"\b(fixed[- ]term|temporary|tempo determinato|befristet)\b"),
    (ContractType.PART_TIME, r"\b(part[- ]?time|tempo parziale|teilzeit)\b"),
    (ContractType.PERMANENT, r"\b(permanent|full[- ]?time|indeterminato|unbefristet|vollzeit)\b"),
)

_CONTRACTS = tuple((tipo, re.compile(p, re.IGNORECASE)) for tipo, p in _CONTRACT_PATTERNS)


def contract_type(job: RawJob, description: str) -> ContractType:
    testo = " ".join(filter(None, (job.contract_hint, job.title)))
    for tipo, pattern in _CONTRACTS:
        if pattern.search(testo):
            return tipo
    # La descrizione è meno affidabile: "possibilità di stage" in fondo a un
    # annuncio per senior non lo rende uno stage. Si guardano solo le prime righe.
    for tipo, pattern in _CONTRACTS:
        if pattern.search(description[:800]):
            return tipo
    return ContractType.UNKNOWN


# --- livello ------------------------------------------------------------------

_SENIORITY_PATTERNS: tuple[tuple[Seniority, str], ...] = (
    (Seniority.INTERN, r"\b(intern|internship|stage|tirocin\w*|working student|werkstudent)\b"),
    (Seniority.PRINCIPAL, r"\b(principal|distinguished|architect|director|vp|head of)\b"),
    (Seniority.LEAD, r"\b(lead|staff|manager|team lead|tech lead|responsabile)\b"),
    (Seniority.SENIOR, r"\b(senior|sr\.?|esperto|expert|mid[- ]senior)\b"),
    (Seniority.JUNIOR, r"\b(junior|jr\.?|entry[- ]level|graduate|neolaureat\w*|trainee)\b"),
    (Seniority.MID, r"\b(mid[- ]?level|intermediate|middle)\b"),
)

_SENIORITIES = tuple((livello, re.compile(p, re.IGNORECASE)) for livello, p in _SENIORITY_PATTERNS)


def seniority(job: RawJob) -> Seniority:
    """Livello dichiarato dalla fonte, altrimenti dedotto dal titolo.

    Il campo della fonte viene prima perché è un dato, mentre il titolo è una
    scelta di marketing: "Senior" nel titolo di un annuncio che poi chiede due
    anni di esperienza succede di continuo.
    """
    if job.seniority_hint:
        for livello, pattern in _SENIORITIES:
            if pattern.search(job.seniority_hint):
                return livello
    for livello, pattern in _SENIORITIES:
        if pattern.search(job.title):
            return livello
    return Seniority.UNKNOWN


# --- famiglia di ruolo --------------------------------------------------------

#: È la colonna "tipo di lavoro" della dashboard. Ordine significativo: le
#: famiglie più specifiche vengono prima di quelle generiche, altrimenti
#: "Machine Learning Engineer" finirebbe fra i software developer.
_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Machine Learning Engineer", r"\b(machine learning|ml engineer|deep learning|nlp)\b"),
    ("Data Scientist", r"\b(data scientist|scienziat[oa] dei dati|statistician)\b"),
    ("Data Engineer", r"\b(data engineer|etl|data platform|analytics engineer)\b"),
    ("Data Analyst", r"\b(data analyst|business intelligence|bi analyst|analista dati)\b"),
    ("DevOps / SRE", r"\b(devops|sre|site reliability|platform engineer|cloud engineer)\b"),
    ("Security Engineer", r"\b(security|sicurezza informatica|appsec|cybersecurity)\b"),
    ("Mobile Developer", r"\b(mobile|android|ios|flutter|react native)\b"),
    ("Frontend Developer", r"\b(frontend|front[- ]end|react|angular|vue|ui engineer)\b"),
    ("Backend Developer", r"\b(backend|back[- ]end|server[- ]side|api engineer)\b"),
    ("Fullstack Developer", r"\b(full[- ]?stack)\b"),
    ("QA Engineer", r"\b(qa|quality assurance|test engineer|tester)\b"),
    ("Embedded Engineer", r"\b(embedded|firmware|rtos|plc)\b"),
    ("Product Manager", r"\b(product manager|product owner)\b"),
    # Nessun confine di parola in coda, di proposito: il tedesco compone i nomi e
    # "Softwareentwickler" e' una parola sola. Con "\bentwickler\b" nessun
    # annuncio tedesco veniva classificato, e la Germania e' uno dei mercati
    # scelti. Vale anche per "engineering" e "developers".
    ("Software Developer", r"\b(software|developer|engineer|sviluppator|programmier)"),
)

_FAMILIES = tuple((nome, re.compile(p, re.IGNORECASE)) for nome, p in _FAMILY_PATTERNS)


def job_family(title: str) -> str | None:
    """Categoria leggibile del ruolo, per la colonna "tipo" della dashboard."""
    for nome, pattern in _FAMILIES:
        if pattern.search(title):
            return nome
    return None


# --- luogo --------------------------------------------------------------------

#: Nomi di paese come compaiono negli annunci -> ISO alpha-2. Coperti i mercati
#: scelti più quelli che ricorrono negli annunci remote.
_COUNTRY_NAMES = {
    "italia": "IT", "italy": "IT", "italie": "IT", "italien": "IT",
    "germania": "DE", "germany": "DE", "deutschland": "DE", "allemagne": "DE",
    "paesi bassi": "NL", "netherlands": "NL", "nederland": "NL", "holland": "NL",
    "spagna": "ES", "spain": "ES", "espana": "ES",
    "francia": "FR", "france": "FR", "frankreich": "FR",
    "regno unito": "GB", "united kingdom": "GB", "uk": "GB", "england": "GB",
    "irlanda": "IE", "ireland": "IE", "portogallo": "PT", "portugal": "PT",
    "austria": "AT", "osterreich": "AT",
    "belgio": "BE", "belgium": "BE", "belgique": "BE",
    "svizzera": "CH", "switzerland": "CH", "schweiz": "CH", "suisse": "CH",
    "polonia": "PL", "poland": "PL", "polska": "PL",
    "svezia": "SE", "sweden": "SE", "danimarca": "DK", "denmark": "DK",
    "norvegia": "NO", "norway": "NO", "finlandia": "FI", "finland": "FI",
    "grecia": "GR", "greece": "GR", "romania": "RO",
    "repubblica ceca": "CZ", "czech republic": "CZ", "czechia": "CZ",
    "ungheria": "HU", "hungary": "HU",
    "stati uniti": "US", "united states": "US", "usa": "US", "u s a": "US",
    "canada": "CA", "india": "IN", "australia": "AU", "brasile": "BR", "brazil": "BR",
}  # fmt: skip

#: Valori che occupano il campo luogo senza indicare un luogo. Sono frequenti
#: sulle board remote, dove quel campo dice *da dove si può lavorare*.
_NON_PLACES = frozenset(
    {
        "remote", "remoto", "worldwide", "anywhere", "global", "europe", "emea",
        "eu", "europa", "multiple locations", "various", "n a", "unknown",
        "remote emea", "remote europe", "remote worldwide", "fully remote",
        "latam", "americas", "apac", "united states or canada",
    }
)  # fmt: skip

_LOCATION_SPLIT = re.compile(r"[,/]|\s+[-–]\s+")  # noqa: RUF001


def split_location(
    raw: str | None, declared_country: str | None
) -> tuple[str | None, str | None, str | None]:
    """Da "Milano, Italia" a ``("Milano", None, "IT")``.

    Il paese dichiarato dalla fonte ha la precedenza sul testo: è un dato
    strutturato, mentre il testo è quello che ha scritto chi ha pubblicato.
    """
    country = declared_country.upper()[:2] if declared_country else None
    if not raw or not raw.strip():
        return None, None, country

    pezzi = [p.strip() for p in _LOCATION_SPLIT.split(raw) if p.strip()]
    if not pezzi:
        return None, None, country

    if len(pezzi) > 1 and (codice := _COUNTRY_NAMES.get(normalize_key(pezzi[-1]))):
        country = country or codice
        pezzi = pezzi[:-1]
    elif len(pezzi) == 1 and (codice := _COUNTRY_NAMES.get(normalize_key(pezzi[0]))):
        # Il campo conteneva solo il paese: nessuna città da estrarre.
        return None, None, country or codice

    citta = pezzi[0] if pezzi and normalize_key(pezzi[0]) not in _NON_PLACES else None
    regione = pezzi[1] if len(pezzi) > 1 else None
    return citta, regione, country


# --- retribuzione e lingua ----------------------------------------------------

#: Valuta implicita quando l'annuncio scrive una cifra senza simbolo.
_CURRENCY_BY_COUNTRY = {
    "IT": "EUR", "DE": "EUR", "NL": "EUR", "ES": "EUR", "FR": "EUR", "IE": "EUR",
    "PT": "EUR", "AT": "EUR", "BE": "EUR", "GR": "EUR", "FI": "EUR",
    "GB": "GBP", "CH": "CHF", "PL": "PLN", "SE": "SEK", "DK": "DKK", "NO": "NOK",
    "CZ": "CZK", "US": "USD", "CA": "CAD", "AU": "AUD",
}  # fmt: skip


def _salary(job: RawJob) -> salary_mod.Salary:
    """Preferisce i campi strutturati; ricade sul testo solo se non ce ne sono."""
    strutturata = salary_mod.from_structured(
        job.salary_min, job.salary_max, job.salary_currency, job.salary_period
    )
    if strutturata.is_stated:
        return strutturata
    if job.salary_text:
        valuta = _CURRENCY_BY_COUNTRY.get((job.country or "").upper())
        return salary_mod.parse(job.salary_text, default_currency=valuta)
    return salary_mod.NOT_STATED


def detect_language(text: str) -> str | None:
    """Lingua dell'annuncio: serve al filtro dello Stadio 0 e alla lingua del CV."""
    if len(text) < 40:
        return None
    try:
        import py3langid

        code, _ = py3langid.classify(text[:4000])
        return str(code)
    except Exception:  # pragma: no cover - la lingua non è mai bloccante
        return None
