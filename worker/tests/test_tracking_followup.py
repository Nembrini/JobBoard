"""Test del promemoria di follow-up (Fase 9.4): nessun database, nessuna rete.

Stesso principio di ``test_notify.py``: ``find_due`` e ``build_followup_email``
sono pure una volta tolta la sessione.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from pydantic import SecretStr

from jobboard.config import Settings
from jobboard.models import Application, Job
from jobboard.models.enums import ApplicationStatus
from jobboard.tracking.followup import (
    DueApplication,
    build_followup_email,
    find_due,
    send_followup_reminders,
)
from jobboard.tracking.settings import TrackingSettings

_ORA = dt.datetime(2026, 8, 31, 10, 0, tzinfo=dt.UTC)


def _application(**patch: Any) -> Application:
    base = {
        "id": 1,
        "status": ApplicationStatus.SUBMITTED,
        "submitted_at": _ORA - dt.timedelta(days=10),
        "follow_up_due_at": None,
    }
    return Application(**{**base, **patch})


def _job(**patch: Any) -> Job:
    base = {"id": 1, "title": "Backend Developer", "company": "Acme"}
    return Job(**{**base, **patch})


_TRACKING = TrackingSettings(enabled=True, follow_up_after_days=7)


# --- find_due -----------------------------------------------------------------------


def test_candidatura_recente_non_e_dovuta() -> None:
    app = _application(submitted_at=_ORA - dt.timedelta(days=2))
    assert find_due([(app, _job())], tracking=_TRACKING, now=_ORA) == []


def test_candidatura_silenziosa_da_abbastanza_e_dovuta() -> None:
    app = _application(submitted_at=_ORA - dt.timedelta(days=8))
    dovute = find_due([(app, _job())], tracking=_TRACKING, now=_ORA)
    assert len(dovute) == 1
    assert dovute[0].days_silent == 8


def test_stato_non_in_attesa_non_e_dovuto() -> None:
    for stato in (ApplicationStatus.REJECTED, ApplicationStatus.OFFER, ApplicationStatus.DRAFT):
        app = _application(status=stato, submitted_at=_ORA - dt.timedelta(days=30))
        assert find_due([(app, _job())], tracking=_TRACKING, now=_ORA) == []


def test_gia_segnalata_non_si_ripete() -> None:
    app = _application(
        submitted_at=_ORA - dt.timedelta(days=20), follow_up_due_at=_ORA - dt.timedelta(days=1)
    )
    assert find_due([(app, _job())], tracking=_TRACKING, now=_ORA) == []


def test_senza_submitted_at_non_e_mai_dovuta() -> None:
    app = _application(submitted_at=None)
    assert find_due([(app, _job())], tracking=_TRACKING, now=_ORA) == []


# --- build_followup_email -------------------------------------------------------------


def test_nessuna_candidatura_dovuta_non_produce_mail() -> None:
    assert build_followup_email([], "https://x") is None


def test_ordina_per_giorni_di_silenzio_decrescente() -> None:
    due = [
        DueApplication(application_id=1, job_id=1, title="A", company="Acme", days_silent=3),
        DueApplication(application_id=2, job_id=2, title="B", company="Beta", days_silent=15),
    ]
    email = build_followup_email(due, "https://x")
    assert email is not None
    assert email.text.index("15 giorni") < email.text.index("3 giorni")
    assert email.count == 2


# --- send_followup_reminders -----------------------------------------------------------


def test_tracciamento_disattivo_non_spedisce(monkeypatch: pytest.MonkeyPatch) -> None:
    chiamato = False

    def _boom(*args: Any, **kwargs: Any) -> None:
        nonlocal chiamato
        chiamato = True

    import jobboard.tracking.followup as followup_mod

    monkeypatch.setattr(followup_mod, "send_html_email", _boom)
    due = [DueApplication(application_id=1, job_id=1, title="A", company="Acme", days_silent=8)]
    settings = Settings(gmail_address="io@example.com", gmail_app_password=SecretStr("app-pass"))
    esito = send_followup_reminders(TrackingSettings(enabled=False), due, settings)
    assert esito is None
    assert chiamato is False


def test_tracciamento_attivo_spedisce(monkeypatch: pytest.MonkeyPatch) -> None:
    catturato: dict[str, Any] = {}

    def _fake_send(settings: Settings, **kwargs: Any) -> None:
        catturato.update(kwargs)

    import jobboard.tracking.followup as followup_mod

    monkeypatch.setattr(followup_mod, "send_html_email", _fake_send)
    due = [DueApplication(application_id=1, job_id=1, title="A", company="Acme", days_silent=8)]
    settings = Settings(gmail_address="io@example.com", gmail_app_password=SecretStr("app-pass"))
    esito = send_followup_reminders(TrackingSettings(enabled=True), due, settings)
    assert esito is not None
    assert catturato["to_addr"] == "io@example.com"
    assert catturato["subject"] == esito.subject
