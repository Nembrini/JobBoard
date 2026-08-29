"""Base dichiarativa, mixin comuni e helper per le colonne ricorrenti."""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convenzione di naming esplicita: senza questa, Alembic genera vincoli con nomi
# autogenerati da Postgres che non e' poi in grado di droppare in una downgrade.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _constraint_name(enum_cls: type[StrEnum]) -> str:
    """``TaskStatus`` -> ``task_status``. Alimenta ``%(constraint_name)s``."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", enum_cls.__name__).lower()


def enum_column(enum_cls: type[StrEnum], **kwargs: Any) -> Mapped[Any]:
    """Colonna per un :class:`StrEnum`, persistita come VARCHAR + CHECK.

    ``create_constraint`` va passato esplicitamente: da SQLAlchemy 1.4 il default
    e' ``False``, quindi senza questa riga la colonna sarebbe un VARCHAR libero e
    un valore fuori dall'enum verrebbe scritto senza che nessuno se ne accorga.

    Vedi la nota in ``enums.py`` sul perche' non si usano gli ENUM nativi.

    Un ``default=`` porta con se' anche il ``server_default`` corrispondente. Non
    e' una comodita': il ``default=`` di SQLAlchemy vive **solo nell'ORM**, e una
    ``INSERT`` che non passa di li' — quelle che la dashboard su Vercel manda con
    Drizzle — finisce contro il ``NOT NULL`` senza valore. Vedi la migration
    ``d5b3e97c1a08``, scritta dopo che era successo davvero.
    """
    predefinito = kwargs.get("default")
    if predefinito is not None and "server_default" not in kwargs:
        kwargs["server_default"] = text(f"'{predefinito.value}'")

    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            create_constraint=True,
            name=_constraint_name(enum_cls),
            values_callable=lambda e: [m.value for m in e],
            length=32,
        ),
        **kwargs,
    )


def default_sql(valore: str) -> Any:
    """Scorciatoia leggibile per i ``server_default`` letterali.

    Esiste per rendere ovvio, a chi aggiunge una colonna, che accanto al
    ``default=`` dell'ORM ne serve uno del database. Vedi ``enum_column``.
    """
    return text(valore)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class TimestampMixin:
    """``created_at`` / ``updated_at`` gestiti dal database."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
