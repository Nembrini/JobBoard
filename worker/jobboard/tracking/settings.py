"""Le preferenze del tracciamento post-candidatura (Fase 9): attivazione e giorni di silenzio.

Stesso pattern di ``notify.settings.NotificationSettings``: una riga ``settings``
letta con un default al primo giro, cosi' la dashboard puo' cambiarla senza
toccare ``worker/.env`` ne' riavviare il worker.

**Distinta dalla riga ``"notifications"``.** Quella decide se e quando parte il
digest dei nuovi annunci; questa decide se il worker legge la casella IMAP e
dopo quanti giorni di silenzio segnalare un follow-up. Sono due caselle di
scelta indipendenti — si puo' volere il digest senza il controllo email, o
viceversa — e una riga sola con due booleani avrebbe reso impossibile
distinguere "non ancora configurato" da "disattivato apposta" per l'uno senza
toccare l'altro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting

#: Chiave della riga ``settings`` con le preferenze di tracciamento.
TRACKING_SETTING_KEY = "tracking"

#: Limiti ragionevoli sul numero di giorni: sotto i 3 un follow-up arriverebbe
#: prima che un recruiter abbia anche solo letto la candidatura, sopra i 60
#: il campo perderebbe senso rispetto a chiudere la candidatura a mano.
_MIN_GIORNI = 3
_MAX_GIORNI = 60


@dataclass(frozen=True)
class TrackingSettings:
    """Cosa decide se il worker legge la posta e quando segnalare un silenzio."""

    #: Prudente come ``NotificationSettings.enabled``: finche' nessuno lo accende
    #: dalla pagina Impostazioni, nessuna connessione IMAP parte da sola.
    enabled: bool = False
    #: Giorni senza una risposta classificata prima di segnare
    #: ``follow_up_due_at`` e spedire un promemoria.
    follow_up_after_days: int = 7

    def to_json(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "follow_up_after_days": self.follow_up_after_days}


def load_tracking_settings(
    session: Session, *, default_follow_up_after_days: int = 7
) -> TrackingSettings:
    """Legge le preferenze, creando la riga dal default al primo giro.

    Stesso ordine di ``load_notification_settings``: quello che c'e' in
    ``settings`` vince perche' e' cio' che Filippo ha scelto dalla dashboard.
    """
    riga = session.get(Setting, TRACKING_SETTING_KEY)
    if riga is None:
        preferenze = TrackingSettings(
            enabled=False, follow_up_after_days=default_follow_up_after_days
        )
        session.add(
            Setting(
                key=TRACKING_SETTING_KEY,
                value=preferenze.to_json(),
                description=(
                    "Tracciamento post-candidatura: lettura IMAP delle risposte e giorni di "
                    "silenzio prima di un promemoria, modificabili dalla pagina Impostazioni"
                ),
            )
        )
        session.flush()
        return preferenze

    valori: dict[str, Any] = dict(riga.value)
    return TrackingSettings(
        enabled=bool(valori.get("enabled", False)),
        follow_up_after_days=_clamp(
            _as_int(valori.get("follow_up_after_days"), default_follow_up_after_days),
            _MIN_GIORNI,
            _MAX_GIORNI,
        ),
    )


def _as_int(valore: Any, ripiego: int) -> int:
    try:
        return int(valore)
    except (TypeError, ValueError):
        return ripiego


def _clamp(valore: int, minimo: int, massimo: int) -> int:
    return max(minimo, min(massimo, valore))
