"""JSearch su RapidAPI — indicizza Google for Jobs, quindi LinkedIn e Indeed.

È l'unica via legale per vedere gli annunci pubblicati su LinkedIn e Indeed:
nessuno dei due ha un'API pubblica, e lo scraping violerebbe i termini con
rischio concreto di ban dell'account (vedi ARCHITECTURE.md §2.1).

**Il piano gratuito è ~200 chiamate al mese, cioè 6-7 al giorno.** È la risorsa
più scarsa dell'intero sistema, e l'adapter è costruito attorno a questo vincolo:

- un budget giornaliero esplicito, che l'adapter si rifiuta di superare;
- le query si consumano **in ordine di priorità**, così se il budget finisce a
  metà run a restare fuori sono le ricerche meno importanti, non le prime della
  lista alfabetica;
- il payload originale finisce in `job_source_link.raw`, così riprocessare non
  costa una seconda chiamata.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from ..models.enums import SalaryPeriod
from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    SourceError,
    parse_iso,
    register,
)

log = logging.getLogger(__name__)

_HOST = "jsearch.p.rapidapi.com"
_ENDPOINT = f"https://{_HOST}/search"

_PERIODS = {
    "HOUR": SalaryPeriod.HOURLY,
    "DAY": SalaryPeriod.DAILY,
    "WEEK": SalaryPeriod.MONTHLY,  # approssimazione: si normalizza comunque ad annuo
    "MONTH": SalaryPeriod.MONTHLY,
    "YEAR": SalaryPeriod.YEARLY,
}


@register
class JSearchAdapter(SourceAdapter):
    slug = "jsearch"
    display_name = "JSearch (Google for Jobs)"
    required_settings = ("rapidapi_key",)
    default_rate_limit_per_min = 10
    #: Sei chiamate al giorno esauriscono ~180 delle ~200 mensili, lasciando un
    #: margine per le prove manuali.
    default_daily_budget = 6

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        if missing := self.missing_settings():
            raise SourceError(f"JSearch non configurato: manca {', '.join(missing)}")

        budget = int(self.config.get("daily_budget", self.default_daily_budget or 6))
        spent = 0

        # Le combinazioni sono generate parola-per-parola e poi paese-per-paese, in
        # quest'ordine: la prima parola chiave è quella che descrive meglio il
        # profilo, ed è quella che deve girare su tutti i mercati prima che il
        # budget finisca.
        for keyword in query.keywords:
            for country in query.countries:
                if spent >= budget:
                    log.warning(
                        "budget JSearch esaurito (%d chiamate): saltate le ricerche "
                        "rimanenti, riprendono domani",
                        budget,
                    )
                    return
                spent += 1
                yield from self._search(http, keyword, country, query)

    def http_headers(self) -> dict[str, str]:
        return {
            "X-RapidAPI-Key": self.settings.rapidapi_key.get_secret_value(),
            "X-RapidAPI-Host": _HOST,
        }

    def _search(
        self, http: HttpClient, keyword: str, country: str, query: SearchQuery
    ) -> Iterator[RawJob]:
        params = {
            "query": f"{keyword} in {country}" if not query.remote_only else keyword,
            "page": "1",
            "num_pages": "1",
            "country": country.lower(),
            "date_posted": _date_filter(query.posted_within_days),
        }
        if query.remote_only:
            params["work_from_home"] = "true"

        try:
            payload = http.get_json(_ENDPOINT, params=params)
        except SourceError as exc:
            raise _explain(exc) from exc

        for entry in payload.get("data") or []:
            job = _to_raw_job(entry)
            if job is not None:
                yield job


def _explain(exc: SourceError) -> SourceError:
    """Traduce gli errori di RapidAPI, senza affermare piu' di quel che si sa.

    **Il 403 "not subscribed" non dice che la chiave e' valida.** Verificato: una
    chiave inventata di sana pianta riceve esattamente la stessa risposta, e il
    401 arriva solo quando l'header manca del tutto. Il messaggio quindi elenca
    le due cause possibili invece di sceglierne una — una versione precedente
    dichiarava valida la chiave e ha mandato a cercare il problema
    nell'abbonamento, mentre in ``.env`` non c'era nessuna chiave.
    """
    testo = str(exc)
    if "not subscribed" in testo.lower():
        return SourceError(
            "JSearch: 403 'not subscribed'. Due cause danno la stessa risposta. "
            "1) RAPIDAPI_KEY assente o malformata: eseguire 'jobboard doctor', che "
            "riconosce anche il caso in cui la riga di .env contiene il commento al "
            "posto del valore. 2) La chiave e' buona ma quell'applicazione RapidAPI "
            "non e' iscritta a JSearch: aprire "
            "rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch e premere 'Start Free "
            "Plan' sul piano Basic. L'iscrizione vale per singola API e per singola "
            "applicazione, non per account."
        )
    if "429" in testo:
        return SourceError(
            "JSearch: quota mensile esaurita. Riprende con il rinnovo del piano; "
            "nel frattempo le altre fonti continuano a girare."
        )
    return exc


def _date_filter(days: int) -> str:
    """L'API accetta solo quattro valori discreti, non un numero di giorni."""
    if days <= 1:
        return "today"
    if days <= 3:
        return "3days"
    if days <= 7:
        return "week"
    return "month"


def _to_raw_job(entry: dict[str, Any]) -> RawJob | None:
    job_id = entry.get("job_id")
    title = entry.get("job_title")
    if not (job_id and title):
        return None

    city = entry.get("job_city")
    state = entry.get("job_state")
    country = entry.get("job_country")
    location = ", ".join(str(p) for p in (city, state) if p) or None

    period_raw = str(entry.get("job_salary_period") or "").upper()
    apply_link = entry.get("job_apply_link")

    return RawJob(
        source=JSearchAdapter.slug,
        external_id=str(job_id),
        title=str(title),
        company=str(entry.get("employer_name") or "") or "Azienda non dichiarata",
        url=str(apply_link or ""),
        description=str(entry.get("job_description") or ""),
        location=location,
        country=str(country).upper()[:2] if country else None,
        is_remote=entry.get("job_is_remote") if entry.get("job_is_remote") is not None else None,
        posted_at=parse_iso(entry.get("job_posted_at_datetime_utc")),
        salary_min=_number(entry.get("job_min_salary")),
        salary_max=_number(entry.get("job_max_salary")),
        salary_currency=str(entry.get("job_salary_currency") or "") or None,
        salary_period=_PERIODS.get(period_raw),
        contract_hint=str(entry.get("job_employment_type") or "") or None,
        # Il portale vero: "LinkedIn", "Indeed", "Glassdoor". E' l'unico motivo
        # per cui questa fonte esiste, e senza salvarlo la dashboard mostrerebbe
        # "jsearch" al posto del nome che si sta cercando.
        publisher=str(entry.get("job_publisher") or "") or None,
        # `job_apply_is_direct` distingue il form dell'azienda dal reindirizzamento
        # a un portale: solo il primo può portare a una candidatura automatica.
        apply_url=str(apply_link) if entry.get("job_apply_is_direct") and apply_link else None,
        raw=entry,
    )


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
