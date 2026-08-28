"""Board ATS delle singole aziende: Greenhouse, Lever, Ashby, Workable.

Sono le fonti con i dati migliori dell'intero sistema, per tre motivi:

1. **La descrizione è completa**, non un estratto da aggregatore.
2. **Il link è quello del form vero**, non un reindirizzamento: è la condizione
   che abilita la candidatura automatica di Tier A (Fase 7).
3. **Nessuna chiave API**: gli endpoint delle job board sono pubblici perché
   servono a far girare il sito di carriere dell'azienda.

Il prezzo è che vanno seguite azienda per azienda: la configurazione di ogni
adapter contiene l'elenco dei *board token*, cioè il nome dell'azienda nell'URL
della sua pagina lavora-con-noi. Una board che sparisce non deve fermare le
altre, quindi ogni token è isolato nel suo try.
"""

from __future__ import annotations

import html
import logging
from abc import abstractmethod
from collections.abc import Iterator
from typing import Any, ClassVar

from ..models.enums import AtsType
from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    SourceError,
    from_epoch_ms,
    parse_iso,
    register,
    title_matches,
)

log = logging.getLogger(__name__)


class AtsBoardAdapter(SourceAdapter):
    """Base comune ai quattro ATS. Cambia l'endpoint, non la struttura."""

    ats_type: ClassVar[AtsType]
    default_rate_limit_per_min = 30

    def fetch(self, query: SearchQuery, http: HttpClient) -> Iterator[RawJob]:
        tokens = [str(t) for t in (self.config.get("boards") or [])]
        if not tokens:
            log.info("%s: nessuna board configurata, niente da fare", self.slug)
            return

        wanted = tuple(k.lower() for k in query.keywords)
        for token in tokens:
            try:
                for job in self.fetch_board(token, http):
                    if title_matches(job.title, wanted):
                        yield job
            except SourceError as exc:
                # Un'azienda che chiude la board o cambia nome non deve far
                # fallire la run: le altre board hanno ancora annunci validi.
                log.warning("%s/%s non raggiungibile: %s", self.slug, token, exc)

    @abstractmethod
    def fetch_board(self, token: str, http: HttpClient) -> Iterator[RawJob]:
        """Annunci di una singola board."""

    def company_name(self, token: str, fallback: str | None = None) -> str:
        """Nome leggibile dell'azienda.

        Gli ATS espongono il token, non il nome: ``acme-inc`` invece di "Acme
        Inc.". La mappa ``board_names`` in configurazione permette di correggerlo
        dove conta, cioè sulla riga della tabella e dentro il CV generato.
        """
        names = self.config.get("board_names") or {}
        return str(names.get(token) or fallback or token.replace("-", " ").title())


# --- Greenhouse ---------------------------------------------------------------


@register
class GreenhouseAdapter(AtsBoardAdapter):
    slug = "greenhouse"
    display_name = "Greenhouse"
    ats_type = AtsType.GREENHOUSE

    def fetch_board(self, token: str, http: HttpClient) -> Iterator[RawJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        payload = http.get_json(url, params={"content": "true"})

        for entry in payload.get("jobs") or []:
            job_id = entry.get("id")
            title = entry.get("title")
            absolute_url = entry.get("absolute_url")
            if not (job_id and title and absolute_url):
                continue

            yield RawJob(
                source=self.slug,
                external_id=f"{token}:{job_id}",
                title=str(title),
                company=self.company_name(token, entry.get("company_name")),
                url=str(absolute_url),
                # Greenhouse restituisce l'HTML con le entità codificate: senza
                # unescape la descrizione è un muro di &lt;p&gt;.
                description=html.unescape(str(entry.get("content") or "")),
                location=(entry.get("location") or {}).get("name"),
                posted_at=parse_iso(entry.get("first_published") or entry.get("updated_at")),
                apply_url=str(absolute_url),
                ats_type=self.ats_type,
                ats_board_token=token,
                ats_job_id=str(job_id),
                raw=entry,
            )


# --- Lever --------------------------------------------------------------------


@register
class LeverAdapter(AtsBoardAdapter):
    slug = "lever"
    display_name = "Lever"
    ats_type = AtsType.LEVER

    def fetch_board(self, token: str, http: HttpClient) -> Iterator[RawJob]:
        payload = http.get_json(
            f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}
        )
        if not isinstance(payload, list):
            raise SourceError(f"lever/{token}: risposta inattesa")

        for entry in payload:
            job_id = entry.get("id")
            title = entry.get("text")
            hosted = entry.get("hostedUrl")
            if not (job_id and title and hosted):
                continue

            categories = entry.get("categories") or {}
            yield RawJob(
                source=self.slug,
                external_id=f"{token}:{job_id}",
                title=str(title),
                company=self.company_name(token),
                url=str(hosted),
                description=_lever_description(entry),
                location=categories.get("location"),
                country=str(entry.get("country") or "").upper()[:2] or None,
                is_remote=_lever_remote(entry),
                posted_at=from_epoch_ms(entry.get("createdAt")),
                contract_hint=categories.get("commitment"),
                apply_url=str(entry.get("applyUrl") or hosted),
                ats_type=self.ats_type,
                ats_board_token=token,
                ats_job_id=str(job_id),
                raw=entry,
            )


def _lever_description(entry: dict[str, Any]) -> str:
    """Ricompone la descrizione, che Lever spezza in tre campi.

    ``description`` è l'introduzione, ``lists`` sono le sezioni a punti — dove
    stanno i requisiti, cioè la parte che conta per il matching — e ``additional``
    le note finali. Prendere solo il primo campo perderebbe proprio i requisiti.
    """
    parti = [str(entry.get("description") or "")]
    for blocco in entry.get("lists") or []:
        titolo = str(blocco.get("text") or "")
        contenuto = str(blocco.get("content") or "")
        parti.append(f"<h3>{titolo}</h3><ul>{contenuto}</ul>" if titolo else contenuto)
    parti.append(str(entry.get("additional") or ""))
    return "\n".join(p for p in parti if p.strip())


def _lever_remote(entry: dict[str, Any]) -> bool | None:
    workplace = str(entry.get("workplaceType") or "").lower()
    if not workplace:
        return None
    return workplace == "remote"


# --- Ashby --------------------------------------------------------------------


@register
class AshbyAdapter(AtsBoardAdapter):
    slug = "ashby"
    display_name = "Ashby"
    ats_type = AtsType.ASHBY

    def fetch_board(self, token: str, http: HttpClient) -> Iterator[RawJob]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        payload = http.get_json(url, params={"includeCompensation": "true"})

        for entry in payload.get("jobs") or []:
            job_id = entry.get("id")
            title = entry.get("title")
            job_url = entry.get("jobUrl")
            if not (job_id and title and job_url):
                continue
            # Ashby restituisce anche gli annunci ritirati: pubblicarli
            # produrrebbe candidature verso posizioni che non esistono più.
            if entry.get("isListed") is False:
                continue

            compensation = entry.get("compensation") or {}
            yield RawJob(
                source=self.slug,
                external_id=f"{token}:{job_id}",
                title=str(title),
                company=self.company_name(token),
                url=str(job_url),
                description=str(
                    entry.get("descriptionHtml") or entry.get("descriptionPlain") or ""
                ),
                location=entry.get("location"),
                is_remote=entry.get("isRemote") if entry.get("isRemote") is not None else None,
                posted_at=parse_iso(entry.get("publishedAt")),
                # Stringa gia' formattata, es. "$211.4K - $290.6K - Offers Equity":
                # la interpreta il parser della retribuzione.
                salary_text=str(compensation.get("compensationTierSummary") or "") or None,
                contract_hint=entry.get("employmentType"),
                apply_url=str(entry.get("applyUrl") or job_url),
                ats_type=self.ats_type,
                ats_board_token=token,
                ats_job_id=str(job_id),
                raw=entry,
            )


# --- Workable -----------------------------------------------------------------


@register
class WorkableAdapter(AtsBoardAdapter):
    slug = "workable"
    display_name = "Workable"
    ats_type = AtsType.WORKABLE

    def fetch_board(self, token: str, http: HttpClient) -> Iterator[RawJob]:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{token}"
        payload = http.get_json(url, params={"details": "true"})
        company = self.company_name(token, payload.get("name"))

        for entry in payload.get("jobs") or []:
            shortcode = entry.get("shortcode")
            title = entry.get("title")
            job_url = entry.get("url") or entry.get("shortlink")
            if not (shortcode and title and job_url):
                continue

            locations = entry.get("locations") or []
            country_code = locations[0].get("countryCode") if locations else None

            yield RawJob(
                source=self.slug,
                external_id=f"{token}:{shortcode}",
                title=str(title),
                company=company,
                url=str(job_url),
                description=_workable_description(entry),
                location=", ".join(str(p) for p in (entry.get("city"), entry.get("country")) if p)
                or None,
                country=str(country_code).upper()[:2] if country_code else None,
                is_remote=bool(entry["telecommuting"]) if "telecommuting" in entry else None,
                posted_at=parse_iso(entry.get("published_on") or entry.get("created_at")),
                contract_hint=entry.get("employment_type"),
                # Workable dichiara il livello con parole sue ("Mid-Senior level"),
                # che è più affidabile di dedurlo dal titolo.
                seniority_hint=entry.get("experience"),
                apply_url=str(entry.get("application_url") or job_url),
                ats_type=self.ats_type,
                ats_board_token=token,
                ats_job_id=str(shortcode),
                raw=entry,
            )


def _workable_description(entry: dict[str, Any]) -> str:
    """Workable tiene requisiti e benefit in campi separati dalla descrizione."""
    return "\n".join(
        str(entry.get(campo) or "")
        for campo in ("description", "requirements", "benefits")
        if entry.get(campo)
    )
