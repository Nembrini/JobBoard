"""Le preferenze del digest: attivazione, soglia e orario (Fase 8.4).

Stesso pattern di ``pipeline.criteria.MATCHING_SETTING_KEY`` e
``pipeline.ingest.SEARCH_SETTING_KEY``: una riga ``settings`` letta con un
default al primo giro, cosi' la dashboard puo' cambiarla senza toccare
``worker/.env`` ne' riavviare il worker. La differenza e' che qui la riga
non nasce da un profilo — nasce dai valori di comportamento gia' in
``.env`` (``MATCH_THRESHOLD``, ``DAILY_RUN_HOUR``), che restano il
ripiego finche' nessuno ha ancora aperto la pagina Impostazioni.

**L'orario e' solo la preferenza, non lo scheduler.** Chi decide quando la
raccolta parte davvero e' l'attivita' di Windows Task Scheduler creata da
``setup-scheduler.cmd``, fissa alle 07:00: cambiare questo valore dalla
dashboard non la sposta. Il perche' — ``schtasks`` non ha modo di leggere
una riga di Postgres — sta in ``docs/ARCHITECTURE.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting

#: Chiave della riga ``settings`` con le preferenze di notifica.
NOTIFICATION_SETTING_KEY = "notifications"


@dataclass(frozen=True)
class NotificationSettings:
    """Cosa decide se e quando spedire il digest."""

    #: Prudente come ``DRY_RUN``: finche' nessuno lo accende dalla pagina
    #: Impostazioni, nessuna mail parte da sola.
    enabled: bool = False
    #: Punteggio minimo perche' un annuncio nuovo finisca nel digest.
    threshold: int = 65
    #: Ora preferita per la raccolta giornaliera, 0-23. Solo informativa — vedi
    #: la nota sullo scheduler sopra.
    hour: int = 7

    def to_json(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "threshold": self.threshold, "hour": self.hour}


def load_notification_settings(
    session: Session, *, default_threshold: int, default_hour: int
) -> NotificationSettings:
    """Legge le preferenze, creando la riga dai default di ``.env`` al primo giro.

    L'ordine e' lo stesso di ``load_criteria``: quello che c'e' in ``settings``
    vince perche' e' cio' che Filippo ha scelto dalla dashboard; i parametri
    passati servono solo a scrivere la prima riga.
    """
    riga = session.get(Setting, NOTIFICATION_SETTING_KEY)
    if riga is None:
        preferenze = NotificationSettings(
            enabled=False, threshold=default_threshold, hour=default_hour
        )
        session.add(
            Setting(
                key=NOTIFICATION_SETTING_KEY,
                value=preferenze.to_json(),
                description=(
                    "Digest email di fine run: attivazione, soglia e orario preferito, "
                    "modificabili dalla pagina Impostazioni"
                ),
            )
        )
        session.flush()
        return preferenze

    valori: dict[str, Any] = dict(riga.value)
    return NotificationSettings(
        enabled=bool(valori.get("enabled", False)),
        threshold=_clamp(_as_int(valori.get("threshold"), default_threshold), 0, 100),
        hour=_clamp(_as_int(valori.get("hour"), default_hour), 0, 23),
    )


def _as_int(valore: Any, ripiego: int) -> int:
    try:
        return int(valore)
    except (TypeError, ValueError):
        return ripiego


def _clamp(valore: int, minimo: int, massimo: int) -> int:
    return max(minimo, min(massimo, valore))
