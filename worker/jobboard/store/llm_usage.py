"""Registro del consumo LLM — Fase 10.2.

Una riga per invocazione **aggregata**: vedi il commento su
:class:`~jobboard.models.ops.LLMUsageLog` per il perché non è una riga per
singola chiamata al modello.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LLMUsageLog
from ..models.enums import LlmUsagePurpose


def record_llm_usage(
    session: Session,
    *,
    purpose: LlmUsagePurpose,
    model: str,
    calls: int,
    input_tokens: int,
    output_tokens: int,
    reference_id: int | None = None,
    batch_id: str | None = None,
) -> None:
    """Registra un aggregato di consumo.

    Non scrive nulla se ``calls`` è zero: un ``run_pipeline`` su un profilo non
    ancora confermato, o un controllo email senza candidature in attesa,
    arrivano qui senza aver fatto nessuna chiamata, e una riga a zero
    affollerebbe la dashboard con dei "buchi" che l'assenza di righe comunica
    già da sola.
    """
    if calls <= 0:
        return
    session.add(
        LLMUsageLog(
            purpose=purpose,
            model=model,
            calls=calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reference_id=reference_id,
            batch_id=batch_id,
        )
    )


def usage_since(session: Session, since: dt.datetime) -> list[LLMUsageLog]:
    """Le righe registrate a partire da ``since``, più recenti prima.

    Usata da ``jb costs show``: il volume atteso è di poche righe al giorno
    (una per run di matching, una per CV generato, ...), quindi aggregare in
    Python il risultato di questa query basta e non serve una seconda query
    per ogni raggruppamento.
    """
    return list(
        session.scalars(
            select(LLMUsageLog)
            .where(LLMUsageLog.occurred_at >= since)
            .order_by(LLMUsageLog.occurred_at.desc())
        )
    )


__all__ = ["record_llm_usage", "usage_since"]
