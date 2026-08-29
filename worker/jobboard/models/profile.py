"""Profilo del candidato.

Due tabelle distinte perche' cambiano per motivi diversi:

* :class:`Profile` e' il **contenuto** del CV (esperienze, skill) — cambia quando
  Filippo carica un CV nuovo, e da esso derivano matching e CV generati.
* :class:`CandidateProfile` sono i **dati per compilare i form** (telefono, work
  authorization, preavviso) — cambiano raramente e non influenzano il matching.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, default_sql


class Profile(Base, TimestampMixin):
    """Singleton: esiste una sola riga, con ``id = 1``.

    Il vincolo e' esplicito perche' l'intero sistema assume un solo candidato: senza
    di esso un secondo insert accidentale renderebbe ambiguo ogni matching.
    """

    __tablename__ = "profile"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    #: MasterProfile validato: anagrafica, esperienze, skill, formazione, lingue,
    #: progetti, certificazioni. Lo schema Pydantic vive in ``jobboard.schemas``.
    master_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #: Testo grezzo estratto dal PDF/DOCX, conservato per poter ri-parsare senza
    #: richiedere di ricaricare il file.
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_storage_path: Mapped[str | None] = mapped_column(String(512))

    #: Embedding del profilo, float32 little-endian serializzato con ``numpy.tobytes``.
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    embedding_dim: Mapped[int | None] = mapped_column(Integer)

    #: ``True`` solo dopo che Filippo ha rivisto a mano il JSON estratto dall'LLM.
    #: La pipeline di matching rifiuta di partire finche' e' ``False``: un profilo
    #: estratto male avvelenerebbe ogni punteggio a valle.
    reviewed: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=default_sql("false")
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateProfile(Base, TimestampMixin):
    """Risposte standard ai form di candidatura. Anch'esso singleton."""

    __tablename__ = "candidate_profile"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))

    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2

    linkedin_url: Mapped[str | None] = mapped_column(String(512))
    github_url: Mapped[str | None] = mapped_column(String(512))
    portfolio_url: Mapped[str | None] = mapped_column(String(512))

    #: Diritto al lavoro per paese, es. ``{"IT": "citizen", "DE": "eu_eligible",
    #: "US": "requires_sponsorship"}``. Alimenta un hard filter dello Stadio 0:
    #: candidarsi dove serve sponsorship e' quasi sempre tempo sprecato.
    work_authorization: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=default_sql("'{}'::jsonb")
    )

    willing_to_relocate: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=default_sql("false")
    )
    notice_period_days: Mapped[int | None] = mapped_column(Integer)

    salary_expectation_min: Mapped[int | None] = mapped_column(Integer)
    salary_expectation_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="EUR", server_default=default_sql("'EUR'")
    )

    #: Lingue parlate con livello CEFR, es. ``{"it": "native", "en": "C1"}``.
    languages: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=default_sql("'{}'::jsonb")
    )

    #: Risposte alle domande ricorrenti dei form ATS (EEO, disponibilita' a
    #: trasferte, come hai saputo di noi...). Chiave = domanda normalizzata.
    ats_answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=default_sql("'{}'::jsonb")
    )
