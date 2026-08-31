"""Backup automatico del database, come CSV — Fase 10.3.

**CSV e non ``pg_dump``.** Un dump binario sarebbe un ripristino piu' fedele,
ma richiede il client Postgres installato sulla macchina che esegue il
backup, e su Windows non e' garantito — la stessa ragione per cui questo
progetto non porta mai una dipendenza di sistema in piu' del necessario (vedi
Playwright, unica eccezione, gia' installato per l'invio candidature). Un CSV
per tabella lo scrive `csv` della libreria standard, si apre in Excel per
un controllo al volo, e un ``json.loads`` lo rilegge riga per riga se mai
servisse un ripristino a mano.

**Solo su disco locale.** Nessun bucket nuovo su Supabase Storage: quello
sarebbe un passo che solo Filippo puo' fare dalla console (vedi i
Prerequisiti in ``ROADMAP.md``), e il perimetro di questa fase e' restare
autonoma finche' non lo si decide altrimenti. La cartella `data/backups/` e'
gia' quella che contiene CV e screenshot, quindi non introduce niente di
nuovo da spiegare o da escludere da git.

**Le colonne binarie restano fuori.** ``profile.embedding`` e
``job.embedding`` sono ``bytea``: in un CSV diventerebbero byte illeggibili
che gonfiano ogni backup senza permettere nulla in piu' — nemmeno un
ripristino, perche' un embedding vecchio non e' meglio di uno ricalcolato al
prossimo `jb match`, che lo rifa' da solo quando trova la colonna nulla.

**La rotazione conta i file, non i giorni.** Uno scenario gia' documentato in
`ARCHITECTURE.md` — il PC di casa spento per settimane — non deve lasciare
zero backup solo perche' l'ultimo supera una soglia di eta'. Si tengono
sempre gli ultimi N, qualunque sia la data dell'ultimo.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import LargeBinary, select
from sqlalchemy.orm import Session

from .models import Base
from .models.base import utcnow

log = logging.getLogger(__name__)

#: Ordinabile per stringa quanto per data: la rotazione non deve interpretare
#: il nome del file, le basta un ``sorted()``.
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"


@dataclass(frozen=True)
class TableDump:
    """Una tabella esportata: colonne nell'ordine dello schema, righe come dizionari."""

    columns: list[str]
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class BackupResult:
    """Cosa e' successo, per il comando ``jb backup run``."""

    path: Path
    rows_by_table: dict[str, int]
    size_bytes: int
    removed: list[Path]

    @property
    def rows_total(self) -> int:
        return sum(self.rows_by_table.values())


def fetch_all_tables(session: Session) -> dict[str, TableDump]:
    """Ogni riga di ogni tabella del progetto, colonne binarie escluse.

    Legge da ``Base.metadata`` e non da un elenco scritto a mano: una tabella
    nuova ci finisce dentro senza che questo modulo debba saperlo, stesso
    principio di ``gen_web_schema``.
    """
    dump: dict[str, TableDump] = {}
    for tabella in Base.metadata.sorted_tables:
        colonne = [c for c in tabella.columns if not isinstance(c.type, LargeBinary)]
        righe = session.execute(select(*colonne)).mappings().all()
        dump[tabella.name] = TableDump(
            columns=[c.name for c in colonne],
            rows=[dict(riga) for riga in righe],
        )
    return dump


def _csv_value(value: Any) -> str:
    """Un valore di colonna reso testo per una cella CSV.

    Le date diventano ISO 8601, i JSONB una stringa JSON che ``json.loads``
    rilegge tale e quale, e i ``StrEnum`` il loro valore — ``str()`` su un
    ``StrEnum`` restituisce gia' quello, non ``NomeEnum.MEMBRO``.
    """
    if value is None:
        return ""
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def write_csv_backup(tables: dict[str, TableDump], destination_dir: Path) -> Path:
    """Un ``.csv`` per tabella dentro ``destination_dir``, creata se manca.

    Pura rispetto al database: prende righe gia' lette, cosi' si puo' provare
    senza Postgres — vedi ``tests/test_backup.py``.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    for nome, dump in tables.items():
        percorso = destination_dir / f"{nome}.csv"
        with percorso.open("w", newline="", encoding="utf-8") as f:
            scrittore = csv.writer(f)
            scrittore.writerow(dump.columns)
            for riga in dump.rows:
                scrittore.writerow([_csv_value(riga.get(colonna)) for colonna in dump.columns])
    return destination_dir


def zip_backup(folder: Path) -> Path:
    """Comprime i CSV della cartella in un ``.zip`` accanto a lei, poi la rimuove."""
    archivio = folder.with_suffix(".zip")
    with zipfile.ZipFile(archivio, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(folder.glob("*.csv")):
            zf.write(file, arcname=file.name)
    shutil.rmtree(folder)
    return archivio


def rotate_backups(backups_dir: Path, keep: int) -> list[Path]:
    """Cancella tutti gli archivi tranne gli ultimi ``keep``, per nome (= per data).

    Un ``keep`` negativo non cancella nulla, invece di svuotare la cartella
    per un valore di configurazione scritto male.
    """
    if keep < 0:
        return []
    archivi = sorted(backups_dir.glob("*.zip"))
    da_rimuovere = archivi[: max(0, len(archivi) - keep)]
    for file in da_rimuovere:
        file.unlink()
    return da_rimuovere


def run_backup(session: Session, *, data_dir: Path, keep: int) -> BackupResult:
    """Orchestrazione completa: legge dal database, scrive, comprime, ruota.

    Non e' testata di per se' — legge da Postgres, e questo repository non
    aggiunge test che ne abbiano bisogno senza prima costruire la fixture
    (vedi ``CLAUDE.md``) — ma ogni pezzo che compone lo e' singolarmente.
    """
    backups_dir = data_dir / "backups"
    cartella = backups_dir / utcnow().strftime(TIMESTAMP_FORMAT)

    dump = fetch_all_tables(session)
    write_csv_backup(dump, cartella)
    archivio = zip_backup(cartella)
    rimossi = rotate_backups(backups_dir, keep)

    log.info(
        "backup scritto in %s: %d tabelle, %d righe totali, %d rimossi per rotazione",
        archivio,
        len(dump),
        sum(len(d.rows) for d in dump.values()),
        len(rimossi),
    )
    return BackupResult(
        path=archivio,
        rows_by_table={nome: len(d.rows) for nome, d in dump.items()},
        size_bytes=archivio.stat().st_size,
        removed=rimossi,
    )


__all__ = [
    "TIMESTAMP_FORMAT",
    "BackupResult",
    "TableDump",
    "fetch_all_tables",
    "rotate_backups",
    "run_backup",
    "write_csv_backup",
    "zip_backup",
]
