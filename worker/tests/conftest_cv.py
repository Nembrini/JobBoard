"""Materiale condiviso dai test della Fase 6.

Un profilo e un annuncio realistici, e un provider LLM finto. Il profilo e'
scritto **in italiano con i numeri a lettere**, come escono davvero dai CV veri:
e' la condizione in cui il validatore rischia i falsi positivi, quindi e' quella
in cui va provato.
"""

from __future__ import annotations

from typing import Any

from jobboard.ai.client import LLMProvider, LLMResult, LLMUsage
from jobboard.ai.tailor import TailoredCV
from jobboard.models import Job
from jobboard.models.enums import AtsType, ContractType, Seniority, WorkMode
from jobboard.schemas import MasterProfile

PROFILO_GREZZO: dict[str, Any] = {
    "contact": {
        "full_name": "Filippo Nembrini",
        "email": "filippo@example.com",
        "city": "Milano",
        "country": "IT",
    },
    "headline": "Software Developer",
    "experiences": [
        {
            "id": "acme-be",
            "company": "Acme Srl",
            "role": "Backend Developer",
            "location": "Milano, IT",
            "start": "2022-01",
            "end": None,
            "tech": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "bullets": [
                {
                    "id": "acme-be-1",
                    "text": (
                        "Progettato un servizio di fatturazione in Python e FastAPI, "
                        "riducendo il tempo di elaborazione mensile da sei ore a venti minuti."
                    ),
                    "result": "da sei ore a venti minuti",
                    "skills": ["Python", "FastAPI"],
                },
                {
                    "id": "acme-be-2",
                    "text": (
                        "Migrato il database da MySQL a PostgreSQL senza interruzioni, "
                        "su un dataset di quaranta milioni di righe."
                    ),
                    "skills": ["PostgreSQL"],
                },
            ],
        },
        {
            "id": "globex-jr",
            "company": "Globex SpA",
            "role": "Junior Developer",
            "start": "2020-09",
            "end": "2021-12",
            "tech": ["Python", "REST"],
            "bullets": [
                {
                    "id": "globex-jr-1",
                    "text": (
                        "Sviluppate integrazioni REST con tre fornitori esterni, coperte da "
                        "test che hanno portato la copertura dal quaranta all'ottanta percento."
                    ),
                    "skills": ["REST", "pytest"],
                }
            ],
        },
    ],
    "education": [
        {
            "id": "unimi",
            "institution": "Universita' degli Studi di Milano",
            "degree": "Laurea Triennale",
            "field_of_study": "Informatica",
            "end": "2020-07",
        }
    ],
    "skills": {
        "hard": ["Python", "FastAPI", "PostgreSQL", "Docker", "REST", "pytest", "Java"],
        "soft": ["Lavoro in team"],
    },
    "languages": [{"code": "it", "level": "native"}, {"code": "en", "level": "B2"}],
}


def profilo() -> MasterProfile:
    return MasterProfile.model_validate(PROFILO_GREZZO)


def annuncio(**overrides: Any) -> Job:
    campi: dict[str, Any] = {
        "id": 77,
        "title": "Backend Engineer (Python)",
        "company": "Northwind GmbH",
        "company_normalized": "northwind",
        "canonical_key": "northwind|backend-engineer|berlin",
        "url": "https://example.com/jobs/77",
        "description_clean": (
            "Backend Engineer with strong Python experience. PostgreSQL, Docker, "
            "FastAPI. Kubernetes is a plus. 3+ years of backend development."
        ),
        "lang": "en",
        "city": "Berlin",
        "country": "DE",
        "work_mode": WorkMode.HYBRID,
        "contract_type": ContractType.PERMANENT,
        "seniority": Seniority.MID,
        "ats_type": AtsType.GREENHOUSE,
        "salary_is_stated": False,
        "is_active": True,
    }
    campi.update(overrides)
    return Job(**campi)


#: Un CV onesto: ogni bullet dichiara la sua fonte, ogni cifra viene da li',
#: ogni competenza dichiara da quale voce del profilo deriva.
CV_ONESTO: dict[str, Any] = {
    "top_keywords": ["Python", "PostgreSQL", "FastAPI", "Docker", "REST APIs"],
    "summary": (
        "Backend developer building Python services in production. Designed a FastAPI "
        "billing service that cut monthly processing from six hours to twenty minutes, "
        "and migrated a forty million row database to PostgreSQL with no downtime."
    ),
    "experience": [
        {
            "id": "acme-be",
            "bullets": [
                {
                    "source_id": "acme-be-1",
                    "text": (
                        "Designed a billing service in Python and FastAPI, cutting monthly "
                        "processing time from 6 hours to 20 minutes."
                    ),
                },
                {
                    "source_id": "acme-be-2",
                    "text": (
                        "Migrated a 40M row database from MySQL to PostgreSQL with no downtime."
                    ),
                },
            ],
        },
        {
            "id": "globex-jr",
            "bullets": [
                {
                    "source_id": "globex-jr-1",
                    "text": (
                        "Built REST integrations with three external providers, raising test "
                        "coverage from 40% to 80%."
                    ),
                }
            ],
        },
    ],
    "skills": {
        "hard": [
            {"text": "Python", "source": "Python"},
            # La grafia dell'annuncio, non quella del profilo.
            {"text": "Postgres", "source": "PostgreSQL"},
            {"text": "Docker", "source": "Docker"},
        ],
        # Tradotta: il profilo e' italiano, il CV e' inglese.
        "soft": [{"text": "Teamwork", "source": "Lavoro in team"}],
    },
}


def cv(**patch: Any) -> TailoredCV:
    """Il CV onesto, eventualmente peggiorato in un punto solo."""
    dati = {**CV_ONESTO, **patch}
    return TailoredCV.model_validate(dati)


class ProviderFinto(LLMProvider):
    """Risponde sempre la stessa cosa, o una sequenza di cose. Nessuna rete."""

    def __init__(self, *risposte: TailoredCV) -> None:
        self.risposte = list(risposte)
        self.prompt_ricevuti: list[str] = []

    @property
    def chiamate(self) -> int:
        return len(self.prompt_ricevuti)

    def generate_text(self, prompt: str, **kwargs: Any) -> LLMResult[str]:
        raise NotImplementedError

    def generate_structured(self, prompt: str, schema: Any, **kwargs: Any) -> LLMResult[Any]:
        self.prompt_ricevuti.append(prompt)
        indice = min(len(self.prompt_ricevuti) - 1, len(self.risposte) - 1)
        return LLMResult(self.risposte[indice], LLMUsage("finto", 1000, 400))

    def generate_json(self, prompt: str, schema: Any, **kwargs: Any) -> LLMResult[dict[str, Any]]:
        raise NotImplementedError
