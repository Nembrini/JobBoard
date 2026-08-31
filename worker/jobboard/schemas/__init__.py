"""Schemi Pydantic condivisi fra gli stadi della pipeline."""

from .applicant_info import ApplicantInfoBank, ApplicantInfoItem
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
    "ApplicantInfoBank",
    "ApplicantInfoItem",
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
