"""Arbeitnow — job board tedesca, senza autenticazione.

Copre soprattutto la Germania più una quota di annunci remote in Europa. Utile
perché la Germania è uno dei mercati scelti e perché non costa nulla: l'endpoint
è pubblico e non richiede né chiave né registrazione.

Limite noto: l'API restituisce una sola pagina alla volta senza filtro di ricerca
lato server. Si scaricano le pagine e si filtra qui.
"""

from __future__ import annotations

import html
from collections.abc import Iterator
from typing import Any

from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    from_epoch,
    register,
    title_matches,
)

_ENDPOINT = "https://www.arbeitnow.com/api/job-board-api"


@register
class ArbeitnowAdapter(SourceAdapter):
    slug = "arbeitnow"
    display_name = "Arbeitnow"
    default_rate_limit_per_min = 30

    #: Oltre questo numero di pagine si scende in annunci vecchi di settimane.
    default_max_pages = 5

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        max_pages = int(self.config.get("max_pages", self.default_max_pages))
        wanted = tuple(k.lower() for k in query.keywords)
        seen = 0

        for page in range(1, max_pages + 1):
            payload = http.get_json(_ENDPOINT, params={"page": page})
            entries = payload.get("data") or []
            if not entries:
                break

            for entry in entries:
                job = _to_raw_job(entry)
                if job is None or not title_matches(job.title, wanted):
                    continue
                yield job
                seen += 1
                if seen >= query.max_results_per_keyword * max(len(wanted), 1):
                    return


def _to_raw_job(entry: dict[str, Any]) -> RawJob | None:
    slug = entry.get("slug")
    title = entry.get("title")
    company = entry.get("company_name")
    if not (slug and title and company):
        return None

    job_types = entry.get("job_types") or []
    return RawJob(
        source=ArbeitnowAdapter.slug,
        external_id=str(slug),
        title=str(title),
        company=str(company),
        url=str(entry.get("url") or f"https://www.arbeitnow.com/jobs/companies/{slug}"),
        # Arbeitnow restituisce l'HTML con le entità già codificate una volta di
        # troppo: senza unescape la descrizione arriva come "&lt;p&gt;Testo".
        description=html.unescape(str(entry.get("description") or "")),
        location=str(entry.get("location") or "") or None,
        # La board è tedesca: quando non dice altro, l'annuncio è in Germania.
        country="DE",
        is_remote=bool(entry.get("remote")) if entry.get("remote") is not None else None,
        posted_at=from_epoch(entry.get("created_at")),
        contract_hint=", ".join(str(t) for t in job_types) or None,
        raw=entry,
    )
