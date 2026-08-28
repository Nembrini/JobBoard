"""Test della CLI che non richiedono database ne' LLM."""

from __future__ import annotations

from typing import Any

from jobboard.cli import _force_utf8_output


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
