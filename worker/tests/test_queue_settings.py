"""Test delle preferenze delle tre attività di Task Scheduler: nessun database vero.

Stessa ``_FakeSession`` di ``test_tracking_settings.py`` per
``load_tracking_settings``: ogni ``load_*_settings`` di questo modulo è pura
una volta tolta la sessione.
"""

from __future__ import annotations

from typing import Any

import pytest

from jobboard.models import Setting
from jobboard.queue_settings import (
    AUTO_WORKER_SETTING_KEY,
    BACKUP_SETTING_KEY,
    TRIGGER_SETTING_KEY,
    AutoWorkerSettings,
    BackupSettings,
    TriggerSettings,
    load_auto_worker_settings,
    load_backup_settings,
    load_trigger_settings,
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


#: Le tre coppie (chiave, funzione di lettura, classe) — stesso comportamento
#: per tutte e tre, quindi un solo set di test parametrizzato invece di tre
#: copie che potrebbero divergere alla prima correzione.
_INTERRUTTORI = [
    pytest.param(
        AUTO_WORKER_SETTING_KEY, load_auto_worker_settings, AutoWorkerSettings, id="worker"
    ),
    pytest.param(TRIGGER_SETTING_KEY, load_trigger_settings, TriggerSettings, id="trigger"),
    pytest.param(BACKUP_SETTING_KEY, load_backup_settings, BackupSettings, id="backup"),
]


@pytest.mark.parametrize(("key", "carica", "tipo"), _INTERRUTTORI)
def test_al_primo_giro_e_acceso(key: str, carica: Any, tipo: Any) -> None:
    """Diverso dalle notifiche e dal tracciamento: qui il default e' acceso,
    perche' il tick di Task Scheduler che governa non e' una funzione nuova
    da scegliere, e' quello che '.\\setup-scheduler' ha gia' creato."""
    sessione = _FakeSession()
    preferenze = carica(sessione)
    assert preferenze == tipo(enabled=True)
    # E la riga resta per il giro dopo, come per le altre preferenze.
    assert key in sessione.store


@pytest.mark.parametrize(("key", "carica", "tipo"), _INTERRUTTORI)
def test_una_volta_spento_vince_sul_default(key: str, carica: Any, tipo: Any) -> None:
    sessione = _FakeSession()
    sessione.store[key] = Setting(key=key, value={"enabled": False})
    preferenze = carica(sessione)
    assert preferenze == tipo(enabled=False)


@pytest.mark.parametrize(("key", "carica", "tipo"), _INTERRUTTORI)
def test_valore_malformato_ricade_sul_default_acceso(key: str, carica: Any, tipo: Any) -> None:
    sessione = _FakeSession()
    sessione.store[key] = Setting(key=key, value={"altro_campo": 1})
    preferenze = carica(sessione)
    assert preferenze == tipo(enabled=True)


def test_le_tre_chiavi_sono_distinte() -> None:
    """Spegnere un'attività non deve poter spegnere le altre per sbaglio."""
    assert len({AUTO_WORKER_SETTING_KEY, TRIGGER_SETTING_KEY, BACKUP_SETTING_KEY}) == 3
