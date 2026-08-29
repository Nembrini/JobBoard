"""Genera ``web/src/db/schema.ts`` dai modelli SQLAlchemy.

Sostituisce ``drizzle-kit pull``, che su questo database va in crash: Postgres
espone i vincoli ``NOT NULL`` come pseudo-CHECK in
``information_schema.check_constraints`` (101 righe su 104) e drizzle-kit 0.31.10
non li gestisce.

Generare da ``Base.metadata`` invece che introspezionare il database mantiene la
stessa garanzia — una sola definizione dello schema, quella Python — e in piu'
produce i **tipi union degli enum**, che l'introspezione non potrebbe dedurre:
nel database quelle colonne sono semplici VARCHAR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Table,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from .config import REPO_ROOT
from .models import Base

HEADER = """// GENERATO AUTOMATICAMENTE - non modificare a mano.
//
// Sorgente: worker/jobboard/models/  ->  rigenerare con:  jobboard gen-web-schema
// Lo schema del database e' definito dai modelli SQLAlchemy e applicato con
// Alembic. Questo file esiste solo per dare i tipi al lato TypeScript.

import {
  bigint,
  boolean,
  customType,
  doublePrecision,
  integer,
  jsonb,
  pgTable,
  serial,
  smallint,
  text,
  timestamp,
  varchar,
} from "drizzle-orm/pg-core";

// drizzle-orm non ha un tipo bytea nativo. Qui ci finiscono gli embedding,
// serializzati con numpy.tobytes(): il lato web non li legge mai, ma la colonna
// deve esistere perche' i tipi corrispondano alla tabella reale.
const bytea = customType<{ data: Buffer; driverData: Buffer }>({
  dataType: () => "bytea",
});
"""


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.capitalize() for w in rest)


def _pascal(name: str) -> str:
    return "".join(w.capitalize() for w in name.split("_"))


def _ts_literal(value: Any) -> str | None:
    """Rappresentazione TS di un default, o ``None`` se non esprimibile."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is dict:
        return "{}"
    if value is list:
        return "[]"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    return None


def _column_expr(col: Column[Any]) -> tuple[str, str | None]:
    """Ritorna (espressione drizzle, nome del tipo enum se la colonna e' un enum)."""
    t = col.type
    db_name = f'"{col.name}"'
    enum_type: str | None = None

    if isinstance(t, SAEnum):
        # Nel database e' VARCHAR: il tipo union lo aggiungiamo noi lato TS.
        enum_type = _pascal(t.name or col.name)
        expr = f"varchar({db_name}, {{ length: 32 }}).$type<{enum_type}>()"
    elif isinstance(t, SmallInteger):
        expr = f"smallint({db_name})"
    elif isinstance(t, BigInteger):
        expr = f'bigint({db_name}, {{ mode: "number" }})'
    elif isinstance(t, Integer):
        # Le chiavi primarie intere sono SERIAL: senza serial() drizzle le
        # considererebbe obbligatorie in inserimento.
        expr = f"serial({db_name})" if col.primary_key else f"integer({db_name})"
    elif isinstance(t, ARRAY):
        expr = f"text({db_name}).array()"
    elif isinstance(t, JSONB):
        expr = f"jsonb({db_name})"
    elif isinstance(t, String) and t.length:
        expr = f"varchar({db_name}, {{ length: {t.length} }})"
    elif isinstance(t, Text | String):
        expr = f"text({db_name})"
    elif isinstance(t, Boolean):
        expr = f"boolean({db_name})"
    elif isinstance(t, DateTime):
        tz = "true" if getattr(t, "timezone", False) else "false"
        expr = f'timestamp({db_name}, {{ withTimezone: {tz}, mode: "date" }})'
    elif isinstance(t, Float):
        expr = f"doublePrecision({db_name})"
    elif isinstance(t, LargeBinary):
        expr = f"bytea({db_name})"
    else:  # pragma: no cover - tipo nuovo non ancora mappato
        raise TypeError(f"tipo non mappato: {col.table.name}.{col.name} -> {t!r}")

    if col.primary_key:
        expr += ".primaryKey()"
    if not col.nullable and not col.primary_key:
        expr += ".notNull()"

    # Un default rende la colonna opzionale in inserimento anche lato TS.
    #
    # **Solo il `server_default` conta**, mai il `default=` dell'ORM. Il secondo
    # e' lato Python: lo applica SQLAlchemy al flush e nel DDL non finisce mai.
    # Copiarlo qui produceva un `.default()` che il database non aveva, e
    # Drizzle — che per una colonna con default scrive la parola chiave `default`
    # nella VALUES — chiedeva a Postgres un valore inesistente. Il risultato era
    # un `null value in column "progress" violates not-null constraint` sulla
    # prima INSERT arrivata da Vercel. Vedi la migration ``d5b3e97c1a08``.
    if col.server_default is not None:
        if isinstance(t, DateTime):
            expr += ".defaultNow()"
        else:
            literal = _ts_literal(getattr(col.default, "arg", None))
            if literal is not None:
                expr += f".default({literal})"

    return expr, enum_type


def _render_table(table: Table) -> tuple[str, set[str]]:
    lines = [f'export const {_camel(table.name)} = pgTable("{table.name}", {{']
    enums: set[str] = set()
    for col in table.columns:
        expr, enum_type = _column_expr(col)
        if enum_type:
            enums.add(enum_type)
        lines.append(f"  {_camel(col.name)}: {expr},")
    lines.append("});")
    const, cls = _camel(table.name), _pascal(table.name)
    lines.append(f"export type {cls}Row = typeof {const}.$inferSelect;")
    lines.append(f"export type New{cls} = typeof {const}.$inferInsert;")
    return "\n".join(lines), enums


def _render_enums() -> str:
    """Tipi union per ogni enum usato in una colonna, con i valori reali."""
    seen: dict[str, list[str]] = {}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, SAEnum):
                name = _pascal(col.type.name or col.name)
                seen.setdefault(name, [e.value for e in col.type.enum_class or []])
    out = ["// Valori ammessi, gli stessi imposti dai vincoli CHECK nel database."]
    for name in sorted(seen):
        values = " | ".join(f'"{v}"' for v in seen[name])
        out.append(f"export type {name} = {values};")
    return "\n".join(out)


def generate() -> str:
    parts = [HEADER, "", _render_enums(), ""]
    for table in Base.metadata.sorted_tables:
        rendered, _ = _render_table(table)
        parts.extend([rendered, ""])
    return "\n".join(parts)


def write(path: Path | None = None) -> Path:
    target = path or (REPO_ROOT / "web" / "src" / "db" / "schema.ts")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate(), encoding="utf-8")
    return target


#: Le tabelle attese, per il messaggio di riepilogo della CLI.
def table_count() -> int:
    return len(Base.metadata.sorted_tables)


__all__ = ["generate", "table_count", "write"]
