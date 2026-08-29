"""Tabelle operative: coda dei task, heartbeat del worker, log delle run, settings."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, default_sql, enum_column
from .enums import RunStatus, TaskStatus, TaskType


class Task(Base, TimestampMixin):
    """Coda di lavoro dalla dashboard verso il worker.

    La dashboard su Vercel non puo' chiamare il PC di casa: inserisce una riga qui e
    il worker la raccoglie entro ``TASK_POLL_SECONDS``. Il prelievo usa
    ``SELECT ... FOR UPDATE SKIP LOCKED``, che garantisce che nessun task venga
    eseguito due volte anche con piu' worker attivi.
    """

    __tablename__ = "task"
    __table_args__ = (
        # Indice PARZIALE sui soli pending: la query di polling gira ogni 30 secondi
        # e guarda solo quelli. Indicizzare anche done/failed farebbe crescere
        # l'indice all'infinito su righe che non verranno mai piu' interrogate.
        Index(
            "ix_task_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_task_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    task_type: Mapped[TaskType] = enum_column(TaskType, nullable=False)
    status: Mapped[TaskStatus] = enum_column(TaskStatus, nullable=False, default=TaskStatus.PENDING)

    #: Parametri del task, es. ``{"match_id": 42}`` per ``generate_cv``.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=default_sql("'{}'::jsonb"))

    #: 0-100, aggiornato dal worker durante l'esecuzione perche' la UI possa
    #: mostrare una barra invece di uno spinner cieco.
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=default_sql("0"))
    progress_message: Mapped[str | None] = mapped_column(String(300))

    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=default_sql("0"))
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3, server_default=default_sql("3"))


class WorkerHeartbeat(Base):
    """Singleton aggiornato dal worker: alimenta l'indicatore online/offline in UI.

    Senza questo, premere "Candidati" a PC spento darebbe un silenzio indistinguibile
    da un errore.
    """

    __tablename__ = "worker_heartbeat"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str | None] = mapped_column(String(32))
    hostname: Mapped[str | None] = mapped_column(String(128))
    last_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_status: Mapped[RunStatus | None] = enum_column(RunStatus)


class Run(Base):
    """Log di una esecuzione della pipeline giornaliera, una riga per fonte."""

    __tablename__ = "run"
    __table_args__ = (Index("ix_run_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Raggruppa le righe della stessa esecuzione fra fonti diverse.
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id", ondelete="SET NULL"))

    status: Mapped[RunStatus] = enum_column(RunStatus, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    jobs_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=default_sql("0"))
    jobs_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=default_sql("0"))
    jobs_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=default_sql("0"))
    api_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=default_sql("0"))
    error: Mapped[str | None] = mapped_column(Text)


class Setting(Base, TimestampMixin):
    """Configurazione modificabile a runtime dalla pagina Impostazioni.

    Distinta dalle variabili d'ambiente: qui stanno le preferenze che Filippo cambia
    dalla UI (soglia, orario, notifiche on/off), in ``.env`` stanno i segreti e i
    parametri di deploy.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
