"""Stadio 0 dell'imbuto: gli scarti che non richiedono di leggere l'annuncio.

Ogni annuncio scartato qui è una chiamata LLM risparmiata allo Stadio 2. Su un
raccolto di centocinquanta annunci il filtro ne toglie più della metà, e sono
proprio quelli su cui un punteggio sarebbe stato tempo perso: ruoli senior per
chi ha due anni, annunci in una lingua che non parli, paesi dove servirebbe un
visto.

**Perché i predicati stanno in Python e non in una ``WHERE``.** La coda della
query sarebbe più elegante, ma una riga assente da un result set non dice
*perché* è assente, e ``match.filtered_reason`` è una colonna che abbiamo
promesso di riempire: senza, l'unico modo di capire perché un annuncio buono non
compare in dashboard sarebbe rieseguire i filtri a mano uno per uno. La SQL fa
quello che sa fare meglio — restringere a ciò che è attivo e non già deciso — e
i predicati con motivazione girano su qualche centinaio di righe già in memoria.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Job, Match
from ..models.enums import MatchStatus, WorkMode
from .criteria import MatchCriteria
from .text import normalize_company

#: Stati che rappresentano una decisione già presa da Filippo. Rivalutarli
#: significherebbe riproporgli ogni giorno ciò che ha già scartato.
DECIDED_STATUSES = (MatchStatus.HIDDEN, MatchStatus.APPLIED)


@dataclass(frozen=True)
class Rejection:
    """Un annuncio scartato e il motivo, in forma leggibile e in forma contabile."""

    job: Job
    #: Slug stabile del tipo di scarto, per i conteggi: ``"lingua"``, ``"livello"``.
    kind: str
    detail: str

    @property
    def reason(self) -> str:
        """Testo per ``match.filtered_reason``, tenuto entro la colonna."""
        return f"{self.kind}: {self.detail}"[:200]


@dataclass
class FilterResult:
    passed: list[Job] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def counts(self) -> Counter[str]:
        return Counter(r.kind for r in self.rejected)

    @property
    def examined(self) -> int:
        return len(self.passed) + len(self.rejected)


def candidates(session: Session, *, rescore: bool = False, limit: int | None = None) -> list[Job]:
    """Gli annunci che meritano di essere guardati oggi.

    Esclude in SQL solo ciò che è oggettivo: annunci non più attivi, annunci su
    cui Filippo ha già deciso, e — a meno di ``rescore`` — quelli già valutati
    fino in fondo, che non cambierebbero punteggio senza che sia cambiato nulla.
    """
    decisi = select(Match.job_id).where(Match.status.in_(DECIDED_STATUSES))
    stmt = select(Job).where(Job.is_active.is_(True), Job.id.not_in(decisi))

    if not rescore:
        valutati = select(Match.job_id).where(Match.reached_stage >= 2)
        stmt = stmt.where(Job.id.not_in(valutati))

    # I più recenti per primi: quando c'è un tetto, è meglio spenderlo su annunci
    # ancora aperti. ``posted_at`` è nullo su alcune fonti, quindi si ordina anche
    # per data di primo avvistamento.
    stmt = stmt.order_by(Job.posted_at.desc().nullslast(), Job.first_seen_at.desc())
    if limit:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


def apply_filters(
    jobs: list[Job], criteria: MatchCriteria, *, today: dt.datetime | None = None
) -> FilterResult:
    """Applica i filtri duri, conservando il motivo di ogni scarto."""
    adesso = today or dt.datetime.now(dt.UTC)
    risultato = FilterResult()

    for job in jobs:
        scarto = _reject(job, criteria, adesso)
        if scarto is None:
            risultato.passed.append(job)
        else:
            risultato.rejected.append(scarto)
    return risultato


def _reject(job: Job, c: MatchCriteria, adesso: dt.datetime) -> Rejection | None:
    """Il primo motivo di scarto, o ``None`` se l'annuncio passa.

    L'ordine conta: si riporta il motivo più informativo per primo. Sapere che
    un'azienda è in blocklist è più utile che sapere che quel suo annuncio era
    anche troppo vecchio.
    """
    if normalize_company(job.company) in c.blocked_companies:
        return Rejection(job, "azienda", f"{job.company} è in blocklist")

    if job.lang and c.languages and job.lang.lower() not in c.languages:
        return Rejection(
            job, "lingua", f"annuncio in {job.lang}, lingue dichiarate: nessuna corrispondenza"
        )

    if not c.accepts_seniority(job.seniority):
        return Rejection(
            job,
            "livello",
            f"{job.seniority.value} contro {c.seniority.value} (+/-{c.seniority_tolerance})",
        )

    if motivo := _location_reject(job, c):
        return motivo

    if job.contract_type in c.excluded_contract_types:
        return Rejection(job, "contratto", job.contract_type.value)

    if job.work_mode in c.excluded_work_modes:
        return Rejection(job, "modalità", job.work_mode.value)

    if job.posted_at and c.max_age_days:
        giorni = (adesso - job.posted_at).days
        if giorni > c.max_age_days:
            return Rejection(job, "età", f"pubblicato {giorni} giorni fa")

    # Solo su una RAL **dichiarata**: una stima non basta a scartare un annuncio,
    # e il silenzio non è una cifra bassa.
    if (
        c.min_salary_eur_year
        and job.salary_is_stated
        and job.salary_eur_year_max
        and job.salary_eur_year_max < c.min_salary_eur_year
    ):
        return Rejection(
            job, "retribuzione", f"fino a {job.salary_eur_year_max} EUR/anno dichiarati"
        )

    return None


def _location_reject(job: Job, c: MatchCriteria) -> Rejection | None:
    """Mercato e diritto al lavoro, che sono due domande diverse.

    *Mercato* è dove Filippo vuole lavorare; *autorizzazione* è dove può, senza
    che l'azienda debba sponsorizzarlo. Un annuncio a Londra fallisce il secondo
    e non il primo, uno a Bangalore fallisce entrambi.

    Un annuncio remoto salta il controllo sul mercato — è il motivo per cui lo si
    guarda — ma **non** quello sull'autorizzazione: un remote da azienda
    statunitense chiede quasi sempre di poter lavorare negli Stati Uniti, e
    scoprirlo alla domanda del form è tardi.
    """
    paese = (job.country or "").upper()
    if not paese:
        return None  # il silenzio della fonte non è un rifiuto

    remoto = job.work_mode is WorkMode.REMOTE
    if c.countries and paese not in c.countries and not (remoto and c.remote_ignores_country):
        return Rejection(job, "paese", f"{paese} è fuori dai mercati scelti")

    if c.authorized_countries and paese not in c.authorized_countries:
        return Rejection(job, "sponsorship", f"servirebbe autorizzazione al lavoro in {paese}")

    return None
