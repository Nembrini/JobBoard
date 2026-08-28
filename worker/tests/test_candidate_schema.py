"""Test delle risposte ai form di candidatura.

E' il modulo i cui valori finiscono dentro candidature vere: un codice paese
sbagliato o una RAL invertita non si notano finche' non e' partito l'invio.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobboard.schemas import CandidateAnswers, Contact, LanguageSkill, MasterProfile


def _profile(**contact: object) -> MasterProfile:
    defaults: dict[str, object] = {
        "full_name": "Filippo Nembrini",
        "email": "filippo@example.com",
        "city": "Milano",
        "country": "IT",
    }
    return MasterProfile(contact=Contact(**{**defaults, **contact}))  # type: ignore[arg-type]


def _answers(**overrides: object) -> CandidateAnswers:
    defaults: dict[str, object] = {"full_name": "Filippo Nembrini", "email": "f@example.com"}
    return CandidateAnswers(**{**defaults, **overrides})  # type: ignore[arg-type]


# --- costruzione dal profilo -------------------------------------------------


def test_contact_data_is_copied_from_the_profile() -> None:
    profile = _profile(linkedin_url="https://linkedin.com/in/x", phone="+39 333 1234567")
    profile.languages.append(LanguageSkill(code="it", level="native"))

    answers = CandidateAnswers.from_master_profile(profile)

    assert answers.full_name == "Filippo Nembrini"
    assert answers.email == "filippo@example.com"
    assert answers.phone == "+39 333 1234567"
    assert answers.country == "IT"
    assert answers.linkedin_url == "https://linkedin.com/in/x"
    assert answers.languages == {"it": "native"}


def test_work_authorization_is_never_guessed() -> None:
    """Vivere a Milano non dimostra la cittadinanza italiana.

    E' il campo su cui una risposta sbagliata brucia la candidatura, quindi la
    bozza lo lascia vuoto e l'avvertimento chiede di compilarlo.
    """
    answers = CandidateAnswers.from_master_profile(_profile(country="IT"))

    assert answers.work_authorization == {}
    assert any("work_authorization" in w for w in answers.warnings())


def test_a_profile_without_email_cannot_produce_answers() -> None:
    """L'email e' obbligatoria in ogni form: meglio fermarsi qui che al form."""
    with pytest.raises(ValueError, match="email"):
        CandidateAnswers.from_master_profile(_profile(email=None))


# --- validazione -------------------------------------------------------------


def test_country_codes_are_normalised_to_upper_case() -> None:
    answers = _answers(country="it", work_authorization={"de": "eu_eligible"})
    assert answers.country == "IT"
    assert answers.work_authorization == {"DE": "eu_eligible"}


def test_language_codes_are_normalised_to_lower_case() -> None:
    assert _answers(languages={"IT": "native"}).languages == {"it": "native"}


@pytest.mark.parametrize("bad", ["ITA", "I", "1T"])
def test_an_invalid_country_code_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError, match="codice paese"):
        _answers(country=bad)


def test_an_unknown_work_authorization_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _answers(work_authorization={"IT": "forse"})


def test_an_inverted_salary_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match="inferiore"):
        _answers(salary_expectation_min=45000, salary_expectation_max=35000)


def test_a_single_ended_salary_range_is_allowed() -> None:
    """Dichiarare solo il minimo e' normale: e' quello che si negozia."""
    assert _answers(salary_expectation_min=40000).salary_expectation_max is None


@pytest.mark.parametrize("phone", ["+39 333 1234567", "0039-333-1234567", "(02) 1234 5678"])
def test_the_usual_phone_formats_are_accepted(phone: str) -> None:
    assert _answers(phone=phone).phone == phone


def test_a_phone_that_is_not_a_number_is_rejected() -> None:
    with pytest.raises(ValidationError, match="telefono"):
        _answers(phone="chiedimelo in colloquio")


def test_currency_must_be_iso_4217() -> None:
    assert _answers(salary_currency="eur").salary_currency == "EUR"
    with pytest.raises(ValidationError, match="valuta"):
        _answers(salary_currency="euro")


def test_an_invalid_availability_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="data"):
        _answers(ats_answers={"available_from": "01/09/2026"})


def test_unknown_fields_are_refused() -> None:
    """Un campo scritto male nel JSON deve dare errore, non essere ignorato."""
    with pytest.raises(ValidationError):
        _answers(telefono="+39 333 1234567")


# --- privacy -----------------------------------------------------------------


def test_demographic_questions_are_declined_by_default() -> None:
    """Genere, etnia e disabilita' sono categorie protette.

    Ogni form ATS offre "preferisco non rispondere": scegliendo sempre quella, il
    sistema non deve conservare nessun dato particolare su un database di terzi.
    """
    assert _answers().ats_answers.decline_demographic_questions is True


# --- avvertimenti ------------------------------------------------------------


def test_warnings_name_what_blocks_a_real_application() -> None:
    warnings = _answers().warnings()

    assert any("telefono" in w for w in warnings)
    assert any("work_authorization" in w for w in warnings)
    assert any("lingua" in w for w in warnings)
    assert any("RAL" in w for w in warnings)


def test_a_complete_profile_has_no_warnings() -> None:
    complete = _answers(
        phone="+39 333 1234567",
        linkedin_url="https://linkedin.com/in/x",
        work_authorization={"IT": "citizen"},
        languages={"it": "native", "en": "C1"},
        salary_expectation_min=35000,
        notice_period_days=30,
    )
    assert complete.warnings() == []


def test_a_salary_note_counts_as_an_answer() -> None:
    """Molti form chiedono la RAL come testo libero, non come numero."""
    answers = _answers(ats_answers={"salary_note": "Allineata al mercato, trattabile"})
    assert not any("RAL" in w for w in answers.warnings())


# --- serializzazione ---------------------------------------------------------


def test_json_roundtrip_is_lossless() -> None:
    """Il JSON e' il formato in cui questi dati vengono corretti a mano."""
    original = _answers(
        work_authorization={"IT": "citizen", "DE": "eu_eligible"},
        languages={"it": "native"},
        ats_answers={"years_of_experience": 2, "requires_sponsorship_now": False},
    )
    assert CandidateAnswers.model_validate_json(original.model_dump_json()) == original
