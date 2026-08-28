"""Test di ``MasterProfile``.

Le invarianti verificate qui non sono formalita': il validatore anti-invenzione
della Fase 6 usa gli id come chiavi e ``known_skills`` come verita' di
riferimento. Se saltano queste, il CV generato puo' contenere affermazioni non
verificabili.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobboard.schemas import Bullet, Contact, Experience, MasterProfile, Project, Skills


def _experience(**overrides: object) -> Experience:
    defaults: dict[str, object] = {
        "id": "acme-backend",
        "company": "Acme Srl",
        "role": "Backend Developer",
        "start": "2022-01",
        "bullets": [
            Bullet(
                id="acme-backend-1",
                text=(
                    "Progettato un servizio di fatturazione riducendo i tempi "
                    "da sei ore a venti minuti."
                ),
                action="Progettato",
                result="da sei ore a venti minuti",
                skills=["Python", "FastAPI"],
            )
        ],
        "tech": ["Python", "PostgreSQL"],
    }
    return Experience(**{**defaults, **overrides})  # type: ignore[arg-type]


def _profile(**overrides: object) -> MasterProfile:
    defaults: dict[str, object] = {
        "contact": Contact(full_name="Filippo Nembrini"),
        "experiences": [_experience()],
        "skills": Skills(hard=["Docker"], soft=["Problem solving"]),
    }
    return MasterProfile(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_minimal_profile_is_valid() -> None:
    p = _profile()
    assert p.contact.full_name == "Filippo Nembrini"
    assert p.experiences[0].end is None, "end assente significa 'in corso'"


def test_duplicate_ids_are_rejected() -> None:
    """Il validatore anti-invenzione indicizza per id: due voci uguali lo renderebbero ambiguo."""
    with pytest.raises(ValidationError, match="id duplicati"):
        _profile(experiences=[_experience(), _experience()])


def test_bullet_id_must_be_kebab_case() -> None:
    with pytest.raises(ValidationError, match="id non valido"):
        Bullet(id="Acme Backend 1", text="Un testo abbastanza lungo da passare la validazione.")


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(ValidationError, match="precede"):
        _experience(start="2022-06", end="2022-01")


@pytest.mark.parametrize("bad", ["2022", "2022-13", "22-01", "2022/01", ""])
def test_invalid_year_month(bad: str) -> None:
    with pytest.raises(ValidationError):
        _experience(start=bad)


def test_extra_fields_are_rejected() -> None:
    """L'LLM che struttura il CV puo' inventarsi campi: devono fallire subito."""
    with pytest.raises(ValidationError):
        Contact(full_name="Filippo Nembrini", stipendio_attuale="50k")  # type: ignore[call-arg]


def test_known_skills_collects_from_every_level() -> None:
    """Le skill vanno raccolte anche da bullet e progetti, non solo dalla sezione Skills."""
    p = _profile(
        projects=[
            Project(id="jobboard", name="JobBoard", description="Dashboard", tech=["Next.js"])
        ]
    )
    skills = p.known_skills()

    assert {"docker", "problem solving"} <= skills, "sezione Skills"
    assert "postgresql" in skills, "tech dell'esperienza"
    assert "fastapi" in skills, "skill citata dentro un bullet"
    assert "next.js" in skills, "tech di un progetto"
    assert all(s == s.lower() for s in skills), "il confronto deve essere case-insensitive"


def test_embedding_text_has_content_not_metadata() -> None:
    """Il testo per l'embedding deve pesare sul contenuto, non su date e anagrafica."""
    text = _profile(headline="Software Developer").to_embedding_text()

    assert "Software Developer" in text
    assert "Backend Developer presso Acme Srl" in text
    assert "servizio di fatturazione" in text
    assert "2022-01" not in text, "le date aggiungono solo rumore alla similarita'"
    assert "Filippo Nembrini" not in text, "l'anagrafica non descrive competenze"


def test_roundtrip_through_json() -> None:
    """Il profilo viaggia come JSONB su Postgres: deve sopravvivere al giro."""
    original = _profile()
    restored = MasterProfile.model_validate_json(original.model_dump_json())
    assert restored == original
