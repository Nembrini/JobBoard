"""Il minimo di Supabase Storage che serve al worker.

La dashboard carica il CV su un bucket privato e accoda un task; qui si fa il
gesto opposto, scaricare quel file per poterlo dare al parser. Come sul lato
web, tre ``httpx`` invece della libreria ufficiale: di ``supabase-py`` servirebbe
una chiamata su una superficie che si porta dietro client Postgres, realtime e
auth, e ognuno di quelli e' una dipendenza in piu' da tenere aggiornata su una
macchina che gira di notte senza nessuno a guardarla.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Il file non c'e', il bucket non c'e', o la chiave non basta."""


def _base_and_headers() -> tuple[str, dict[str, str]]:
    settings = get_settings()
    if not settings.supabase_url:
        raise StorageError("SUPABASE_URL non impostata in worker/.env")

    chiave = settings.supabase_service_role_key.get_secret_value()
    if not chiave:
        raise StorageError("SUPABASE_SERVICE_ROLE_KEY non impostata in worker/.env")

    base = f"{settings.supabase_url.rstrip('/')}/storage/v1"
    return base, {"Authorization": f"Bearer {chiave}", "apikey": chiave}


def download(percorso: str, destinazione: Path) -> Path:
    """Scarica un oggetto dal bucket dei CV e lo scrive su disco.

    Il file finisce su disco e non in memoria perche' i parser PDF vogliono un
    percorso: ``pypdfium2`` apre un file, non un buffer, e passargli un
    temporaneo e' meno codice che adattare tutta la catena a lavorare in RAM per
    un documento da poche centinaia di kilobyte.
    """
    base, headers = _base_and_headers()
    bucket = get_settings().supabase_storage_bucket

    with httpx.stream(
        "GET", f"{base}/object/{bucket}/{percorso}", headers=headers, timeout=60
    ) as risposta:
        if risposta.status_code == 404:
            raise StorageError(f"{percorso}: non esiste nel bucket {bucket}")
        if risposta.status_code >= 400:
            raise StorageError(f"{percorso}: HTTP {risposta.status_code}")

        destinazione.parent.mkdir(parents=True, exist_ok=True)
        with destinazione.open("wb") as uscita:
            for blocco in risposta.iter_bytes():
                uscita.write(blocco)

    log.info("scaricato %s (%d byte)", percorso, destinazione.stat().st_size)
    return destinazione
