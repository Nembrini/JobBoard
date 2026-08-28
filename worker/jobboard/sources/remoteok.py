"""RemoteOK — annunci remote, senza autenticazione.

Tre particolarità di questa API, tutte verificate sulla risposta vera:

1. **Il primo elemento dell'array non è un annuncio**, è un avviso legale con i
   termini d'uso. Trattarlo come annuncio produce una riga con titolo vuoto a
   ogni run.
2. **Le retribuzioni assenti valgono ``0``, non ``null``.** Uno zero preso per
   buono diventerebbe un annuncio "da 0 €", ordinato in fondo alla tabella come
   se la RAL fosse dichiarata.
3. **I termini richiedono di citare Remote OK e linkare l'annuncio** con un link
   seguibile. La dashboard mostra sempre la fonte e il link originale, quindi la
   condizione è soddisfatta — ma va tenuta presente se un giorno si togliesse la
   colonna "fonte".
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..models.enums import SalaryPeriod
from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    from_epoch,
    register,
    title_matches,
)

_ENDPOINT = "https://remoteok.com/api"


@register
class RemoteOkAdapter(SourceAdapter):
    slug = "remoteok"
    display_name = "RemoteOK"
    default_rate_limit_per_min = 10

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        payload = http.get_json(_ENDPOINT)
        if not isinstance(payload, list):
            return

        wanted = tuple(k.lower() for k in query.keywords)
        for entry in payload:
            if not isinstance(entry, dict) or "legal" in entry:
                continue  # l'avviso legale in testa all'array
            job = _to_raw_job(entry)
            # Oltre al titolo si guardano i tag, che su RemoteOK sono la
            # classificazione vera dell'annuncio ("golang", "backend").
            tag = " ".join(str(t) for t in entry.get("tags") or [])
            if job is None or not title_matches(job.title, wanted, tag):
                continue
            yield job


def _to_raw_job(entry: dict[str, Any]) -> RawJob | None:
    job_id = entry.get("id")
    title = entry.get("position")
    company = entry.get("company")
    url = entry.get("url")
    if not (job_id and title and company and url):
        return None

    return RawJob(
        source=RemoteOkAdapter.slug,
        external_id=str(job_id),
        title=str(title),
        company=str(company),
        url=str(url),
        description=str(entry.get("description") or ""),
        location=str(entry.get("location") or "") or None,
        is_remote=True,
        posted_at=from_epoch(entry.get("epoch")),
        # Lo zero significa "non dichiarata": passarlo avanti creerebbe annunci
        # con RAL zero indistinguibili da quelli davvero mal pagati.
        salary_min=_positive(entry.get("salary_min")),
        salary_max=_positive(entry.get("salary_max")),
        # RemoteOK pubblica cifre annue in dollari senza dichiarare né la valuta
        # né il periodo: entrambi sono convenzioni della board, non dati.
        salary_currency="USD" if _positive(entry.get("salary_min")) else None,
        salary_period=SalaryPeriod.YEARLY if _positive(entry.get("salary_min")) else None,
        apply_url=str(entry.get("apply_url") or "") or None,
        raw=entry,
    )


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
