"""Test della CLI che non richiedono database ne' LLM."""

from __future__ import annotations

import subprocess
from typing import Any

import jobboard.cli as cli
from jobboard.cli import _force_utf8_output, _stato_attivita_pianificata


class _Stream:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reconfigure(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class _StreamWithoutReconfigure:
    """Come gli oggetti con cui pytest sostituisce stdout durante i test."""


def test_output_is_forced_to_utf8(monkeypatch: Any) -> None:
    """Regressione reale: su una console cp1252 il processo terminava.

    Non con un carattere sbagliato: con ``UnicodeEncodeError``. Bastava un nome
    d'azienda fuori dall'Europa occidentale, o un accento combinante uscito dal
    PDF di un CV.
    """
    out, err = _Stream(), _Stream()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)

    _force_utf8_output()

    assert out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_a_stream_that_cannot_be_reconfigured_is_left_alone(monkeypatch: Any) -> None:
    """Sotto pytest gli stream non hanno reconfigure: non deve essere un errore."""
    monkeypatch.setattr("sys.stdout", _StreamWithoutReconfigure())
    monkeypatch.setattr("sys.stderr", _StreamWithoutReconfigure())

    _force_utf8_output()  # non deve sollevare


class _EsitoFinto:
    """Come l'oggetto che ``subprocess.run`` restituisce, ridotto a cio' che serve."""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def test_stato_attivita_pianificata_running(monkeypatch: Any) -> None:
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _EsitoFinto("4\r\n"))
    assert _stato_attivita_pianificata("JobBoard - worker") == "Running"


def test_stato_attivita_pianificata_disabled(monkeypatch: Any) -> None:
    """Regressione reale: l'attivita' e' rimasta disabilitata un giorno e mezzo senza che
    nessun errore lo dicesse — la coda accettava i task, nessuno li raccoglieva piu'.
    Vedi ``_check_scheduler``."""
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _EsitoFinto("1\r\n"))
    assert _stato_attivita_pianificata("JobBoard - worker") == "Disabled"


def test_stato_attivita_pianificata_assente(monkeypatch: Any) -> None:
    """Output vuoto: ``Get-ScheduledTask`` non ha trovato l'attivita'."""
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _EsitoFinto(""))
    assert _stato_attivita_pianificata("JobBoard - worker") == "Missing"


def test_stato_attivita_pianificata_powershell_irraggiungibile(monkeypatch: Any) -> None:
    def _fallisce(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("powershell non trovato")

    monkeypatch.setattr(cli.subprocess, "run", _fallisce)
    assert _stato_attivita_pianificata("JobBoard - worker") is None


def test_stato_attivita_pianificata_timeout(monkeypatch: Any) -> None:
    def _timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=10)

    monkeypatch.setattr(cli.subprocess, "run", _timeout)
    assert _stato_attivita_pianificata("JobBoard - worker") is None


def test_check_scheduler_non_interroga_task_scheduler_fuori_da_windows(monkeypatch: Any) -> None:
    """Su Linux/macOS 'schtasks' non esiste: il controllo deve solo saltare, mai fallire."""
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")

    def _non_dovrebbe_essere_chiamata(nome: str) -> str | None:
        raise AssertionError("non deve interrogare Task Scheduler fuori da Windows")

    monkeypatch.setattr(cli, "_stato_attivita_pianificata", _non_dovrebbe_essere_chiamata)

    cli._check_scheduler()  # non deve sollevare
