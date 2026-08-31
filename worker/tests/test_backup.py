"""Test del backup CSV (Fase 10.3): solo le parti che non toccano Postgres.

``run_backup`` orchestra una lettura vera dal database e non e' testata di per
se', stesso principio di ``run_email_check`` (IMAP): quello che si prova qui e'
tutto cio' che sta a valle di una lettura gia' fatta — CSV, zip, rotazione.
"""

from __future__ import annotations

import csv
import datetime as dt
import zipfile
from pathlib import Path

from jobboard.backup import TableDump, rotate_backups, write_csv_backup, zip_backup


def test_ogni_tabella_diventa_un_csv_con_intestazione(tmp_path: Path) -> None:
    dump = {
        "job": TableDump(columns=["id", "title"], rows=[{"id": 1, "title": "Backend Engineer"}]),
        "run": TableDump(columns=["id", "status"], rows=[]),
    }
    cartella = write_csv_backup(dump, tmp_path / "20260831-030000")

    job_csv = (cartella / "job.csv").read_text(encoding="utf-8").splitlines()
    assert job_csv[0] == "id,title"
    assert job_csv[1] == "1,Backend Engineer"

    # Una tabella senza righe scrive comunque l'intestazione: e' quello che
    # dice che il backup ha coperto la tabella, non un buco silenzioso.
    run_csv = (tmp_path / "20260831-030000" / "run.csv").read_text(encoding="utf-8").splitlines()
    assert run_csv == ["id,status"]


def test_valori_none_diventano_stringa_vuota(tmp_path: Path) -> None:
    dump = {"job": TableDump(columns=["id", "city"], rows=[{"id": 1, "city": None}])}
    cartella = write_csv_backup(dump, tmp_path / "b")
    righe = list(csv.reader((cartella / "job.csv").open(encoding="utf-8")))
    assert righe == [["id", "city"], ["1", ""]]


def test_date_diventano_iso_e_json_resta_rileggibile(tmp_path: Path) -> None:
    quando = dt.datetime(2026, 8, 31, 7, 0, tzinfo=dt.UTC)
    dump = {
        "task": TableDump(
            columns=["created_at", "payload"],
            rows=[{"created_at": quando, "payload": {"match_id": 42}}],
        )
    }
    cartella = write_csv_backup(dump, tmp_path / "b")
    righe = list(csv.reader((cartella / "task.csv").open(encoding="utf-8")))
    assert righe[1][0] == quando.isoformat()
    assert righe[1][1] == '{"match_id": 42}'


def test_zip_backup_comprime_e_rimuove_la_cartella(tmp_path: Path) -> None:
    dump = {"source": TableDump(columns=["id"], rows=[{"id": 1}])}
    cartella = write_csv_backup(dump, tmp_path / "20260831-030000")

    archivio = zip_backup(cartella)

    assert archivio == tmp_path / "20260831-030000.zip"
    assert archivio.exists()
    assert not cartella.exists(), "la cartella non compressa non deve restare in giro"
    with zipfile.ZipFile(archivio) as zf:
        assert zf.namelist() == ["source.csv"]


def test_rotate_backups_tiene_solo_gli_ultimi_n(tmp_path: Path) -> None:
    nomi = ["20260101-030000", "20260102-030000", "20260103-030000", "20260104-030000"]
    for nome in nomi:
        (tmp_path / f"{nome}.zip").write_bytes(b"")

    rimossi = rotate_backups(tmp_path, keep=2)

    rimasti = sorted(p.name for p in tmp_path.glob("*.zip"))
    assert rimasti == ["20260103-030000.zip", "20260104-030000.zip"]
    assert {p.name for p in rimossi} == {"20260101-030000.zip", "20260102-030000.zip"}


def test_rotate_backups_non_tocca_niente_se_sono_gia_pochi(tmp_path: Path) -> None:
    (tmp_path / "20260101-030000.zip").write_bytes(b"")
    assert rotate_backups(tmp_path, keep=14) == []
    assert (tmp_path / "20260101-030000.zip").exists()


def test_rotate_backups_con_keep_negativo_non_cancella_nulla(tmp_path: Path) -> None:
    """Un valore di configurazione scritto male non deve svuotare la cartella."""
    (tmp_path / "20260101-030000.zip").write_bytes(b"")
    assert rotate_backups(tmp_path, keep=-1) == []
    assert (tmp_path / "20260101-030000.zip").exists()
