"""Test dello schema che non richiedono un database.

Girano in CI e in locale prima di avere Supabase configurato: verificano che i
modelli compilino a DDL Postgres valido e che le invarianti su cui il resto del
sistema fa affidamento siano davvero espresse nello schema.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy import Enum as SAEnum
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


def test_every_enum_column_has_a_check_constraint() -> None:
    """Ogni colonna enum deve essere validata dal database.

    Regressione reale: ``Enum(create_constraint=...)`` vale ``False`` di default da
    SQLAlchemy 1.4. Senza passarlo esplicitamente le colonne enum finiscono come
    VARCHAR liberi e un valore fuori elenco viene scritto senza che nessuno se ne
    accorga — un ``'Pending'`` al posto di ``'pending'`` renderebbe un task
    invisibile al consumer per sempre.
    """
    missing = []
    for table in Base.metadata.sorted_tables:
        checks = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        for col in table.columns:
            if isinstance(col.type, SAEnum):
                expected = f"ck_{table.name}_{col.type.name}"
                if expected not in checks:
                    missing.append(f"{table.name}.{col.name} (atteso {expected})")
    assert not missing, "colonne enum senza vincolo CHECK: " + ", ".join(missing)


def test_ogni_default_dell_orm_ha_anche_un_default_sul_database() -> None:
    """Un ``default=`` senza ``server_default=`` e' una colonna che rompe da Vercel.

    Regressione reale, e costosa da diagnosticare. Il ``default=`` di SQLAlchemy
    vive **solo nell'ORM**: lo applica il flush, e nel DDL non finisce mai. Finche'
    a scrivere era solo il worker non si vedeva nulla; la prima ``INSERT`` arrivata
    dalla dashboard — Drizzle, che per una colonna con default scrive la parola
    chiave ``default`` nella ``VALUES`` — e' morta con

        null value in column "progress" of relation "task"
        violates not-null constraint

    e non era un caso isolato: erano trentacinque colonne su tutto lo schema.
    Riguarda ogni tabella in cui la dashboard scrivera' — ``task`` nella Fase 5,
    ``application`` nella Fase 7.

    Le colonne nullable restano fuori: li' l'assenza di default significa NULL, che
    e' un valore legittimo e spesso quello giusto.
    """
    mancanti = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if col.primary_key or col.nullable:
                continue
            if col.default is not None and col.server_default is None:
                mancanti.append(f"{table.name}.{col.name}")

    assert not mancanti, (
        "colonne NOT NULL con default solo lato ORM: "
        + ", ".join(mancanti)
        + " — aggiungere server_default=default_sql(...), altrimenti ogni INSERT "
        "che non passa dall'ORM fallisce sul NOT NULL"
    )
