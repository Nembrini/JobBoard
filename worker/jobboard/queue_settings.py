"""Gli interruttori delle tre attività di Task Scheduler create da ``setup-scheduler.cmd``.

``.\\setup-scheduler`` crea tre attività — "JobBoard - worker" (``jb work
--once`` ogni minuto), "JobBoard - trigger giornaliero" (``jb work trigger
--scheduled`` alle 07:00) e "JobBoard - backup notturno" (``jb backup run
--scheduled`` alle 03:00) — ed è il meccanismo che rende automatici sia i
bottoni "Aggiorna adesso"/"Rivaluta tutto" della dashboard sia la raccolta e
il backup di ogni giorno. Ognuna delle tre resta incondizionata una volta
creata: ``schtasks`` non ha modo di leggere una riga di Postgres prima di
agire, quindi ogni riga qui è solo l'interruttore per fermarla dalla pagina
Impostazioni senza cancellare l'attività di Windows.

**Acceso di default, per tutti e tre.** Chi ha già eseguito
``.\\setup-scheduler`` conta da tempo su quei tick: un interruttore nato spento
fermerebbe in silenzio, al primo deploy di questo file, un'automazione già in
uso — la sorpresa che il resto del codice evita apposta (vedi ``notify.settings``
per il caso contrario, dove spento è il default perché l'azione, una mail, non
esisteva ancora).

**Letto solo dall'invocazione automatica, mai da quella manuale.** ``--once``
lo legge sempre (è *solo* il tick automatico); ``trigger`` e ``backup run``
lo leggono **soltanto** con ``--scheduled``, il flag che ``setup-scheduler.cmd``
passa nell'azione delle due attività giornaliere. Lanciati a mano in un
terminale, senza quel flag, restano un'azione esplicita di Filippo e non si
fermano per un interruttore pensato solo per il tick automatico — altrimenti
"fai un backup prima di una migration rischiosa" potrebbe non succedere senza
una ragione visibile a chi ha appena digitato il comando.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .models import Setting

#: Chiavi delle tre righe ``settings``, una per attività di Task Scheduler.
AUTO_WORKER_SETTING_KEY = "auto_worker"
TRIGGER_SETTING_KEY = "scheduled_trigger"
BACKUP_SETTING_KEY = "scheduled_backup"


def _carica_interruttore(session: Session, key: str, description: str) -> bool:
    """Legge un interruttore, creando la riga accesa al primo giro.

    Motore comune ai tre interruttori del modulo: stessa forma di riga
    (``{"enabled": bool}``), stesso default acceso, stessa tolleranza a un
    valore malformato o a un campo mancante. Quello che li distingue è solo la
    chiave e la frase che la pagina Impostazioni mostra accanto allo switch.
    """
    riga = session.get(Setting, key)
    if riga is None:
        session.add(Setting(key=key, value={"enabled": True}, description=description))
        session.flush()
        return True

    valori: dict[str, Any] = dict(riga.value)
    return bool(valori.get("enabled", True))


@dataclass(frozen=True)
class AutoWorkerSettings:
    """Se il tick automatico di Task Scheduler (``jb work --once``) può reclamare un task."""

    enabled: bool = True


def load_auto_worker_settings(session: Session) -> AutoWorkerSettings:
    """Legge la preferenza di "JobBoard - worker", creando la riga accesa al primo giro."""
    return AutoWorkerSettings(
        enabled=_carica_interruttore(
            session,
            AUTO_WORKER_SETTING_KEY,
            "Avvio automatico: se il tick di Task Scheduler ('JobBoard - worker', "
            "ogni minuto) può reclamare un task dalla coda, modificabile dalla "
            "pagina Impostazioni",
        )
    )


@dataclass(frozen=True)
class TriggerSettings:
    """Se il tick giornaliero (``jb work trigger --scheduled``) accoda la raccolta."""

    enabled: bool = True


def load_trigger_settings(session: Session) -> TriggerSettings:
    """Legge la preferenza di "JobBoard - trigger giornaliero", creando la riga al primo giro."""
    return TriggerSettings(
        enabled=_carica_interruttore(
            session,
            TRIGGER_SETTING_KEY,
            "Raccolta giornaliera: se 'JobBoard - trigger giornaliero' (07:00) accoda "
            "da solo un run_pipeline, modificabile dalla pagina Impostazioni",
        )
    )


@dataclass(frozen=True)
class BackupSettings:
    """Se il tick notturno (``jb backup run --scheduled``) esegue davvero il backup."""

    enabled: bool = True


def load_backup_settings(session: Session) -> BackupSettings:
    """Legge la preferenza di "JobBoard - backup notturno", creando la riga al primo giro."""
    return BackupSettings(
        enabled=_carica_interruttore(
            session,
            BACKUP_SETTING_KEY,
            "Backup notturno: se 'JobBoard - backup notturno' (03:00) esporta davvero "
            "il database, modificabile dalla pagina Impostazioni",
        )
    )
