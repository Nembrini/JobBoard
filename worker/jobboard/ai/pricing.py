"""Prezzo per milione di token, per modello — Fase 10.2.

**Nessun prezzo e' scritto qui a memoria.** I nomi dei modelli in ``config.py``
(``gemini-3.5-flash-lite``, ``gemini-3.6-flash``) sono successivi a questo
codice: un listino sbagliato sarebbe peggio di nessun listino, perche'
sembrerebbe un dato invece di un'invenzione. Stessa regola della RAL non
dichiarata (vedi ``CLAUDE.md``): **se il prezzo non e' stato impostato, il
costo e' "n.d.", mai una stima.** Filippo lo registra a mano con
``jb costs price set``, leggendolo dalla console del provider attivo — l'unico
posto dove è verificabile davvero, e cambia nel tempo.

I prezzi vivono nella tabella ``settings`` (chiave ``"llm_pricing"``), stesso
posto e stesso pattern di ``notify.settings`` e ``tracking.settings``: una riga
JSONB che la dashboard potrebbe un giorno esporre, oggi scritta solo da CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting

#: Chiave della riga ``settings`` con i prezzi configurati.
PRICING_SETTING_KEY = "llm_pricing"


@dataclass(frozen=True)
class ModelPrice:
    """Prezzo per un milione di token, in ingresso e in uscita."""

    input_per_million: float
    output_per_million: float
    currency: str = "USD"


def load_pricing(session: Session) -> dict[str, ModelPrice]:
    """I prezzi configurati, per nome di modello. Vuoto se nessuno lo e' ancora."""
    riga = session.get(Setting, PRICING_SETTING_KEY)
    if riga is None:
        return {}

    prezzi: dict[str, ModelPrice] = {}
    for modello, dati in dict(riga.value or {}).items():
        if not isinstance(dati, dict):
            continue
        try:
            prezzi[modello] = ModelPrice(
                input_per_million=float(dati["input_per_million"]),
                output_per_million=float(dati["output_per_million"]),
                currency=str(dati.get("currency") or "USD"),
            )
        except (KeyError, TypeError, ValueError):
            # Una riga scritta a mano male non deve far esplodere l'intera
            # dashboard dei costi: quel modello risulta semplicemente senza
            # prezzo, come se nessuno l'avesse mai impostato.
            continue
    return prezzi


def save_price(session: Session, model: str, price: ModelPrice) -> None:
    """Registra (o aggiorna) il prezzo di un modello, senza toccare gli altri."""
    riga = session.get(Setting, PRICING_SETTING_KEY)
    valori: dict[str, Any] = dict(riga.value) if riga is not None else {}
    valori[model] = {
        "input_per_million": price.input_per_million,
        "output_per_million": price.output_per_million,
        "currency": price.currency,
    }

    if riga is None:
        session.add(
            Setting(
                key=PRICING_SETTING_KEY,
                value=valori,
                description=(
                    "Prezzo per milione di token in ingresso/uscita, per modello — "
                    "impostato a mano con 'jb costs price set', letto dalla console del "
                    "provider. Un modello assente da qui resta a costo 'n.d.'."
                ),
            )
        )
    else:
        # JSONB non traccia le mutazioni in-place: senza riassegnare l'intero
        # dizionario l'UPDATE non parte, stesso tranello di ``matches criteria``.
        riga.value = valori


def estimate_cost(
    prices: dict[str, ModelPrice], model: str, input_tokens: int, output_tokens: int
) -> tuple[float, str] | None:
    """Il costo stimato (valore, valuta), o ``None`` se il modello non ha un prezzo.

    Mai un ripiego su un prezzo "simile": due nomi di modello diversi hanno
    quasi sempre tariffe diverse, e un costo stimato con il prezzo sbagliato
    sarebbe piu' fuorviante di un "n.d." onesto.
    """
    prezzo = prices.get(model)
    if prezzo is None:
        return None
    costo = (
        input_tokens / 1_000_000 * prezzo.input_per_million
        + output_tokens / 1_000_000 * prezzo.output_per_million
    )
    return costo, prezzo.currency


__all__ = ["PRICING_SETTING_KEY", "ModelPrice", "estimate_cost", "load_pricing", "save_price"]
