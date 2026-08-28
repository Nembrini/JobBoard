"""Adzuna — aggregatore con copertura europea, chiave gratuita.

È la fonte più importante per il mercato italiano ed europeo on-site: copre
IT, DE, NL, ES, FR, UK e altri con un piano gratuito ampio.

**Il campo `salary_is_predicted` è la ragione per cui questo adapter esiste così
com'è.** Adzuna restituisce una retribuzione anche quando l'annuncio non ne
dichiara alcuna, stimandola dal titolo e dalla zona. È un dato utile per loro e
velenoso per noi: la dashboard promette *"RAL se dichiarata"*, e mostrare una
stima come se fosse dichiarata è esattamente il genere di bugia che rende
inutilizzabile una tabella. Quando `salary_is_predicted` vale `"1"`, la
retribuzione viene scartata.
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

_ENDPOINT = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

#: Paesi serviti da Adzuna, in ISO alpha-2 minuscolo. Chiederne uno fuori elenco
#: restituisce 404, e il messaggio dell'API non dice perché.
SUPPORTED_COUNTRIES = frozenset(
    {
        "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "gb",
        "in", "it", "mx", "nl", "nz", "pl", "sg", "us", "za",
    }
)  # fmt: skip

#: Valuta per paese: l'API restituisce gli importi senza dichiararla.
_CURRENCY_BY_COUNTRY = {
    "at": "EUR", "be": "EUR", "de": "EUR", "es": "EUR", "fr": "EUR",
    "it": "EUR", "nl": "EUR", "gb": "GBP", "us": "USD", "ca": "CAD",
    "au": "AUD", "ch": "CHF", "pl": "PLN", "br": "BRL", "in": "INR",
    "mx": "MXN", "nz": "NZD", "sg": "SGD", "za": "ZAR",
}  # fmt: skip

#: Massimo consentito dall'API per pagina.
_MAX_PER_PAGE = 50


@register
class AdzunaAdapter(SourceAdapter):
    slug = "adzuna"
    display_name = "Adzuna"
    required_settings = ("adzuna_app_id", "adzuna_app_key")
    default_rate_limit_per_min = 25

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        if missing := self.missing_settings():
            raise SourceError(f"Adzuna non configurato: manca {', '.join(missing)}")

        countries = [c.lower() for c in query.countries if c.lower() in SUPPORTED_COUNTRIES]
        if skipped := sorted({c.lower() for c in query.countries} - set(countries)):
            # Non è un errore: alcuni mercati semplicemente non sono su Adzuna.
            # Ma va detto, altrimenti sembra che la fonte non trovi nulla lì.
            log.info(
                "Adzuna non copre %s: quei mercati vanno cercati con le altre fonti",
                ", ".join(skipped),
            )

        for country in countries:
            for keyword in query.keywords:
                yield from self._search(http, country, keyword, query)

    def _search(
        self, http: HttpClient, country: str, keyword: str, query: SearchQuery
    ) -> Iterator[RawJob]:
        per_page = min(query.max_results_per_keyword, _MAX_PER_PAGE)
        params = {
            "app_id": self.settings.adzuna_app_id,
            "app_key": self.settings.adzuna_app_key.get_secret_value(),
            "results_per_page": per_page,
            "what": keyword,
            "max_days_old": query.posted_within_days,
            "content-type": "application/json",
        }
        if query.remote_only:
            params["what_or"] = "remote smart working telelavoro"

        payload = http.get_json(_ENDPOINT.format(country=country, page=1), params=params)
        for entry in payload.get("results") or []:
            job = _to_raw_job(entry, country)
            if job is not None:
                yield job


def _to_raw_job(entry: dict[str, Any], country: str) -> RawJob | None:
    job_id = entry.get("id")
    title = entry.get("title")
    if not (job_id and title):
        return None

    company = (entry.get("company") or {}).get("display_name") or "Azienda non dichiarata"
    location = (entry.get("location") or {}).get("display_name")

    # "1" come stringa, non True: l'API restituisce i booleani come stringhe.
    predicted = str(entry.get("salary_is_predicted", "0")) == "1"
    salary_min = None if predicted else _number(entry.get("salary_min"))
    salary_max = None if predicted else _number(entry.get("salary_max"))

    return RawJob(
        source=AdzunaAdapter.slug,
        external_id=str(job_id),
        title=str(title),
        company=str(company),
        url=str(entry.get("redirect_url") or ""),
        description=str(entry.get("description") or ""),
        location=str(location) if location else None,
        country=country.upper(),
        posted_at=parse_iso(entry.get("created")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=_CURRENCY_BY_COUNTRY.get(country) if salary_min or salary_max else None,
        # Adzuna normalizza tutto ad annuo, quindi il periodo è noto per costruzione.
        salary_period=SalaryPeriod.YEARLY if salary_min or salary_max else None,
        contract_hint=" ".join(
            str(entry.get(field) or "") for field in ("contract_type", "contract_time")
        ).strip()
        or None,
        raw=entry,
    )


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
