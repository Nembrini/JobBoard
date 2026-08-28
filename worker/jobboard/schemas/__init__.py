"""Schemi Pydantic condivisi fra gli stadi della pipeline."""

from .candidate import AtsAnswers, CandidateAnswers, WorkAuthorization
from .profile import (
    Bullet,
    CefrLevel,
    Certification,
    Contact,
    Education,
    Experience,
    LanguageSkill,
    MasterProfile,
    Project,
    Skills,
)

__all__ = [
    "AtsAnswers",
    "Bullet",
    "CandidateAnswers",
    "CefrLevel",
    "Certification",
    "Contact",
    "Education",
    "Experience",
    "LanguageSkill",
    "MasterProfile",
    "Project",
    "Skills",
    "WorkAuthorization",
]
