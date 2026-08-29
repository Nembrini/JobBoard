"""Persistenza del profilo e delle risposte ai form.

Entrambe le tabelle sono singleton con ``id = 1``: qui non si fa mai ``INSERT``
alla cieca, si legge la riga e la si aggiorna. Il ``CHECK (id = 1)`` sul database
e' la rete di sicurezza, non il meccanismo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..ai.embeddings import Vector, from_bytes, to_bytes
from ..models import CandidateProfile, Profile
from ..models.base import utcnow
from ..schemas import CandidateAnswers, MasterProfile

#: Chiave della riga singleton, in entrambe le tabelle.
_SINGLETON_ID = 1


@dataclass(frozen=True)
class StoredProfile:
    """Il profilo come sta sul database, gia' validato."""

    profile: MasterProfile
    raw_text: str
    source_file_name: str
    reviewed: bool
    reviewed_at: dt.datetime | None
    embedding: Vector | None
    embedding_model: str | None
    updated_at: dt.datetime

    def embedding_is_current(self, model_name: str) -> bool:
        """``False`` anche quando l'embedding esiste ma viene da un altro modello.

        Confrontare vettori prodotti da modelli diversi non da' errore: da'
        numeri. Vanno rigenerati tutti insieme o nessuno.
        """
        return self.embedding is not None and self.embedding_model == model_name


@dataclass(frozen=True)
class StoredCandidate:
    answers: CandidateAnswers
    updated_at: dt.datetime


# --- profilo -----------------------------------------------------------------


def save_profile(
    session: Session,
    *,
    profile: MasterProfile,
    embedding: Vector | None,
    embedding_model: str | None,
    reviewed: bool,
    raw_text: str | None = None,
    source_file_name: str | None = None,
    source_storage_path: str | None = None,
) -> StoredProfile:
    """Scrive il profilo, creando la riga se non c'e'.

    ``raw_text`` e ``source_file_name`` sono opzionali perche' ricaricando un JSON
    corretto a mano non si ripassa dal PDF: in quel caso si conservano i valori
    gia' presenti. Se pero' non c'e' ancora nessuna riga, mancano davvero e il
    salvataggio si ferma invece di scrivere stringhe vuote.
    """
    row = session.get(Profile, _SINGLETON_ID)
    if row is None:
        if raw_text is None or source_file_name is None:
            raise ValueError(
                "nessun profilo sul database: il primo salvataggio deve partire dal "
                "file del CV (jobboard profile import), non da un JSON"
            )
        row = Profile(id=_SINGLETON_ID)
        session.add(row)

    row.master_profile = profile.model_dump(mode="json")
    if raw_text is not None:
        row.raw_text = raw_text
    if source_file_name is not None:
        row.source_file_name = source_file_name
    # Solo quando arriva: un JSON ricaricato a mano non ripassa dal file, e
    # azzerare il percorso qui vorrebbe dire perdere il link per riscaricare
    # l'originale a ogni correzione.
    if source_storage_path is not None:
        row.source_storage_path = source_storage_path

    row.embedding = to_bytes(embedding) if embedding is not None else None
    row.embedding_model = embedding_model if embedding is not None else None
    row.embedding_dim = int(embedding.shape[-1]) if embedding is not None else None

    # ``reviewed_at`` segue ``reviewed``: senza questo, una revisione revocata
    # lascerebbe una data che sembra dire il contrario.
    if reviewed and not row.reviewed:
        row.reviewed_at = utcnow()
    elif not reviewed:
        row.reviewed_at = None
    row.reviewed = reviewed

    session.flush()
    return _to_stored(row)


def load_profile(session: Session) -> StoredProfile | None:
    row = session.get(Profile, _SINGLETON_ID)
    return _to_stored(row) if row else None


def mark_reviewed(session: Session, reviewed: bool = True) -> StoredProfile:
    """Segna il profilo come rivisto a mano, senza toccare il contenuto.

    E' il flag che la pipeline di matching controlla prima di partire: un profilo
    estratto male produrrebbe punteggi sbagliati su ogni annuncio, per giorni,
    senza che nulla segnali il problema.
    """
    row = session.get(Profile, _SINGLETON_ID)
    if row is None:
        raise ValueError("nessun profilo da segnare: esegui prima 'jobboard profile import'")
    if reviewed and not row.reviewed:
        row.reviewed_at = utcnow()
    elif not reviewed:
        row.reviewed_at = None
    row.reviewed = reviewed
    session.flush()
    return _to_stored(row)


def _to_stored(row: Profile) -> StoredProfile:
    return StoredProfile(
        profile=MasterProfile.model_validate(row.master_profile),
        raw_text=row.raw_text,
        source_file_name=row.source_file_name,
        reviewed=row.reviewed,
        reviewed_at=row.reviewed_at,
        embedding=from_bytes(row.embedding) if row.embedding else None,
        embedding_model=row.embedding_model,
        updated_at=row.updated_at,
    )


# --- risposte ai form --------------------------------------------------------


def save_candidate(session: Session, answers: CandidateAnswers) -> StoredCandidate:
    row = session.get(CandidateProfile, _SINGLETON_ID)
    if row is None:
        row = CandidateProfile(id=_SINGLETON_ID)
        session.add(row)

    row.full_name = answers.full_name
    row.email = answers.email
    row.phone = answers.phone
    row.city = answers.city
    row.country = answers.country
    row.linkedin_url = answers.linkedin_url
    row.github_url = answers.github_url
    row.portfolio_url = answers.portfolio_url
    row.work_authorization = dict(answers.work_authorization)
    row.willing_to_relocate = answers.willing_to_relocate
    row.notice_period_days = answers.notice_period_days
    row.salary_expectation_min = answers.salary_expectation_min
    row.salary_expectation_max = answers.salary_expectation_max
    row.salary_currency = answers.salary_currency
    row.languages = dict(answers.languages)
    row.ats_answers = answers.ats_answers.model_dump(mode="json")

    session.flush()
    return StoredCandidate(answers=answers, updated_at=row.updated_at)


def load_candidate(session: Session) -> StoredCandidate | None:
    row = session.get(CandidateProfile, _SINGLETON_ID)
    if row is None:
        return None
    answers = CandidateAnswers.model_validate(
        {
            "full_name": row.full_name,
            "email": row.email,
            "phone": row.phone,
            "city": row.city,
            "country": row.country,
            "linkedin_url": row.linkedin_url,
            "github_url": row.github_url,
            "portfolio_url": row.portfolio_url,
            "work_authorization": row.work_authorization,
            "willing_to_relocate": row.willing_to_relocate,
            "notice_period_days": row.notice_period_days,
            "salary_expectation_min": row.salary_expectation_min,
            "salary_expectation_max": row.salary_expectation_max,
            "salary_currency": row.salary_currency,
            "languages": row.languages,
            "ats_answers": row.ats_answers,
        }
    )
    return StoredCandidate(answers=answers, updated_at=row.updated_at)
