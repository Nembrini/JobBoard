"""Jooble — aggregatore multi-paese, chiave gratuita.

La chiave viaggia **nel percorso dell'URL**, non in un header: `POST
https://jooble.org/api/{chiave}`. Comodo per loro, scomodo per noi — significa
che la chiave finisce in ogni log di rete e in ogni messaggio d'errore che
contenga l'URL. Per questo gli errori di questo modulo mascherano l'URL prima di
propagarlo.

Limite importante: il campo `snippet` **non è la job description**, è un estratto
di due righe con i termini cercati evidenziati in `<b>`. Per il matching serve
il testo completo, che qui non c'è: gli annunci Jooble entrano quindi con una
descrizione povera e vanno considerati una fonte di *segnalazione*, non di
contenuto. Quando lo stesso annuncio arriva anche da una board ATS, la dedup lo
unifica e il testo buono vince.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    SourceError,
    parse_iso,
    register,
)

_ENDPOINT = "https://jooble.org/api/{key}"

#: Nomi dei paesi come li vuole Jooble nel campo "location": accetta testo
#: libero, ma con il nome inglese del paese la copertura è migliore.
_COUNTRY_NAMES = {
    "IT": "Italy",
    "DE": "Germany",
    "NL": "Netherlands",
    "ES": "Spain",
    "FR": "France",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "PT": "Portugal",
    "AT": "Austria",
    "BE": "Belgium",
    "CH": "Switzerland",
    "PL": "Poland",
}


@register
class JoobleAdapter(SourceAdapter):
    slug = "jooble"
    display_name = "Jooble"
    required_settings = ("jooble_api_key",)
    default_rate_limit_per_min = 20

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        if missing := self.missing_settings():
            raise SourceError(f"Jooble non configurato: manca {', '.join(missing)}")

        url = _ENDPOINT.format(key=self.settings.jooble_api_key.get_secret_value())
        for country in query.countries:
            location = _COUNTRY_NAMES.get(country.upper(), country)
            for keyword in query.keywords:
                payload = self._search(http, url, keyword, location)
                for entry in payload.get("jobs") or []:
                    job = _to_raw_job(entry, country.upper())
                    if job is not None:
                        yield job

    def _search(self, http: HttpClient, url: str, keyword: str, location: str) -> dict[str, Any]:
        try:
            result = http.post_json(url, {"keywords": keyword, "location": location, "page": "1"})
        except SourceError as exc:
            # Il messaggio contiene l'URL, e l'URL contiene la chiave.
            raise type(exc)(_mask(str(exc))) from None
        return result if isinstance(result, dict) else {}


def _mask(message: str) -> str:
    """Sostituisce la chiave nell'URL, ovunque compaia nel messaggio."""
    return re.sub(r"(jooble\.org/api/)[^/\s]+", r"\1***", message)


def _to_raw_job(entry: dict[str, Any], country: str) -> RawJob | None:
    job_id = entry.get("id")
    title = entry.get("title")
    link = entry.get("link")
    if not (job_id and title and link):
        return None

    return RawJob(
        source=JoobleAdapter.slug,
        external_id=str(job_id),
        title=str(title),
        company=str(entry.get("company") or "") or "Azienda non dichiarata",
        url=str(link),
        # Estratto, non descrizione: vedi la nota in testa al modulo.
        description=str(entry.get("snippet") or ""),
        location=str(entry.get("location") or "") or None,
        country=country,
        posted_at=parse_iso(entry.get("updated")),
        # Testo libero e in lingua locale: "30.000 € all'anno", "€15/ora".
        salary_text=str(entry.get("salary") or "") or None,
        contract_hint=str(entry.get("type") or "") or None,
        raw=entry,
    )
