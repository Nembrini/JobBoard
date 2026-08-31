"""Lettura e scrittura delle entita' sul database.

Il resto del codice non compone query: chiede qui. Cosi' i dettagli che si
sbagliano facilmente — il vincolo di singleton sul profilo, la serializzazione
dell'embedding, il flag ``reviewed`` — stanno in un posto solo.
"""

from .applicant_info import StoredApplicantInfo, load_applicant_info, save_applicant_info
from .llm_usage import record_llm_usage, usage_since
from .profile import (
    StoredCandidate,
    StoredProfile,
    load_candidate,
    load_profile,
    mark_reviewed,
    save_candidate,
    save_profile,
)

__all__ = [
    "StoredApplicantInfo",
    "StoredCandidate",
    "StoredProfile",
    "load_applicant_info",
    "load_candidate",
    "load_profile",
    "mark_reviewed",
    "record_llm_usage",
    "save_applicant_info",
    "save_candidate",
    "save_profile",
    "usage_since",
]
