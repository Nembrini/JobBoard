"""Test del classificatore (Fase 9.3): nessuna rete, provider finto.

Stesso ``ProviderFinto`` di ``conftest_cv.py`` nello spirito, ma locale: qui
la risposta è un'``EmailClassification``, non un ``TailoredCV``.
"""

from __future__ import annotations

from typing import Any

from jobboard.ai.client import LLMProvider, LLMResult, LLMUsage
from jobboard.models.enums import ApplicationStatus, EmailClass
from jobboard.tracking.classifier import (
    STATUS_BY_CLASS,
    EmailClassification,
    build_prompt,
    classify,
    is_new_message,
    next_status,
)


class _ProviderFinto(LLMProvider):
    def __init__(self, risposta: EmailClassification) -> None:
        self.risposta = risposta
        self.prompt_ricevuto: str | None = None
        self.system_ricevuto: str | None = None

    def generate_text(self, prompt: str, **kwargs: Any) -> LLMResult[str]:
        raise NotImplementedError

    def generate_structured(self, prompt: str, schema: Any, **kwargs: Any) -> LLMResult[Any]:
        self.prompt_ricevuto = prompt
        self.system_ricevuto = kwargs.get("system")
        return LLMResult(self.risposta, LLMUsage("finto", 100, 40))

    def generate_json(self, prompt: str, schema: Any, **kwargs: Any) -> LLMResult[dict[str, Any]]:
        raise NotImplementedError


def test_classify_passa_azienda_ruolo_oggetto_e_corpo_nel_prompt() -> None:
    finto = _ProviderFinto(EmailClassification(classification=EmailClass.ACK, summary="ok"))
    esito = classify(
        finto, company="Acme", job_title="Backend Developer", subject="Ricevuto", body="Grazie."
    )
    assert esito.value.classification is EmailClass.ACK
    assert finto.prompt_ricevuto is not None
    assert "Acme" in finto.prompt_ricevuto
    assert "Backend Developer" in finto.prompt_ricevuto
    assert "Ricevuto" in finto.prompt_ricevuto
    assert "Grazie." in finto.prompt_ricevuto


def test_build_prompt_taglia_corpi_lunghissimi() -> None:
    corpo = "x" * 10_000
    prompt = build_prompt(company="Acme", job_title="Dev", subject="Oggetto", body=corpo)
    # Il taglio e' su _MAX_BODY_CHARS (4000): il prompt intero resta molto piu' corto
    # dei diecimila caratteri originali.
    assert len(prompt) < 5_000


# --- STATUS_BY_CLASS / next_status ---------------------------------------------------


def test_ogni_classe_ha_una_voce_nella_mappa() -> None:
    for classe in EmailClass:
        assert classe in STATUS_BY_CLASS


def test_interview_avanza_lo_stato() -> None:
    nuovo = next_status(ApplicationStatus.SUBMITTED, EmailClass.INTERVIEW)
    assert nuovo is ApplicationStatus.INTERVIEW


def test_ack_dopo_interview_non_retrocede() -> None:
    """Un "ricevuto" arrivato in ritardo non deve cancellare un colloquio già fissato."""
    assert next_status(ApplicationStatus.INTERVIEW, EmailClass.ACK) is ApplicationStatus.INTERVIEW


def test_rejection_vince_sempre_su_uno_stato_non_terminale() -> None:
    nuovo = next_status(ApplicationStatus.INTERVIEW, EmailClass.REJECTION)
    assert nuovo is ApplicationStatus.REJECTED


def test_stato_terminale_non_si_riapre_da_solo() -> None:
    for terminale in (
        ApplicationStatus.REJECTED,
        ApplicationStatus.OFFER,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.FAILED,
    ):
        assert next_status(terminale, EmailClass.INTERVIEW) is terminale


def test_request_info_e_other_non_cambiano_lo_stato() -> None:
    partenza = ApplicationStatus.SUBMITTED
    assert next_status(partenza, EmailClass.REQUEST_INFO) is partenza
    assert next_status(partenza, EmailClass.OTHER) is partenza


# --- is_new_message -------------------------------------------------------------------


def test_is_new_message_senza_id_e_sempre_nuovo() -> None:
    assert is_new_message("", frozenset({"<a@x>"})) is True


def test_is_new_message_gia_visto() -> None:
    assert is_new_message("<a@x>", frozenset({"<a@x>"})) is False


def test_is_new_message_mai_visto() -> None:
    assert is_new_message("<b@x>", frozenset({"<a@x>"})) is True
