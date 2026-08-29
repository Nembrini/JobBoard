"""Punteggio di compatibilita' fra il profilo e un annuncio."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, default_sql, enum_column
from .enums import MatchStatus
from .job import Job


class Match(Base, TimestampMixin):
    """Un annuncio valutato contro il profilo.

    Conserva i punteggi di **tutti** gli stadi dell'imbuto, non solo quello finale:
    servono per calibrare i pesi a posteriori su dati reali (``scripts/calibrate.py``)
    e per capire perche' un annuncio buono e' stato scartato presto.
    """

    __tablename__ = "match"
    __table_args__ = (
        Index("ix_match_score_status", "score", "status"),
        Index("ix_match_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # --- Stadio 1: semantico, costo zero ---
    semantic_score: Mapped[float | None] = mapped_column(Float)  # cosine, 0..1
    keyword_score: Mapped[float | None] = mapped_column(Float)  # BM25 normalizzato, 0..1
    hybrid_score: Mapped[float | None] = mapped_column(Float)  # 0.6*sem + 0.4*kw

    # --- Stadio 2: rubrica LLM ---
    #: Punteggio finale 0-100, quello mostrato in dashboard.
    score: Mapped[int | None] = mapped_column(SmallInteger)
    #: Punteggi per singola voce della rubrica: must_have_coverage, nice_to_have,
    #: seniority_fit, domain_fit, location_fit, salary_fit.
    subscores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    #: Requisiti richiesti che il profilo non copre. Evidenziati nel drawer di
    #: dettaglio e usati dal generatore di CV per non sovrastimare la copertura.
    gaps: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default=default_sql("'{}'"))

    scored_with: Mapped[str | None] = mapped_column(String(128))
    scored_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    #: A quale stadio dell'imbuto l'annuncio si e' fermato (0, 1 o 2). Un annuncio
    #: fermo allo stadio 0 non ha ``score``: e' stato escluso da un hard filter.
    reached_stage: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=default_sql("0"))
    #: Motivo dell'esclusione, quando ``reached_stage`` e' 0.
    filtered_reason: Mapped[str | None] = mapped_column(String(200))

    status: Mapped[MatchStatus] = enum_column(
        MatchStatus, nullable=False, default=MatchStatus.NEW, index=True
    )

    job: Mapped[Job] = relationship()
