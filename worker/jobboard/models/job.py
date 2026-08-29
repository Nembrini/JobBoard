"""Annunci di lavoro: fonti, annuncio canonico, link per fonte, requisiti estratti."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, default_sql, enum_column
from .enums import AtsType, ContractType, SalaryPeriod, Seniority, WorkMode


class Source(Base, TimestampMixin):
    """Una fonte di annunci. Una riga per adapter attivo."""

    __tablename__ = "source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: Chiave dell'adapter nel registry, es. ``"adzuna"``, ``"greenhouse"``.
    adapter: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=default_sql("true"))

    #: Configurazione specifica dell'adapter: paesi, query, board token seguiti.
    #: Non contiene mai chiavi API — quelle stanno in ``.env``.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=default_sql("'{}'::jsonb"))

    #: Tetto di chiamate al minuto. Per JSearch e' il free tier a fare da collo di
    #: bottiglia (~200/mese), gestito a parte con un budget giornaliero.
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default=default_sql("30"))
    daily_call_budget: Mapped[int | None] = mapped_column(Integer)

    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    links: Mapped[list[JobSourceLink]] = relationship(back_populates="source")


class Job(Base, TimestampMixin):
    """Annuncio canonico, deduplicato fra le fonti."""

    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_canonical_key", "canonical_key"),
        Index("ix_job_active_posted", "is_active", "posted_at"),
        Index("ix_job_company_norm", "company_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- identita' ---
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    company_normalized: Mapped[str] = mapped_column(String(300), nullable=False)

    #: ``normalize(company) + normalize(title) + normalize(city)``. Prima chiave di
    #: dedup; in caso di collisione decide il confronto SimHash.
    canonical_key: Mapped[str] = mapped_column(String(600), nullable=False)

    #: SimHash a 64 bit della description pulita. Firmato perche' Postgres non ha
    #: interi a 64 bit senza segno: il confronto e' su distanza di Hamming, quindi
    #: il segno e' irrilevante.
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- luogo e modalita' ---
    location_raw: Mapped[str | None] = mapped_column(String(400))
    city: Mapped[str | None] = mapped_column(String(160))
    region: Mapped[str | None] = mapped_column(String(160))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    work_mode: Mapped[WorkMode] = enum_column(WorkMode, nullable=False, default=WorkMode.UNKNOWN)

    # --- retribuzione ---
    #: ``False`` quando l'annuncio non dichiara nulla. In dashboard si mostra "n.d.":
    #: una stima non va mai presentata come se fosse dichiarata.
    salary_is_stated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=default_sql("false"))
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[SalaryPeriod | None] = enum_column(SalaryPeriod)

    #: RAL annua lorda normalizzata in EUR, per poter ordinare e filtrare fra
    #: annunci che dichiarano orari, mensili o annui in valute diverse.
    salary_eur_year_min: Mapped[int | None] = mapped_column(Integer)
    salary_eur_year_max: Mapped[int | None] = mapped_column(Integer)

    # --- inquadramento ---
    contract_type: Mapped[ContractType] = enum_column(
        ContractType, nullable=False, default=ContractType.UNKNOWN
    )
    seniority: Mapped[Seniority] = enum_column(Seniority, nullable=False, default=Seniority.UNKNOWN)
    #: Famiglia di ruolo normalizzata, es. "Software Developer", "Data Engineer".
    job_family: Mapped[str | None] = mapped_column(String(120))

    # --- contenuto ---
    description_raw: Mapped[str | None] = mapped_column(Text)
    description_clean: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(String(5))

    # --- link e ATS ---
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    #: Vince sempre il link ATS diretto su quello dell'aggregatore: e' l'unico che
    #: abilita l'invio automatico (Tier A).
    apply_url: Mapped[str | None] = mapped_column(String(1024))
    ats_type: Mapped[AtsType] = enum_column(AtsType, nullable=False, default=AtsType.UNKNOWN)
    ats_board_token: Mapped[str | None] = mapped_column(String(200))
    ats_job_id: Mapped[str | None] = mapped_column(String(200))

    # --- ciclo di vita ---
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=default_sql("true"))

    # --- embedding ---
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(128))

    links: Mapped[list[JobSourceLink]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    requirements: Mapped[JobRequirements | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class JobSourceLink(Base):
    """Un annuncio visto da una fonte specifica.

    Lo stesso posto di lavoro compare spesso su Adzuna, JSearch e sulla board ATS
    dell'azienda: un solo :class:`Job`, tre righe qui.
    """

    __tablename__ = "job_source_link"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_source_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), nullable=False)

    #: Identificativo dell'annuncio presso quella fonte.
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Il portale su cui l'annuncio e' pubblicato, quando la fonte e' un
    #: aggregatore: ``LinkedIn``, ``Indeed``, ``linkedin.com``.
    #:
    #: E' una colonna e non una lettura di ``raw``: la dashboard la mostra su
    #: ogni riga di ogni pagina, e ``raw`` e' un JSONB grande che Postgres
    #: dovrebbe decomprimere per intero per estrarne una parola.
    publisher: Mapped[str | None] = mapped_column(String(120))

    #: Payload originale della fonte, per poter riprocessare senza rifare la chiamata
    #: (utile con JSearch, dove ogni chiamata pesa sul budget mensile).
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    job: Mapped[Job] = relationship(back_populates="links")
    source: Mapped[Source] = relationship(back_populates="links")


class JobRequirements(Base):
    """Requisiti estratti dalla job description dall'LLM (Stadio 2 del matching)."""

    __tablename__ = "job_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    must_have: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default=default_sql("'{}'"))
    nice_to_have: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default=default_sql("'{}'"))
    tech_stack: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default=default_sql("'{}'"))

    min_years_experience: Mapped[int | None] = mapped_column(Integer)
    max_years_experience: Mapped[int | None] = mapped_column(Integer)

    #: Lingue richieste con livello, es. ``{"en": "C1", "de": "B2"}``.
    languages_required: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict, server_default=default_sql("'{}'::jsonb"))
    #: Politica remote dichiarata nel testo, che spesso contraddice il campo
    #: strutturato della fonte (annunci "remote" che poi chiedono 3 giorni in sede).
    remote_policy: Mapped[str | None] = mapped_column(String(300))
    requires_work_authorization: Mapped[bool | None] = mapped_column(Boolean)

    #: Segnali negativi rilevati: "unpaid", "equity only", stack legacy non voluto.
    red_flags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list, server_default=default_sql("'{}'"))

    extracted_with: Mapped[str] = mapped_column(String(128), nullable=False)
    extracted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    job: Mapped[Job] = relationship(back_populates="requirements")
