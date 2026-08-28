"""Stadio 1: ordina i superstiti dello Stadio 0 senza spendere un centesimo.

Combina due segnali che sbagliano in modo diverso — la similarità semantica
dell'embedding e la corrispondenza lessicale di BM25 — e ne tiene i primi
quaranta per la rubrica LLM. È il punto in cui l'imbuto si stringe davvero:
tutto quello che sta a monte è gratis, tutto quello che sta a valle costa una
chiamata per annuncio.

La formula è ``0.6 * spread(coseno) + 0.4 * spread(bm25)``. Entrambi i termini
passano da :func:`~jobboard.ai.embeddings.spread`, che riscala **dentro il
lotto**: senza, il coseno — che su questo modello vive schiacciato fra 0.79 e
0.92 — peserebbe il 60% sulla carta e quasi nulla nei fatti, e BM25, che non ha
un massimo, peserebbe tutto il resto.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from sqlalchemy.orm import Session

from ..ai.embeddings import Embedder, Vector, cosine, from_bytes, spread, to_bytes
from ..models import Job
from ..schemas import MasterProfile
from .bm25 import Bm25

log = logging.getLogger(__name__)

#: Quanto pesa la similarità semantica rispetto alla corrispondenza esatta.
#: Il rapporto viene dal piano e va tarato su dati etichettati
#: (``scripts/calibrate.py``), non a intuito.
SEMANTIC_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4

#: Quante volte il titolo viene ripetuto nel testo dato a BM25. Un "Java" nel
#: titolo dice molto più di un "Java" nell'elenco dei requisiti graditi, e BM25
#: da solo non conosce la struttura del documento: ripetere il campo è il modo
#: classico di dargli un peso senza cambiare la formula.
TITLE_BOOST = 3

#: Tetto ai caratteri della descrizione passati all'embedder. Il modello tronca
#: comunque a 512 token: questo evita solo di far tokenizzare diecimila
#: caratteri per buttarne novemila. La coda è la parte sacrificabile — benefit,
#: informativa privacy e dichiarazioni EEO stanno sempre in fondo.
_MAX_DESCRIPTION_CHARS = 4000

#: Le competenze del profilo pesano più delle famiglie di ruolo: sono il segnale
#: che distingue due annunci per lo stesso ruolo con stack diversi.
_SKILL_WEIGHT = 1.0
_FAMILY_WEIGHT = 0.6


@dataclass(frozen=True)
class Ranked:
    """Un annuncio con i punteggi dello Stadio 1."""

    job: Job
    semantic: float
    keyword: float
    hybrid: float


def job_embedding_text(job: Job) -> str:
    """Il testo di un annuncio per l'embedding.

    L'ordine non è estetico: il modello legge 512 token e poi smette, quindi
    quello che conta di più va davanti. Titolo, azienda e luogo occupano una
    riga e contengono la metà dell'informazione utile; la descrizione riempie il
    resto e viene tagliata dalla coda, dove stanno le parti intercambiabili.
    """
    testa = [job.title]
    if job.company:
        testa.append(f"presso {job.company}")
    if luogo := ", ".join(p for p in (job.city, job.region, job.country) if p):
        testa.append(luogo)
    if job.work_mode.value != "unknown":
        testa.append(job.work_mode.value)
    if job.job_family:
        testa.append(job.job_family)

    return " · ".join(testa) + "\n" + (job.description_clean or "")[:_MAX_DESCRIPTION_CHARS]


def bm25_text(job: Job) -> str:
    """Il testo di un annuncio per BM25, con il titolo pesato."""
    titolo = " ".join([job.title] * TITLE_BOOST)
    return f"{titolo}\n{job.job_family or ''}\n{job.description_clean or ''}"


def profile_terms(profile: MasterProfile) -> tuple[list[str], list[float]]:
    """I termini di ricerca del profilo, con il loro peso.

    Sono le competenze dichiarate e le tecnologie usate davvero nelle
    esperienze, non le parole del summary: un aggettivo nel riassunto non è una
    competenza, e includerlo darebbe punteggio agli annunci più prolissi.
    """
    termini: dict[str, float] = {}

    def aggiungi(valore: str, peso: float) -> None:
        chiave = valore.strip().lower()
        if len(chiave) < 2:
            return
        termini[chiave] = max(termini.get(chiave, 0.0), peso)

    for skill in profile.skills.hard:
        aggiungi(skill, _SKILL_WEIGHT)
    for esperienza in profile.experiences:
        for tech in esperienza.tech:
            aggiungi(tech, _SKILL_WEIGHT)
        aggiungi(esperienza.role, _FAMILY_WEIGHT)
        for bullet in esperienza.bullets:
            for skill in bullet.skills:
                aggiungi(skill, _SKILL_WEIGHT)
    for progetto in profile.projects:
        for tech in progetto.tech:
            # Un progetto personale dimostra meno di un anno di lavoro: stesso
            # termine, metà del peso.
            aggiungi(tech, _SKILL_WEIGHT / 2)
    if profile.headline:
        aggiungi(profile.headline, _FAMILY_WEIGHT)

    voci = sorted(termini.items())
    return [t for t, _ in voci], [p for _, p in voci]


def ensure_embeddings(
    session: Session, jobs: Sequence[Job], embedder: Embedder, *, batch_size: int = 32
) -> int:
    """Calcola e salva gli embedding mancanti o prodotti da un altro modello.

    Il confronto fra vettori di modelli diversi non dà errore: dà numeri, e
    numeri plausibili. Per questo il nome del modello viaggia in colonna accanto
    al vettore e un cambio di ``EMBEDDING_MODEL`` invalida tutto il pregresso.
    """
    da_fare = [j for j in jobs if j.embedding is None or j.embedding_model != embedder.model_name]
    if not da_fare:
        return 0

    log.info("calcolo %d embedding con %s", len(da_fare), embedder.model_name)
    for inizio in range(0, len(da_fare), batch_size):
        lotto = da_fare[inizio : inizio + batch_size]
        vettori = embedder.embed_jobs([job_embedding_text(j) for j in lotto])
        for job, vettore in zip(lotto, vettori, strict=True):
            job.embedding = to_bytes(vettore)
            job.embedding_model = embedder.model_name
        session.flush()

    return len(da_fare)


def rank(
    jobs: Sequence[Job],
    profile: MasterProfile,
    profile_vector: Vector,
    *,
    semantic_weight: float = SEMANTIC_WEIGHT,
    keyword_weight: float = KEYWORD_WEIGHT,
) -> list[Ranked]:
    """Ordina gli annunci per punteggio ibrido, dal più promettente.

    Gli annunci senza embedding vengono saltati invece di ricevere zero: uno zero
    li manderebbe in fondo alla classifica come se fossero stati valutati e
    bocciati. Chiamare prima :func:`ensure_embeddings` è responsabilità del
    chiamante, che è l'unico a sapere se può permettersi di caricare il modello.
    """
    valutabili = [j for j in jobs if j.embedding]
    if not valutabili:
        return []
    if saltati := len(jobs) - len(valutabili):
        log.warning("%d annunci senza embedding, esclusi dallo Stadio 1", saltati)

    matrice = np.vstack([from_bytes(j.embedding or b"") for j in valutabili])
    coseni = cosine(profile_vector, matrice)

    termini, pesi = profile_terms(profile)
    indice = Bm25.build([bm25_text(j) for j in valutabili])
    lessicali = indice.score(termini, pesi)

    ibridi = semantic_weight * spread(coseni) + keyword_weight * spread(lessicali)

    risultati = [
        Ranked(job=job, semantic=float(c), keyword=float(k), hybrid=float(h))
        for job, c, k, h in zip(valutabili, coseni, lessicali, ibridi, strict=True)
    ]
    risultati.sort(key=lambda r: r.hybrid, reverse=True)
    return risultati


def normalized_keyword_scores(ranked: Sequence[Ranked]) -> NDArray[np.float32]:
    """I punteggi BM25 riscalati, per mostrarli in dashboard senza confondere.

    Il valore grezzo di BM25 non ha un massimo e non significa niente da solo:
    quello che si può mostrare è la posizione relativa dentro il lotto.
    """
    if not ranked:
        return np.empty(0, dtype=np.float32)
    return spread(np.array([r.keyword for r in ranked], dtype=np.float32))
