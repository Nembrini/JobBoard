"""Remotive — annunci esclusivamente remote, senza autenticazione.

Copre il mercato "remote worldwide", uno dei tre scelti. Ogni annuncio è remoto
per costruzione, quindi ``is_remote`` è sempre ``True``: non è una deduzione, è
la definizione della board.

Il campo che conta davvero è ``candidate_required_location``: dice *da dove* si
può lavorare ("Europe", "USA Only", "Worldwide"). Un annuncio remoto riservato
agli Stati Uniti è inutile quanto uno on-site a Chicago.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    parse_iso,
    register,
    title_matches,
)

_ENDPOINT = "https://remotive.com/api/remote-jobs"

#: Categorie di Remotive che hanno senso per un profilo tecnico. Filtrare qui
#: evita di scaricare annunci di marketing e customer support a ogni run.
_DEFAULT_CATEGORIES = ("software-dev", "devops", "data")

#: Quanti annunci chiedere per categoria. Il filtro avviene qui, quindi vale la
#: pena prenderne parecchi in una sola chiamata invece di tornare a chiedere.
_MAX_PER_CATEGORY = 100


@register
class RemotiveAdapter(SourceAdapter):
    slug = "remotive"
    display_name = "Remotive"
    default_rate_limit_per_min = 20

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        """Una chiamata per categoria, poi il filtro qui.

        La prima versione interrogava l'API una volta per ogni combinazione di
        categoria e parola chiave: **diciotto chiamate e cinquantun secondi** per
        diciannove annunci, perché le risposte si sovrapponevano quasi del tutto.
        E il parametro ``search`` filtra male — restituiva "Office Assistant" e
        "Sales Jedi" dentro la categoria *software-dev*. Scaricare la categoria
        intera e filtrarla qui costa tre chiamate ed è più preciso.
        """
        categories = tuple(self.config.get("categories") or _DEFAULT_CATEGORIES)
        wanted = tuple(query.keywords)
        emitted: set[str] = set()

        for category in categories:
            params: dict[str, Any] = {"category": category, "limit": _MAX_PER_CATEGORY}
            payload = http.get_json(_ENDPOINT, params=params)

            for entry in payload.get("jobs") or []:
                job = _to_raw_job(entry)
                # Le categorie si sovrappongono: lo stesso annuncio compare in
                # "software-dev" e in "devops".
                if job is None or job.external_id in emitted:
                    continue
                if not title_matches(job.title, wanted, " ".join(entry.get("tags") or [])):
                    continue
                emitted.add(job.external_id)
                yield job


def _to_raw_job(entry: dict[str, Any]) -> RawJob | None:
    job_id = entry.get("id")
    title = entry.get("title")
    company = entry.get("company_name")
    url = entry.get("url")
    if not (job_id and title and company and url):
        return None

    return RawJob(
        source=RemotiveAdapter.slug,
        external_id=str(job_id),
        title=str(title),
        company=str(company),
        url=str(url),
        description=str(entry.get("description") or ""),
        # Non è la sede dell'azienda ma il vincolo geografico del candidato: è
        # quello che serve per capire se puoi candidarti.
        location=str(entry.get("candidate_required_location") or "") or None,
        is_remote=True,
        posted_at=parse_iso(entry.get("publication_date")),
        # Testo libero e spesso vuoto: "$50k - $70k", "competitive". Lo interpreta
        # il parser della retribuzione, che sa anche dire "non dichiarata".
        salary_text=str(entry.get("salary") or "") or None,
        contract_hint=str(entry.get("job_type") or "") or None,
        raw=entry,
    )
