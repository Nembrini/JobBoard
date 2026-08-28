"""Interfaccia comune a tutte le fonti di annunci.

Un adapter fa **una cosa sola**: interroga la sua API e restituisce dei
:class:`RawJob`. Non normalizza, non deduplica, non scrive sul database. Cosi' le
API di terzi — che cambiano senza preavviso — restano confinate qui, e la
pipeline a valle vede sempre la stessa forma.

Il rate limiting e i retry stanno in :class:`HttpClient` invece che nei singoli
adapter: sono sbagli che si fanno una volta per fonte, e con nove fonti diventano
nove occasioni di farli.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Settings
from ..models.enums import AtsType, SalaryPeriod

log = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """Errore non recuperabile: chiave sbagliata, endpoint sparito, risposta assurda."""


class SourceTemporaryError(SourceError):
    """Vale la pena ritentare: 429, 5xx, timeout, connessione caduta."""


class RawJob(BaseModel):
    """Un annuncio come lo restituisce una fonte, prima di ogni normalizzazione.

    I campi ``*_hint`` contengono le parole della fonte cosi' come sono: la
    traduzione in enum e' un lavoro di :mod:`jobboard.pipeline.normalize`, che
    puo' cambiare idea senza toccare nove adapter.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: str
    #: Identificativo presso la fonte. Deve essere stabile fra due run, altrimenti
    #: lo stesso annuncio risulta nuovo ogni giorno.
    external_id: str
    title: str
    company: str
    url: str

    description: str = ""
    location: str | None = None
    #: ISO 3166-1 alpha-2, solo se la fonte lo dichiara.
    country: str | None = None
    #: ``None`` significa "la fonte non si esprime", che e' diverso da "non remoto".
    is_remote: bool | None = None

    posted_at: dt.datetime | None = None

    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None
    #: Retribuzione presente solo come testo ("40-50k RAL"): la interpreta
    #: :mod:`jobboard.pipeline.salary`.
    salary_text: str | None = None

    contract_hint: str | None = None
    seniority_hint: str | None = None

    #: Link diretto al form di candidatura, quando la fonte lo distingue dalla
    #: pagina dell'annuncio.
    apply_url: str | None = None
    ats_type: AtsType = AtsType.UNKNOWN
    ats_board_token: str | None = None
    ats_job_id: str | None = None

    #: Payload originale, salvato in ``job_source_link.raw``: permette di
    #: riprocessare senza rifare la chiamata, che con JSearch pesa sul budget.
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("posted_at")
    @classmethod
    def _aware(cls, v: dt.datetime | None) -> dt.datetime | None:
        """Le date senza fuso vanno considerate UTC.

        Meta' delle fonti restituisce ISO senza offset. Le colonne sono
        ``TIMESTAMPTZ``: scriverci un datetime naive lo fa interpretare nel fuso
        del server, e un annuncio pubblicato oggi risulterebbe di due ore fa o fra
        due ore a seconda di dove gira il processo.
        """
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=dt.UTC)
        return v


#: Parole che compaiono in mezzo titolo e non distinguono niente. Tenerle
#: renderebbe "senior" un criterio di pertinenza.
_STOPWORDS = frozenset(
    {
        "senior", "junior", "lead", "staff", "principal", "mid", "level", "entry",
        "and", "or", "the", "di", "de", "der", "und", "con", "per", "in", "at",
    }
)  # fmt: skip

_TOKENS = re.compile(r"[a-z0-9+#]+")

#: Sotto questa lunghezza un token va confrontato per intero: "qa" come prefisso
#: pescherebbe "qatar", "ai" pescherebbe "aircraft".
_MIN_PREFIX_LEN = 4


def title_matches(title: str, keywords: Sequence[str], extra: str = "") -> bool:
    """Il titolo riguarda una delle ricerche?

    Serve alle fonti che restituiscono l'intera board e vanno filtrate qui: una
    sola azienda grande porterebbe centinaia di annunci di vendita e
    amministrazione dentro la pipeline, e ognuno costerebbe un embedding.

    Il confronto e' **per parola, non per frase**. La prima versione cercava la
    frase come sottostringa e non trovava nulla: "software developer" non compare
    dentro "Senior Software Engineer" ne' dentro "Backend Developer", che sono
    esattamente gli annunci da tenere. Basta che una parola significativa della
    ricerca compaia nel titolo.
    """
    if not keywords:
        return True

    parole = set(_TOKENS.findall(f"{title} {extra}".lower()))
    for keyword in keywords:
        significative = [t for t in _TOKENS.findall(keyword.lower()) if t not in _STOPWORDS]
        if any(_present(token, parole) for token in significative):
            return True
    return False


def _present(token: str, parole: set[str]) -> bool:
    """Esatto, oppure per prefisso: "developer" deve trovare anche "developers"."""
    if token in parole:
        return True
    if len(token) < _MIN_PREFIX_LEN:
        return False
    return any(parola.startswith(token) for parola in parole)


def from_epoch(seconds: float | int | None) -> dt.datetime | None:
    """Epoch Unix in secondi -> datetime UTC."""
    if not seconds:
        return None
    return dt.datetime.fromtimestamp(float(seconds), tz=dt.UTC)


def from_epoch_ms(millis: float | int | None) -> dt.datetime | None:
    """Epoch in millisecondi -> datetime UTC. Lever li restituisce cosi'."""
    if not millis:
        return None
    return dt.datetime.fromtimestamp(float(millis) / 1000.0, tz=dt.UTC)


def parse_iso(value: str | None) -> dt.datetime | None:
    """ISO 8601 tollerante, con o senza fuso, con o senza ora."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


@dataclass(frozen=True)
class SearchQuery:
    """Cosa cercare. Volutamente povera: e' il minimo comune fra nove API diverse.

    Quello che una fonte sa fare in piu' (raggio in km, categoria, tipo di
    contratto) sta nel suo ``config``, non qui.
    """

    keywords: tuple[str, ...]
    #: ISO 3166-1 alpha-2. Le fonti solo-remote lo ignorano.
    countries: tuple[str, ...] = ("it",)
    max_results_per_keyword: int = 50
    posted_within_days: int = 21
    remote_only: bool = False


@dataclass
class HttpClient:
    """Client HTTP con limite di frequenza e retry, condiviso da tutti gli adapter.

    Il limite e' applicato come intervallo minimo fra due chiamate invece che come
    finestra scorrevole: gli adapter girano in sequenza in un solo processo, quindi
    e' equivalente e non richiede stato da mantenere.
    """

    rate_limit_per_min: int = 30
    timeout: float = 20.0
    headers: Mapping[str, str] = field(default_factory=dict)
    user_agent: str = "JobBoard/0.1 (uso personale)"

    #: Chiamate effettuate, per la riga ``run``.
    calls: int = 0
    _last_call: float = 0.0
    _client: httpx.Client | None = None

    def __post_init__(self) -> None:
        if self.rate_limit_per_min <= 0:
            raise ValueError("rate_limit_per_min deve essere positivo")

    @property
    def _min_interval(self) -> float:
        return 60.0 / self.rate_limit_per_min

    def __enter__(self) -> HttpClient:
        self._client = httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent, **dict(self.headers)},
            follow_redirects=True,
        )
        return self

    def __exit__(self, *exc: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def get_json(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._request("GET", url, params=params)

    def post_json(self, url: str, payload: Mapping[str, Any]) -> Any:
        return self._request("POST", url, json=payload)

    def get_text(self, url: str, params: Mapping[str, Any] | None = None) -> str:
        response = self._send("GET", url, params=params)
        return response.text

    @retry(
        retry=retry_if_exception_type(SourceTemporaryError),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = self._send(method, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            # Capita quando una fonte risponde 200 con una pagina HTML di errore o
            # di manutenzione: e' un guasto temporaneo travestito da successo.
            raise SourceTemporaryError(
                f"{url}: risposta non JSON ({response.headers.get('content-type')})"
            ) from exc

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            raise SourceError("HttpClient va usato come context manager")

        self._wait_for_slot()
        self.calls += 1
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise SourceTemporaryError(f"{url}: timeout dopo {self.timeout}s") from exc
        except httpx.TransportError as exc:
            raise SourceTemporaryError(f"{url}: {type(exc).__name__}") from exc

        _raise_for_status(url, response)
        return response

    def _wait_for_slot(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()


def _raise_for_status(url: str, response: httpx.Response) -> None:
    if response.is_success:
        return
    code = response.status_code
    # 429 e 5xx passano; un 404 su una board che non esiste piu' e' definitivo, e
    # ritentarlo quattro volte con backoff sprecherebbe solo tempo.
    if code == 429 or code >= 500:
        raise SourceTemporaryError(f"{url}: HTTP {code}")
    raise SourceError(f"{url}: HTTP {code} — {response.text[:200]}")


class SourceAdapter(ABC):
    """Una fonte di annunci."""

    #: Chiave nel registry e nella colonna ``source.adapter``.
    slug: ClassVar[str]
    display_name: ClassVar[str]
    #: Nomi dei campi di ``Settings`` senza i quali la fonte non puo' funzionare.
    #: Vuoto per le fonti che non richiedono autenticazione.
    required_settings: ClassVar[tuple[str, ...]] = ()
    default_rate_limit_per_min: ClassVar[int] = 30
    #: Tetto di chiamate al giorno imposto dal piano gratuito, se ce n'e' uno.
    default_daily_budget: ClassVar[int | None] = None

    def __init__(
        self,
        settings: Settings,
        config: Mapping[str, Any] | None = None,
        *,
        rate_limit_per_min: int | None = None,
    ) -> None:
        self.settings = settings
        self.config = dict(config or {})
        self.rate_limit_per_min = rate_limit_per_min or self.default_rate_limit_per_min

    @abstractmethod
    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        """Restituisce gli annunci della fonte.

        Riceve il client invece di crearlo: cosi' il conteggio delle chiamate e il
        rate limit valgono per l'intera sessione della fonte, e un adapter non puo'
        dimenticarsi di applicarli.
        """

    def is_configured(self) -> bool:
        """``True`` se ci sono tutte le chiavi necessarie."""
        return not self.missing_settings()

    def missing_settings(self) -> list[str]:
        missing = []
        for name in self.required_settings:
            value: Any = getattr(self.settings, name, None)
            actual = value.get_secret_value() if isinstance(value, SecretStr) else value
            if not actual:
                missing.append(name.upper())
        return missing

    def new_client(self) -> HttpClient:
        return HttpClient(rate_limit_per_min=self.rate_limit_per_min, headers=self.http_headers())

    def http_headers(self) -> dict[str, str]:
        return {}

    def __repr__(self) -> str:
        return f"<{type(self).__name__} slug={self.slug!r}>"


# --- registry ----------------------------------------------------------------

_ADAPTERS: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    """Decoratore: iscrive un adapter al registry."""
    if cls.slug in _ADAPTERS:
        raise SourceError(f"adapter duplicato: {cls.slug}")
    _ADAPTERS[cls.slug] = cls
    return cls


def get_adapter_class(slug: str) -> type[SourceAdapter]:
    try:
        return _ADAPTERS[slug]
    except KeyError:
        raise SourceError(
            f"fonte sconosciuta: {slug!r}. Disponibili: {', '.join(sorted(_ADAPTERS))}"
        ) from None


def all_adapter_classes() -> dict[str, type[SourceAdapter]]:
    return dict(_ADAPTERS)
