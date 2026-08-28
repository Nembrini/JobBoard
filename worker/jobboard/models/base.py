"""Base dichiarativa, mixin comuni e helper per le colonne ricorrenti."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, MetaData, func
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


def enum_column(enum_cls: type[StrEnum], **kwargs: Any) -> Mapped[Any]:
    """Colonna per un :class:`StrEnum`, persistita come VARCHAR + CHECK.

    Vedi la nota in ``enums.py`` sul perche' non si usano gli ENUM nativi.
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
            length=32,
        ),
        **kwargs,
    )


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
