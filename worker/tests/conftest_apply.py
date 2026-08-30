"""Materiale condiviso dai test della Fase 7 (candidatura)."""

from __future__ import annotations

from typing import Any

from jobboard.schemas import CandidateAnswers

CANDIDATO_GREZZO: dict[str, Any] = {
    "full_name": "Filippo Nembrini",
    "email": "filippo@example.com",
    "phone": "+39 333 1234567",
    "city": "Milano",
    "country": "IT",
    "linkedin_url": "https://linkedin.com/in/filipponembrini",
    "github_url": "https://github.com/fnembrini",
    "work_authorization": {"IT": "citizen", "DE": "eu_eligible"},
    "willing_to_relocate": True,
    "notice_period_days": 30,
    "salary_expectation_min": 45000,
    "salary_expectation_max": 55000,
    "salary_currency": "EUR",
    "languages": {"it": "native", "en": "B2"},
    "ats_answers": {
        "years_of_experience": 4,
        "requires_sponsorship_now": False,
        "requires_sponsorship_future": False,
        "willing_to_travel": True,
        "available_from": "2026-10-01",
    },
}


def candidato(**overrides: Any) -> CandidateAnswers:
    dati = {**CANDIDATO_GREZZO, **overrides}
    return CandidateAnswers.model_validate(dati)
