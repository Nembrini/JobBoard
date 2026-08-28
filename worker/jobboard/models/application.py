"""Candidature inviate e loro evoluzione nel tempo."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, enum_column
from .enums import ApplicationEventType, ApplicationStatus, ApplicationTier
from .match import Match


class Application(Base, TimestampMixin):
    """Una candidatura a un annuncio.

    Il vincolo di unicita' su ``match_id`` e' il meccanismo di **idempotenza**: la
    stessa offerta non puo' generare due candidature, nemmeno se il bottone viene
    premuto due volte o un task viene ritentato.
    """

    __tablename__ = "application"
    __table_args__ = (Index("ix_application_status_submitted", "status", "submitted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    tier: Mapped[ApplicationTier] = enum_column(ApplicationTier, nullable=False)
    status: Mapped[ApplicationStatus] = enum_column(
        ApplicationStatus, nullable=False, default=ApplicationStatus.DRAFT, index=True
    )

    # --- CV generato ---
    #: Percorso su Supabase Storage: ``resumes/{job_id}/Filippo_Nembrini_Resume.pdf``.
    #: Una cartella per annuncio, cosi' il nome del file resta sempre lo stesso senza
    #: che una candidatura sovrascriva quella precedente.
    cv_storage_path: Mapped[str | None] = mapped_column(String(512))
    cover_letter_storage_path: Mapped[str | None] = mapped_column(String(512))
    #: Output strutturato del generatore: top_keywords, summary, experience, skills.
    #: Serve per il diff in UI e per rigenerare senza ripartire da zero.
    cv_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cv_language: Mapped[str | None] = mapped_column(String(5))
    #: Quante iterazioni di compressione sono servite per stare in una pagina.
    #: Se e' spesso alto, il template o il MasterProfile vanno rivisti.
    cv_fit_iterations: Mapped[int | None] = mapped_column(Integer)

    # --- invio ---
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: ``True`` quando l'invio e' stato simulato senza contattare l'ATS.
    was_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ats_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    #: Screenshot del form Tier B, per poter ricostruire cosa e' stato compilato.
    screenshots: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # --- follow-up ---
    follow_up_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_email_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    match: Mapped[Match] = relationship()
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationEvent.occurred_at",
    )


class ApplicationEvent(Base):
    """Timeline append-only di una candidatura.

    Non si modifica mai una riga esistente: lo storico serve a capire dopo settimane
    perche' una candidatura e' in un certo stato.
    """

    __tablename__ = "application_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )

    event_type: Mapped[ApplicationEventType] = enum_column(ApplicationEventType, nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    #: Dati specifici dell'evento: classificazione email, codice HTTP dell'ATS,
    #: stato precedente e successivo di un cambio di stato.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    application: Mapped[Application] = relationship(back_populates="events")
