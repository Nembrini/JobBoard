"""Persistenza del pool di informazioni applicante.

Singleton con ``id = 1``, come ``store.profile``: si legge la riga e la si
riscrive per intero, mai un ``INSERT`` alla cieca.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import ApplicantInfo
from ..schemas import ApplicantInfoBank

_SINGLETON_ID = 1


@dataclass(frozen=True)
class StoredApplicantInfo:
    bank: ApplicantInfoBank
    updated_at: dt.datetime


def load_applicant_info(session: Session) -> StoredApplicantInfo | None:
    row = session.get(ApplicantInfo, _SINGLETON_ID)
    if row is None:
        return None
    return StoredApplicantInfo(
        bank=ApplicantInfoBank.model_validate({"items": row.items}),
        updated_at=row.updated_at,
    )


def save_applicant_info(session: Session, bank: ApplicantInfoBank) -> StoredApplicantInfo:
    row = session.get(ApplicantInfo, _SINGLETON_ID)
    if row is None:
        row = ApplicantInfo(id=_SINGLETON_ID)
        session.add(row)

    row.items = [voce.model_dump(mode="json") for voce in bank.items]

    session.flush()
    return StoredApplicantInfo(bank=bank, updated_at=row.updated_at)
