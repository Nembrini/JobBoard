"""Test delle preferenze di tracciamento (Fase 9): nessun database vero.

Stessa ``_FakeSession`` di ``test_notify.py`` per ``load_notification_settings``:
``load_tracking_settings`` è pura una volta tolta la sessione.
"""

from __future__ import annotations

from typing import Any

from jobboard.models import Setting
from jobboard.tracking.settings import (
    TRACKING_SETTING_KEY,
    TrackingSettings,
    load_tracking_settings,
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


def test_al_primo_giro_e_disattivo_con_il_default() -> None:
    sessione = _FakeSession()
    preferenze = load_tracking_settings(sessione, default_follow_up_after_days=10)  # type: ignore[arg-type]
    assert preferenze == TrackingSettings(enabled=False, follow_up_after_days=10)
    # E la riga resta per il giro dopo, come per le notifiche.
    assert TRACKING_SETTING_KEY in sessione.store


def test_una_volta_salvate_le_preferenze_vincono_sul_default() -> None:
    sessione = _FakeSession()
    sessione.store[TRACKING_SETTING_KEY] = Setting(
        key=TRACKING_SETTING_KEY, value={"enabled": True, "follow_up_after_days": 14}
    )
    preferenze = load_tracking_settings(sessione, default_follow_up_after_days=7)  # type: ignore[arg-type]
    assert preferenze == TrackingSettings(enabled=True, follow_up_after_days=14)


def test_giorni_fuori_range_vengono_riportati_dentro() -> None:
    sessione = _FakeSession()
    sessione.store[TRACKING_SETTING_KEY] = Setting(
        key=TRACKING_SETTING_KEY, value={"enabled": True, "follow_up_after_days": 900}
    )
    preferenze = load_tracking_settings(sessione, default_follow_up_after_days=7)  # type: ignore[arg-type]
    assert preferenze.follow_up_after_days == 60

    sessione.store[TRACKING_SETTING_KEY] = Setting(
        key=TRACKING_SETTING_KEY, value={"enabled": True, "follow_up_after_days": 0}
    )
    preferenze = load_tracking_settings(sessione, default_follow_up_after_days=7)  # type: ignore[arg-type]
    assert preferenze.follow_up_after_days == 3


def test_valore_malformato_ricade_sul_default() -> None:
    sessione = _FakeSession()
    sessione.store[TRACKING_SETTING_KEY] = Setting(
        key=TRACKING_SETTING_KEY, value={"enabled": True, "follow_up_after_days": "presto"}
    )
    preferenze = load_tracking_settings(sessione, default_follow_up_after_days=7)  # type: ignore[arg-type]
    assert preferenze.follow_up_after_days == 7
