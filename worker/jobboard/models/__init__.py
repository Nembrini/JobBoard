"""Modelli SQLAlchemy — fonte di verita' dello schema.

Alembic autogenera le migration da qui, e il lato Next.js legge i tipi TypeScript
dal database con ``drizzle-kit pull``. Modificare una colonna significa modificarla
in questo package e in nessun altro posto.

Tutti i modelli vanno importati qui: ``Base.metadata`` deve conoscerli al momento
in cui Alembic confronta lo schema, altrimenti genera una migration che droppa le
tabelle che non ha "visto".
"""

from .application import Application, ApplicationEvent
from .base import Base, TimestampMixin, enum_column, utcnow
from .enums import (
    TERMINAL_APPLICATION_STATUSES,
    TIER_A_ATS,
    ApplicationEventType,
    ApplicationStatus,
    ApplicationTier,
    AtsType,
    ContractType,
    EmailClass,
    LlmUsagePurpose,
    MatchStatus,
    RunStatus,
    SalaryPeriod,
    Seniority,
    TaskStatus,
    TaskType,
    WorkMode,
)
from .job import Job, JobRequirements, JobSourceLink, Source
from .match import Match
from .ops import LLMUsageLog, Run, Setting, Task, WorkerHeartbeat
from .profile import ApplicantInfo, CandidateProfile, Profile

__all__ = [
    "TERMINAL_APPLICATION_STATUSES",
    "TIER_A_ATS",
    "ApplicantInfo",
    "Application",
    "ApplicationEvent",
    "ApplicationEventType",
    "ApplicationStatus",
    "ApplicationTier",
    "AtsType",
    "Base",
    "CandidateProfile",
    "ContractType",
    "EmailClass",
    "Job",
    "JobRequirements",
    "JobSourceLink",
    "LLMUsageLog",
    "LlmUsagePurpose",
    "Match",
    "MatchStatus",
    "Profile",
    "Run",
    "RunStatus",
    "SalaryPeriod",
    "Seniority",
    "Setting",
    "Source",
    "Task",
    "TaskStatus",
    "TaskType",
    "TimestampMixin",
    "WorkMode",
    "WorkerHeartbeat",
    "enum_column",
    "utcnow",
]
