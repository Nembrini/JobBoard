"""Test della strutturazione del CV che non richiedono l'LLM.

Le chiamate al modello non sono deterministiche e costano quota: qui si testa
tutto cio' che sta *intorno* alla chiamata — la traduzione dello schema, gli id,
la normalizzazione, gli avvertimenti — che e' anche la parte dove i bug fanno
danni silenziosi.
"""

from __future__ import annotations

import json

import pytest

from jobboard.ai.client import _to_gemini_schema
from jobboard.cv.extract import ExtractedDocument
from jobboard.cv.structure import _assign_ids, _normalize, _warnings
from jobboard.schemas import Bullet, Contact, Experience, MasterProfile, Skills

# --- traduzione dello schema per Gemini --------------------------------------


def test_gemini_schema_drops_unsupported_keywords() -> None:
    """Regressione reale: la richiesta falliva con 400 INVALID_ARGUMENT.

    Pydantic emette ``additionalProperties`` per via di ``extra="forbid"``, e
    ``$ref``/``$defs`` per i modelli annidati. Gemini non li supporta.
    """
    raw = json.dumps(_to_gemini_schema(MasterProfile))

    for keyword in ("additionalProperties", "$ref", "$defs", "allOf", "const"):
        assert keyword not in raw, f"{keyword} non deve arrivare all'API"


def test_gemini_schema_keeps_every_field() -> None:
    """Regressione reale: filtrare le chiavi di ``properties`` svuotava lo schema.

    Le chiavi dentro ``properties`` sono nomi di campo, non parole chiave: un
    filtro applicato anche a quelle produceva uno schema valido ma vuoto, e il
    modello rispondeva un oggetto senza alcun contenuto.
    """
    schema = _to_gemini_schema(MasterProfile)

    assert set(schema["properties"]) == set(MasterProfile.model_fields)
    experience = schema["properties"]["experiences"]["items"]
    assert set(experience["properties"]) == set(Experience.model_fields)
    bullet = experience["properties"]["bullets"]["items"]
    assert set(bullet["properties"]) == set(Bullet.model_fields)


def test_gemini_schema_turns_optionals_into_nullable() -> None:
    """Pydantic scrive ``anyOf: [T, null]``; Gemini vuole il tipo con nullable."""
    schema = _to_gemini_schema(MasterProfile)
    headline = schema["properties"]["headline"]

    assert headline["type"] == "string"
    assert headline["nullable"] is True
    assert "anyOf" not in headline


# --- assegnazione degli id ---------------------------------------------------


def test_ids_come_from_content_not_from_the_model() -> None:
    """Gli id li assegna il codice: devono essere stabili e derivati dal contenuto."""
    data = _assign_ids(
        {
            "experiences": [
                {
                    "company": "Acme Srl",
                    "role": "Backend Developer",
                    "id": "qualcosa-inventato-dal-modello",
                    "bullets": [{"text": "a"}, {"text": "b"}],
                }
            ],
            "projects": [{"name": "Job Board"}],
        }
    )

    exp = data["experiences"][0]
    assert exp["id"] == "acme-srl-backend-developer"
    assert [b["id"] for b in exp["bullets"]] == [
        "acme-srl-backend-developer-1",
        "acme-srl-backend-developer-2",
    ]
    assert data["projects"][0]["id"] == "job-board"


def test_ids_are_deduplicated() -> None:
    """Due incarichi identici nella stessa azienda non devono collidere."""
    data = _assign_ids(
        {
            "experiences": [
                {"company": "Acme", "role": "Dev", "bullets": []},
                {"company": "Acme", "role": "Dev", "bullets": []},
            ]
        }
    )
    assert [e["id"] for e in data["experiences"]] == ["acme-dev", "acme-dev-2"]


def test_ids_strip_accents_and_punctuation() -> None:
    data = _assign_ids(
        {"education": [{"institution": "Università di Milano-Bicocca", "degree": "Laurea"}]}
    )
    assert data["education"][0]["id"] == "universita-di-milano-bicocca-laurea"


def test_id_falls_back_when_there_is_nothing_to_slugify() -> None:
    data = _assign_ids({"projects": [{"name": "!!!"}]})
    assert data["projects"][0]["id"] == "progetto-1"


# --- normalizzazione ---------------------------------------------------------


def test_all_caps_name_is_title_cased() -> None:
    """Un nome in maiuscolo e' una scelta grafica dell'originale, non un dato."""
    data = _normalize({"contact": {"full_name": "FILIPPO NEMBRINI"}})
    assert data["contact"]["full_name"] == "Filippo Nembrini"


def test_normal_name_is_left_alone() -> None:
    for name in ("Filippo Nembrini", "Filippo de Nembrini", "J. Nembrini"):
        assert _normalize({"contact": {"full_name": name}})["contact"]["full_name"] == name


# --- avvertimenti ------------------------------------------------------------


def _doc(**overrides: object) -> ExtractedDocument:
    defaults: dict[str, object] = {
        "text": "x" * 500,
        "method": "pypdfium2",
        "pages": 1,
        "language": "it",
        "source_name": "cv.pdf",
    }
    return ExtractedDocument(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_lost_numbers_are_surfaced_for_review() -> None:
    """Una cifra persa dall'estrattore non deve sparire in silenzio."""
    profile = MasterProfile(contact=Contact(full_name="Filippo Nembrini"))
    warnings = _warnings(profile, _doc(possibly_lost_numbers=("239",)))

    assert any("239" in w for w in warnings)


def test_warns_when_no_bullet_has_a_result() -> None:
    """Senza metriche il CV su misura non potra' produrre affermazioni forti."""
    profile = MasterProfile(
        contact=Contact(full_name="Filippo Nembrini"),
        skills=Skills(hard=["Python"]),
        experiences=[
            Experience(
                id="acme-dev",
                company="Acme",
                role="Dev",
                start="2022-01",
                bullets=[Bullet(id="acme-dev-1", text="Sviluppato un servizio di fatturazione.")],
            )
        ],
    )
    profile.contact.email = "a@b.it"

    warnings = _warnings(profile, _doc())
    assert any("risultato misurabile" in w for w in warnings)


def test_warns_about_an_experience_with_no_bullets() -> None:
    """Un'esperienza senza bullet finisce nel CV come una riga vuota."""
    profile = MasterProfile(
        contact=Contact(full_name="Filippo Nembrini", email="a@b.it"),
        skills=Skills(hard=["Python"]),
        experiences=[
            Experience(id="acme-dev", company="Acme", role="Dev", start="2022-01", bullets=[])
        ],
    )

    assert any("senza alcun bullet" in w for w in _warnings(profile, _doc()))


def test_no_warnings_on_a_healthy_profile() -> None:
    profile = MasterProfile(
        contact=Contact(full_name="Filippo Nembrini", email="a@b.it"),
        skills=Skills(hard=["Python"]),
        experiences=[
            Experience(
                id="acme-dev",
                company="Acme",
                role="Dev",
                start="2022-01",
                bullets=[
                    Bullet(
                        id="acme-dev-1",
                        text="Ridotto dell'80% le richieste di assistenza degli operatori.",
                        result="80%",
                    )
                ],
            )
        ],
    )

    assert _warnings(profile, _doc()) == []


# --- normalizzazione delle date ----------------------------------------------


def test_a_bare_year_becomes_january() -> None:
    """Regressione reale: il modello ha risposto '2024' e la validazione e' fallita.

    Il prompt chiede gia' YYYY-MM, ma chiederlo non basta. Gennaio e' una
    convenzione applicata sia a inizio sia a fine, cosi' la durata resta corretta.
    """
    data = _normalize({"education": [{"start": "2021", "end": "2024"}]})
    assert data["education"][0] == {"start": "2021-01", "end": "2024-01"}


@pytest.mark.parametrize(
    ("scritto", "atteso"),
    [
        ("2024-3", "2024-03"),
        ("2024-03-15", "2024-03"),
        ("03/2024", "2024-03"),
        ("3/2024", "2024-03"),
        ("2024/03", "2024-03"),
        ("2024-03", "2024-03"),
    ],
)
def test_the_usual_date_shapes_are_understood(scritto: str, atteso: str) -> None:
    data = _normalize({"experiences": [{"start": scritto}]})
    assert data["experiences"][0]["start"] == atteso


@pytest.mark.parametrize("scritto", ["presente", "Present", "in corso", "attuale", ""])
def test_an_ongoing_role_has_no_end_date(scritto: str) -> None:
    """Nel modello 'in corso' si esprime con l'assenza della data, non con una parola."""
    data = _normalize({"experiences": [{"start": "2024-01", "end": scritto}]})
    assert data["experiences"][0]["end"] is None


def test_an_unrecognisable_date_is_left_to_the_schema() -> None:
    """Meglio un errore di validazione che una data inventata."""
    data = _normalize({"experiences": [{"start": "primavera 2024"}]})
    assert data["experiences"][0]["start"] == "primavera 2024"


def test_an_impossible_month_is_not_accepted() -> None:
    data = _normalize({"experiences": [{"start": "2024-13"}]})
    assert data["experiences"][0]["start"] == "2024-13"


def test_certification_dates_are_normalised_too() -> None:
    data = _normalize({"certifications": [{"issued": "2023", "expires": "12/2026"}]})
    assert data["certifications"][0] == {"issued": "2023-01", "expires": "2026-12"}
