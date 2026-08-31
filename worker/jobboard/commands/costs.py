"""Comandi ``costs``: consumo token e costo stimato dei modelli LLM (Fase 10.2).

Legge quello che ``jobboard.store.llm_usage.record_llm_usage`` ha già scritto
dai gestori — nessun calcolo nuovo qui, solo aggregazione per la lettura.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..ai.pricing import ModelPrice, estimate_cost, load_pricing, save_price
from ..db import session_scope
from ..models.base import utcnow
from ..store import usage_since

console = Console()

costs_app = typer.Typer(
    name="costs",
    help="Consumo token e costo stimato dei modelli LLM.",
    no_args_is_help=True,
)
price_app = typer.Typer(
    name="price",
    help="Prezzo per milione di token, per modello — usato per stimare il costo.",
    no_args_is_help=True,
)
costs_app.add_typer(price_app)


@dataclass
class _Aggregato:
    purpose: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    days: set[dt.date] = field(default_factory=set)


@costs_app.command("show")
def show(
    days: Annotated[
        int, typer.Option("--days", "-d", help="Quanti giorni indietro considerare.")
    ] = 30,
) -> None:
    """Token e costo stimato per scopo e modello, negli ultimi N giorni."""
    da = utcnow() - dt.timedelta(days=days)
    with session_scope() as session:
        righe = usage_since(session, da)
        prezzi = load_pricing(session)

    if not righe:
        console.print(f"[yellow]Nessun consumo registrato negli ultimi {days} giorni.[/]")
        return

    aggregati: dict[tuple[str, str], _Aggregato] = {}
    for riga in righe:
        chiave = (riga.purpose.value, riga.model)
        agg = aggregati.setdefault(chiave, _Aggregato(purpose=riga.purpose.value, model=riga.model))
        agg.calls += riga.calls
        agg.input_tokens += riga.input_tokens
        agg.output_tokens += riga.output_tokens
        agg.days.add(riga.occurred_at.date())

    tabella = Table(title=f"Consumo LLM — ultimi {days} giorni", header_style="bold")
    tabella.add_column("Scopo")
    tabella.add_column("Modello")
    tabella.add_column("Chiamate", justify="right")
    tabella.add_column("Token in", justify="right")
    tabella.add_column("Token out", justify="right")
    tabella.add_column("Giorni attivi", justify="right")
    tabella.add_column("Costo stimato", justify="right")

    totali_per_valuta: dict[str, float] = defaultdict(float)
    costo_ignoto = False
    for agg in sorted(aggregati.values(), key=lambda a: (a.purpose, a.model)):
        stima = estimate_cost(prezzi, agg.model, agg.input_tokens, agg.output_tokens)
        if stima is None:
            costo_ignoto = True
            costo_testo = "[dim]n.d.[/]"
        else:
            valore, valuta = stima
            totali_per_valuta[valuta] += valore
            costo_testo = f"{valore:.4f} {valuta}"
        tabella.add_row(
            agg.purpose,
            agg.model,
            str(agg.calls),
            str(agg.input_tokens),
            str(agg.output_tokens),
            str(len(agg.days)),
            costo_testo,
        )
    console.print(tabella)

    if totali_per_valuta:
        for valuta, valore in sorted(totali_per_valuta.items()):
            console.print(f"Totale stimato ({valuta}): [bold]{valore:.4f}[/]")
    if costo_ignoto:
        console.print(
            '[dim]"n.d." per i modelli senza un prezzo impostato — vedi '
            "[bold]jb costs price set[/]. Come la RAL non dichiarata: mai una stima al "
            "posto di un dato mancante.[/]"
        )


@price_app.command("set")
def price_set(
    model: Annotated[str, typer.Argument(help="Nome del modello, es. gemini-3.5-flash-lite.")],
    input_per_million: Annotated[
        float, typer.Option("--input", help="Prezzo per 1M di token in ingresso.")
    ],
    output_per_million: Annotated[
        float, typer.Option("--output", help="Prezzo per 1M di token in uscita.")
    ],
    currency: Annotated[str, typer.Option("--currency", help="Valuta del prezzo.")] = "USD",
) -> None:
    """Registra il prezzo di un modello, letto dalla console del provider.

    Senza questo comando ogni costo resta "n.d.": nessun prezzo e' incluso nel
    codice, per lo stesso motivo per cui la RAL stimata non finisce mai nella
    colonna di quella dichiarata (vedi CLAUDE.md).
    """
    with session_scope() as session:
        save_price(session, model, ModelPrice(input_per_million, output_per_million, currency))
    console.print(
        f"[green]Prezzo salvato[/] per {model}: {input_per_million:g}/{output_per_million:g} "
        f"{currency} per milione di token (input/output)."
    )


@price_app.command("list")
def price_list() -> None:
    """I prezzi configurati finora."""
    with session_scope() as session:
        prezzi = load_pricing(session)

    if not prezzi:
        console.print(
            "[yellow]Nessun prezzo impostato.[/] Ogni costo in "
            '[bold]jb costs show[/] risulta "n.d.".'
        )
        return

    tabella = Table(title="Prezzi configurati", header_style="bold")
    tabella.add_column("Modello")
    tabella.add_column("Input / 1M", justify="right")
    tabella.add_column("Output / 1M", justify="right")
    tabella.add_column("Valuta")
    for modello, prezzo in sorted(prezzi.items()):
        tabella.add_row(
            modello,
            f"{prezzo.input_per_million:g}",
            f"{prezzo.output_per_million:g}",
            prezzo.currency,
        )
    console.print(tabella)


__all__ = ["costs_app"]
