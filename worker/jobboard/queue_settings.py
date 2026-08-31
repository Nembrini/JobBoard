"""L'interruttore dell'avvio automatico: se il tick di Task Scheduler può lavorare.

``.\\setup-scheduler`` crea "JobBoard - worker", un'attività che lancia
``jb work --once`` ogni minuto — è il meccanismo che rende automatica sia la
raccolta giornaliera (Fase 8.1/8.2, "JobBoard - trigger giornaliero" alle
07:00 accoda, "JobBoard - worker" esegue entro un minuto) sia i bottoni
"Aggiorna adesso"/"Rivaluta tutto" della dashboard: la prossima tornata prende
il task da sola, lo esegue, e il processo termina — nessun altro codice serve
per "spegnerlo", ``--once`` esce da sé a fine lavoro.

**Acceso di default.** Chi ha già eseguito ``.\\setup-scheduler`` conta da
tempo su quel tick per la raccolta di ogni mattina: un interruttore nato
spento la fermerebbe in silenzio al primo deploy di questo file, che è
l'opposto di prudente — è la sorpresa che il resto del codice evita apposta
(vedi ``notify.settings`` per il caso contrario, dove spento è il default
perché l'azione, una mail, non esisteva ancora). Qui esiste già: questa riga
è solo l'interruttore per chi lo vuole fermare senza cancellare l'attività di
Task Scheduler.

Stesso pattern di ``notify.settings.NotificationSettings`` e
``tracking.settings.TrackingSettings``: una riga ``settings`` letta con un
default al primo giro. La legge ``commands.worker``, prima di reclamare un
task, non ``queue.claim`` — un ``jb work`` lanciato a mano (``serve()``, non
``--once``) resta un'azione esplicita e non deve fermarsi per un interruttore
pensato solo per il tick automatico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

#: Chiave della riga ``settings`` con la preferenza di avvio automatico.
AUTO_WORKER_SETTING_KEY = "auto_worker"


@dataclass(frozen=True)
class AutoWorkerSettings:
    """Se il tick automatico di Task Scheduler (``jb work --once``) può reclamare un task."""

    #: Acceso di default: e' il comportamento che l'attivita' di Task Scheduler
    #: gia' ha appena creata, non una funzione nuova che va scelta per esistere.
    enabled: bool = True

    def to_json(self) -> dict[str, Any]:
        return {"enabled": self.enabled}


def load_auto_worker_settings(session: Session) -> AutoWorkerSettings:
    """Legge la preferenza, creando la riga accesa al primo giro.

    Stesso ordine di ``load_notification_settings``: quello che c'è in
    ``settings`` vince perché è ciò che Filippo ha scelto dalla dashboard.
    """
    riga = session.get(Setting, AUTO_WORKER_SETTING_KEY)
    if riga is None:
        preferenze = AutoWorkerSettings(enabled=True)
        session.add(
            Setting(
                key=AUTO_WORKER_SETTING_KEY,
                value=preferenze.to_json(),
                description=(
                    "Avvio automatico: se il tick di Task Scheduler ('JobBoard - worker', "
                    "ogni minuto) può reclamare un task dalla coda, modificabile dalla "
                    "pagina Impostazioni"
                ),
            )
        )
        session.flush()
        return preferenze

    valori: dict[str, Any] = dict(riga.value)
    return AutoWorkerSettings(enabled=bool(valori.get("enabled", True)))
