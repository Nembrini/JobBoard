"""Ambiente Alembic.

L'URL del database NON viene letto da ``alembic.ini`` ma da ``jobboard.config``,
cosi' esiste un solo posto in cui la connection string e' configurata (``.env``) e
non c'e' rischio di applicare una migration al database sbagliato.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from jobboard.config import get_settings

# Import necessario: registra tutti i modelli su Base.metadata prima che Alembic
# confronti lo schema. Senza, l'autogenerate produrrebbe un DROP di ogni tabella.
from jobboard.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera l'SQL senza connettersi, per una review prima di applicarlo."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Senza questi due, Alembic ignora i cambi di tipo e di default lato
            # server, e le migration silenziosamente non riflettono i modelli.
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
