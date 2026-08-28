"""Riconoscimento degli annunci ripetuti.

Lo stesso posto di lavoro compare su Adzuna, su JSearch e sulla board Greenhouse
dell'azienda. Sono tre righe della stessa cosa: mostrarle tutte e tre in
dashboard rende la tabella inutile, e candidarsi tre volte è peggio.

La dedup è a due livelli, perché i due problemi sono diversi:

1. **Chiave canonica** — azienda + ruolo + città, normalizzati. Cattura i casi
   in cui il titolo è identico. Costa una lettura indicizzata.
2. **SimHash della descrizione** — cattura i casi in cui il titolo differisce
   ("Backend Developer" contro "Backend Developer (Java)") ma il testo è lo
   stesso annuncio. Serve perché la chiave canonica, da sola, è troppo rigida.

Quando due annunci sono la stessa cosa, si tiene **la versione migliore**: quella
con il link ATS diretto, perché è l'unica che abilita la candidatura automatica.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from ..models.enums import TIER_A_ATS, AtsType
from .normalize import NormalizedJob
from .text import hamming

#: Bit di differenza sotto i quali due descrizioni sono lo stesso annuncio.
#: Su 64 bit, 10 corrisponde all'85% di somiglianza. Due testi indipendenti ne
#: differiscono di una trentina: la soglia non è delicata.
MAX_HAMMING_DISTANCE = 10

#: Sotto questa lunghezza il SimHash non è affidabile: un estratto di due righe
#: da Jooble produce impronte casuali. Per quegli annunci vale solo la chiave.
_MIN_CHARS_FOR_SIMHASH = 300


@dataclass
class JobGroup:
    """Un annuncio e tutte le sue apparizioni."""

    canonical: NormalizedJob
    variants: list[NormalizedJob]

    @property
    def sources(self) -> list[str]:
        return sorted({v.source for v in self.variants})


def is_same(a: NormalizedJob, b: NormalizedJob) -> bool:
    """``True`` se i due annunci sono lo stesso posto di lavoro."""
    if a.canonical_key and a.canonical_key == b.canonical_key:
        return True
    return _same_by_content(a, b)


def _same_by_content(a: NormalizedJob, b: NormalizedJob) -> bool:
    """Confronto sul testo, ma solo fra annunci della stessa azienda.

    Il vincolo sull'azienda non è un'ottimizzazione: due offerte di aziende
    diverse possono avere descrizioni quasi identiche — le agenzie ripubblicano
    lo stesso testo per clienti diversi — e unirle nasconderebbe un annuncio
    vero.
    """
    if not a.company_normalized or a.company_normalized != b.company_normalized:
        return False
    if min(len(a.description_clean), len(b.description_clean)) < _MIN_CHARS_FOR_SIMHASH:
        return False
    return hamming(a.simhash, b.simhash) <= MAX_HAMMING_DISTANCE


def group(jobs: Iterable[NormalizedJob]) -> list[JobGroup]:
    """Raggruppa gli annunci di un lotto, unendo i duplicati."""
    gruppi: list[JobGroup] = []
    per_chiave: dict[str, JobGroup] = {}

    for job in jobs:
        esistente = per_chiave.get(job.canonical_key)
        if esistente is None:
            # La chiave non basta: si cerca anche per contenuto fra i gruppi
            # della stessa azienda, dove i titoli potrebbero differire.
            esistente = next(
                (g for g in gruppi if _same_by_content(g.canonical, job)),
                None,
            )
        if esistente is None:
            nuovo = JobGroup(canonical=job, variants=[job])
            gruppi.append(nuovo)
            per_chiave[job.canonical_key] = nuovo
            continue

        esistente.variants.append(job)
        esistente.canonical = merge(esistente.variants)
        per_chiave.setdefault(job.canonical_key, esistente)

    return gruppi


def merge(variants: Sequence[NormalizedJob]) -> NormalizedJob:
    """Compone la versione migliore a partire da tutte le apparizioni.

    Non si sceglie una variante e si buttano le altre: ognuna può avere il pezzo
    che manca alle altre. L'aggregatore conosce la RAL, la board ATS ha la
    descrizione completa e il link al form vero.
    """
    if len(variants) == 1:
        return variants[0]

    base = max(variants, key=_richness)

    migliore_ats = next(
        (v for v in variants if v.ats_type in TIER_A_ATS),
        next((v for v in variants if v.ats_type is not AtsType.UNKNOWN), None),
    )
    con_ral = next((v for v in variants if v.salary.is_stated), None)
    piu_lunga = max(variants, key=lambda v: len(v.description_clean))
    con_data = [v for v in variants if v.posted_at]

    return replace(
        base,
        description_raw=piu_lunga.description_raw,
        description_clean=piu_lunga.description_clean,
        simhash=piu_lunga.simhash,
        content_hash=piu_lunga.content_hash,
        salary=con_ral.salary if con_ral else base.salary,
        # Il link ATS vince sempre su quello dell'aggregatore: è l'unico che
        # porta al form vero invece che a una pagina di reindirizzamento.
        apply_url=(migliore_ats.apply_url if migliore_ats else None) or base.apply_url,
        ats_type=migliore_ats.ats_type if migliore_ats else base.ats_type,
        ats_board_token=migliore_ats.ats_board_token if migliore_ats else base.ats_board_token,
        ats_job_id=migliore_ats.ats_job_id if migliore_ats else base.ats_job_id,
        url=migliore_ats.url if migliore_ats else base.url,
        # La data più vecchia è quella vera: gli aggregatori usano la data in cui
        # hanno indicizzato l'annuncio, non quella in cui è stato pubblicato.
        posted_at=min((v.posted_at for v in con_data), default=None),  # type: ignore[type-var]
        city=base.city or next((v.city for v in variants if v.city), None),
        country=base.country or next((v.country for v in variants if v.country), None),
    )


def _richness(job: NormalizedJob) -> tuple[int, int, int, int]:
    """Quanto è completa una variante. Decide quale fa da base alla fusione."""
    return (
        2 if job.ats_type in TIER_A_ATS else 1 if job.ats_type is not AtsType.UNKNOWN else 0,
        1 if job.salary.is_stated else 0,
        1 if job.city else 0,
        len(job.description_clean),
    )
