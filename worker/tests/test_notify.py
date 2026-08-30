"""Test del digest email (Fase 8.3/8.4): nessun database, nessuna rete.

``build_digest`` e ``load_notification_settings`` sono pure una volta tolta la
sessione — la stessa ragione per cui ``test_matching.py`` testa ``_row`` con una
``_FakeSession`` invece di un database vero.
"""

from __future__ import annotations

import smtplib
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr

from jobboard.config import Settings
from jobboard.models import Job, Setting
from jobboard.models.enums import AtsType, ContractType, Seniority, WorkMode
from jobboard.notify import mailer
from jobboard.notify.digest import build_digest, send_digest
from jobboard.notify.mailer import MailError, send_html_email
from jobboard.notify.settings import (
    NOTIFICATION_SETTING_KEY,
    NotificationSettings,
    load_notification_settings,
)
from jobboard.pipeline.match import MatchCriteria, MatchReport, Scored
from jobboard.pipeline.rank import Ranked


def _job(job_id: int, title: str = "Backend Developer", company: str = "Acme") -> Job:
    """Solo i campi che il digest legge davvero: titolo, azienda, luogo, id."""
    return Job(
        id=job_id,
        title=title,
        company=company,
        company_normalized=company.lower(),
        city="Milano",
        country="IT",
        work_mode=WorkMode.REMOTE,
        contract_type=ContractType.PERMANENT,
        seniority=Seniority.MID,
        salary_is_stated=False,
        ats_type=AtsType.UNKNOWN,
    )


def _scored(job_id: int, score: int, *, title: str = "Backend Developer") -> Scored:
    ranked = Ranked(job=_job(job_id, title=title), semantic=0.8, keyword=0.5, hybrid=0.7)
    # `assessment` non entra in nessuna funzione testata qui: il digest legge
    # solo `score` e `job`. Stesso `type: ignore` di `test_matching.py` per un
    # campo che il costruttore richiede ma che qui non serve popolare per davvero.
    return Scored(ranked=ranked, assessment=None, score=score, model="test")  # type: ignore[arg-type]


def _report(scored: list[Scored], new_ids: set[int]) -> MatchReport:
    report = MatchReport(criteria=MatchCriteria())
    report.scored = scored
    report.new_job_ids = new_ids
    return report


# --- build_digest -----------------------------------------------------------------


def test_niente_da_dire_non_produce_una_mail() -> None:
    report = _report([_scored(1, 80)], new_ids=set())  # non nuovo
    notifica = NotificationSettings(enabled=True, threshold=65)
    assert build_digest(report, notifica, "https://x") is None


def test_sotto_soglia_non_entra_nel_digest() -> None:
    report = _report([_scored(1, 40)], new_ids={1})
    notifica = NotificationSettings(enabled=True, threshold=65)
    assert build_digest(report, notifica, "https://x") is None


def test_un_nuovo_sopra_soglia_produce_il_digest_ordinato_per_punteggio() -> None:
    report = _report([_scored(1, 70), _scored(2, 90)], new_ids={1, 2})
    digest = build_digest(report, NotificationSettings(enabled=True, threshold=65), "https://x")
    assert digest is not None
    assert digest.count == 2
    # Il piu' alto per primo: e' quello che vale la pena leggere per primo.
    assert digest.text.index("90%") < digest.text.index("70%")
    assert "https://x/annuncio/2" in digest.html
    assert "https://x/annuncio/1" in digest.html


def test_gia_esistenti_non_ripetono_la_notifica() -> None:
    """Un `--rescore` non deve segnalare due volte lo stesso annuncio."""
    report = _report([_scored(1, 90), _scored(2, 90)], new_ids={2})
    digest = build_digest(report, NotificationSettings(enabled=True, threshold=65), "https://x")
    assert digest is not None
    assert digest.count == 1
    assert "annuncio/2" in digest.html
    assert "annuncio/1" not in digest.html


def test_titolo_html_escaped() -> None:
    """Un titolo con `<` non deve rompere il markup della mail."""
    report = _report([_scored(1, 90, title="C++ <Senior> Dev")], new_ids={1})
    digest = build_digest(report, NotificationSettings(enabled=True, threshold=65), "https://x")
    assert digest is not None
    assert "<Senior>" not in digest.html
    assert "&lt;Senior&gt;" in digest.html


# --- send_digest --------------------------------------------------------------------


def test_notifiche_spente_non_costruiscono_niente(monkeypatch: pytest.MonkeyPatch) -> None:
    chiamato = False

    def _boom(*args: Any, **kwargs: Any) -> None:
        nonlocal chiamato
        chiamato = True

    import jobboard.notify.digest as digest_mod

    monkeypatch.setattr(digest_mod, "send_html_email", _boom)
    report = _report([_scored(1, 90)], new_ids={1})
    settings = Settings(gmail_address="io@example.com", gmail_app_password=SecretStr("app-pass"))
    esito = send_digest(NotificationSettings(enabled=False, threshold=65), report, settings)
    assert esito is None
    assert chiamato is False


def test_send_digest_chiama_il_mailer_con_lo_stesso_contenuto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catturato: dict[str, Any] = {}

    def _fake_send(settings: Settings, **kwargs: Any) -> None:
        catturato.update(kwargs)

    import jobboard.notify.digest as digest_mod

    monkeypatch.setattr(digest_mod, "send_html_email", _fake_send)
    report = _report([_scored(1, 90)], new_ids={1})
    settings = Settings(gmail_address="io@example.com", gmail_app_password=SecretStr("app-pass"))
    esito = send_digest(NotificationSettings(enabled=True, threshold=65), report, settings)
    assert esito is not None
    assert catturato["to_addr"] == "io@example.com"
    assert catturato["subject"] == esito.subject


# --- settings -------------------------------------------------------------------


class _FakeSession:
    """Solo quello che ``load_notification_settings`` usa."""

    def __init__(self) -> None:
        self.store: dict[str, Setting] = {}

    def get(self, model: type[Any], key: str) -> Setting | None:
        assert model is Setting
        return self.store.get(key)

    def add(self, obj: Setting) -> None:
        self.store[obj.key] = obj

    def flush(self) -> None:
        pass


def test_al_primo_giro_i_default_vengono_dal_env() -> None:
    sessione = _FakeSession()
    preferenze = load_notification_settings(sessione, default_threshold=70, default_hour=8)  # type: ignore[arg-type]
    assert preferenze == NotificationSettings(enabled=False, threshold=70, hour=8)
    # E la riga resta per il giro dopo, cosi' un secondo `run_pipeline` non la ricrea.
    assert NOTIFICATION_SETTING_KEY in sessione.store


def test_una_volta_salvate_le_preferenze_vincono_sul_env() -> None:
    sessione = _FakeSession()
    sessione.store[NOTIFICATION_SETTING_KEY] = Setting(
        key=NOTIFICATION_SETTING_KEY,
        value={"enabled": True, "threshold": 55, "hour": 19},
    )
    preferenze = load_notification_settings(sessione, default_threshold=70, default_hour=8)  # type: ignore[arg-type]
    assert preferenze == NotificationSettings(enabled=True, threshold=55, hour=19)


def test_valori_fuori_range_vengono_riportati_dentro() -> None:
    sessione = _FakeSession()
    sessione.store[NOTIFICATION_SETTING_KEY] = Setting(
        key=NOTIFICATION_SETTING_KEY,
        value={"enabled": True, "threshold": 500, "hour": -3},
    )
    preferenze = load_notification_settings(sessione, default_threshold=70, default_hour=8)  # type: ignore[arg-type]
    assert preferenze.threshold == 100
    assert preferenze.hour == 0


# --- mailer -----------------------------------------------------------------------


class _FakeSmtp:
    """Solo i tre metodi che ``send_html_email`` chiama, per verificare l'ordine."""

    istanze: ClassVar[list[_FakeSmtp]] = []

    def __init__(self, host: str, port: int, timeout: int = 30) -> None:
        self.host = host
        self.port = port
        self.chiamate: list[str] = []
        _FakeSmtp.istanze.append(self)

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.chiamate.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.chiamate.append(f"login:{user}:{password}")

    def send_message(self, msg: Any) -> None:
        self.chiamate.append(f"send:{msg['Subject']}")


def test_send_html_email_fa_starttls_login_e_invio_in_ordine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeSmtp.istanze.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSmtp)
    settings = Settings(
        gmail_address="io@example.com",
        gmail_app_password=SecretStr("app-pass"),
        smtp_host="smtp.example.com",
        smtp_port=587,
    )
    send_html_email(settings, to_addr="io@example.com", subject="Ciao", html="<p>x</p>", text="x")
    assert len(_FakeSmtp.istanze) == 1
    fake = _FakeSmtp.istanze[0]
    assert fake.host == "smtp.example.com"
    assert fake.chiamate == ["starttls", "login:io@example.com:app-pass", "send:Ciao"]


def test_senza_credenziali_non_prova_nemmeno_a_connettersi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("non doveva connettersi senza credenziali")

    monkeypatch.setattr(mailer.smtplib, "SMTP", _boom)
    settings = Settings(gmail_address="", gmail_app_password=SecretStr(""))
    with pytest.raises(RuntimeError, match="GMAIL"):
        send_html_email(
            settings, to_addr="io@example.com", subject="Ciao", html="<p>x</p>", text="x"
        )


def test_un_guasto_smtp_diventa_mailerror(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Rotto:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise smtplib.SMTPConnectError(421, "giu'")

    monkeypatch.setattr(mailer.smtplib, "SMTP", _Rotto)
    settings = Settings(gmail_address="io@example.com", gmail_app_password=SecretStr("app-pass"))
    with pytest.raises(MailError):
        send_html_email(
            settings, to_addr="io@example.com", subject="Ciao", html="<p>x</p>", text="x"
        )
