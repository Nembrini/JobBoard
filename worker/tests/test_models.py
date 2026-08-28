"""Test dello schema che non richiedono un database.

Girano in CI e in locale prima di avere Supabase configurato: verificano che i
modelli compilino a DDL Postgres valido e che le invarianti su cui il resto del
sistema fa affidamento siano davvero espresse nello schema.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from jobboard.models import Base, Seniority
from jobboard.models.enums import TIER_A_ATS, AtsType

DIALECT = postgresql.dialect()

EXPECTED_TABLES = {
    "application",
    "application_event",
    "candidate_profile",
    "job",
    "job_requirements",
    "job_source_link",
    "match",
    "profile",
    "run",
    "settings",
    "source",
    "task",
    "worker_heartbeat",
}


def test_all_tables_registered() -> None:
    """Alembic autogenera da Base.metadata: una tabella non importata verrebbe droppata."""
    assert set(Base.metadata.tables) == EXPECTED_TABLES


@pytest.mark.parametrize("table", Base.metadata.sorted_tables, ids=lambda t: str(t.name))
def test_table_compiles_to_postgres_ddl(table: object) -> None:
    ddl = str(CreateTable(table).compile(dialect=DIALECT))  # type: ignore[arg-type]
    assert ddl.strip().startswith("CREATE TABLE")


def test_indexes_compile() -> None:
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=DIALECT)).startswith("CREATE")


def test_task_polling_index_is_partial() -> None:
    """L'indice di polling deve restare parziale sui soli pending.

    Senza il predicato crescerebbe indefinitamente su righe done/failed che la
    query di polling non guardera' mai piu'.
    """
    index = next(i for i in Base.metadata.tables["task"].indexes if i.name == "ix_task_pending")
    ddl = str(CreateIndex(index).compile(dialect=DIALECT))
    assert "WHERE status = 'pending'" in ddl


@pytest.mark.parametrize("table_name", ["profile", "candidate_profile", "worker_heartbeat"])
def test_singleton_constraint(table_name: str) -> None:
    """Le tabelle singleton devono impedire una seconda riga a livello di database."""
    table = Base.metadata.tables[table_name]
    checks = [c for c in table.constraints if c.__class__.__name__ == "CheckConstraint"]
    assert any("id = 1" in str(c.sqltext) for c in checks), (  # type: ignore[attr-defined]
        f"{table_name} non ha il vincolo singleton"
    )


def test_application_is_idempotent_per_match() -> None:
    """Un match non puo' generare due candidature: e' la garanzia di idempotenza."""
    assert Base.metadata.tables["application"].c.match_id.unique is True


def test_job_source_link_unique_per_source() -> None:
    """Lo stesso annuncio dalla stessa fonte non deve duplicarsi."""
    table = Base.metadata.tables["job_source_link"]
    uniques = [c for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({"source_id", "external_id"} == {col.name for col in c.columns} for c in uniques)


def test_seniority_ranks_are_ordered() -> None:
    """Il filtro "entro +/-1 livello" dello Stadio 0 dipende da questo ordinamento."""
    ordered = [
        Seniority.INTERN,
        Seniority.JUNIOR,
        Seniority.MID,
        Seniority.SENIOR,
        Seniority.LEAD,
        Seniority.PRINCIPAL,
    ]
    ranks = [s.rank for s in ordered]
    assert ranks == sorted(ranks)
    assert Seniority.UNKNOWN.rank == -1, "UNKNOWN non deve entrare nei confronti di distanza"


def test_tier_a_ats_are_known_types() -> None:
    assert set(AtsType) >= TIER_A_ATS
    assert AtsType.WORKDAY not in TIER_A_ATS, "Workday non ha un endpoint di apply pubblico"
