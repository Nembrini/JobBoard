"""Test della preferenza di avvio automatico: nessun database vero.

Stessa ``_FakeSession`` di ``test_tracking_settings.py`` per
``load_tracking_settings``: ``load_auto_worker_settings`` è pura una volta
tolta la sessione.
"""

from __future__ import annotations

from typing import Any

from jobboard.models import Setting
from jobboard.queue_settings import (
    AUTO_WORKER_SETTING_KEY,
    AutoWorkerSettings,
    load_auto_worker_settings,
)


class _FakeSession:
    def __init__(self) -> None:
        self.store: dict[str, Setting] = {}

    def get(self, model: type[Any], key: str) -> Setting | None:
        assert model is Setting
        return self.store.get(key)

    def add(self, obj: Setting) -> None:
        self.store[obj.key] = obj

    def flush(self) -> None:
        pass


def test_al_primo_giro_e_acceso() -> None:
    """Diverso dalle notifiche e dal tracciamento: qui il default e' acceso,
    perche' il tick di Task Scheduler che governa non e' una funzione nuova
    da scegliere, e' quello che '.\\setup-scheduler' ha gia' creato."""
    sessione = _FakeSession()
    preferenze = load_auto_worker_settings(sessione)  # type: ignore[arg-type]
    assert preferenze == AutoWorkerSettings(enabled=True)
    # E la riga resta per il giro dopo, come per le altre preferenze.
    assert AUTO_WORKER_SETTING_KEY in sessione.store


def test_una_volta_spento_vince_sul_default() -> None:
    sessione = _FakeSession()
    sessione.store[AUTO_WORKER_SETTING_KEY] = Setting(
        key=AUTO_WORKER_SETTING_KEY, value={"enabled": False}
    )
    preferenze = load_auto_worker_settings(sessione)  # type: ignore[arg-type]
    assert preferenze == AutoWorkerSettings(enabled=False)


def test_valore_malformato_ricade_sul_default_acceso() -> None:
    sessione = _FakeSession()
    sessione.store[AUTO_WORKER_SETTING_KEY] = Setting(
        key=AUTO_WORKER_SETTING_KEY, value={"altro_campo": 1}
    )
    preferenze = load_auto_worker_settings(sessione)  # type: ignore[arg-type]
    assert preferenze == AutoWorkerSettings(enabled=True)
