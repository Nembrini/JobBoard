"""Taratura dei pesi della rubrica su annunci etichettati a mano.

I pesi con cui il sistema parte — 40% requisiti obbligatori, 15% seniority, e
così via — vengono dal piano, cioè da un'ipotesi ragionevole e non da dati. Qui
si verifica quell'ipotesi contro il giudizio di Filippo su annunci veri.

Il ciclo è::

    python scripts/calibrate.py export        # scrive il CSV da compilare
    # ... si riempie la colonna "voto" con un numero da 0 a 100 ...
    python scripts/calibrate.py evaluate      # dice se i pesi attuali reggono

**Non servono nuove chiamate LLM.** I sei sotto-punteggi sono già in
``match.subscores``: cambiare i pesi è moltiplicare numeri già salvati. È
esattamente il motivo per cui la rubrica chiede sei giudizi al modello invece di
un totale.

**Trenta esempi non bastano a stimare sei parametri liberi.** La ricerca dei
pesi migliori trova sempre *qualcosa*, anche nel rumore. Per questo lo script
non si limita a stampare il vincitore: divide gli esempi in due metà, cerca su
ciascuna e verifica se il vincitore dell'una regge sull'altra. Se le due metà
non sono d'accordo, il messaggio lo dice e i pesi vanno lasciati stare.
"""

from __future__ import annotations

import csv
import itertools
from pathlib import Path
from typing import Annotated

import numpy as np
import typer
from numpy.typing import NDArray
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from jobboard.ai.rubric import NEUTRAL, RUBRIC_WEIGHTS
from jobboard.config import get_settings
from jobboard.db import session_scope
from jobboard.models import Job, Match

app = typer.Typer(help="Taratura dei pesi della rubrica.", no_args_is_help=True)
console = Console()

#: Nomi dei criteri, in un ordine fisso: le colonne del CSV e quelle della
#: matrice devono corrispondere posizione per posizione.
CRITERIA = tuple(RUBRIC_WEIGHTS)

#: Passo della griglia. Con 0.05 i pesi possibili sono 53 130 combinazioni:
#: abbastanza fini da spostare un criterio del 5%, abbastanza poche da valutarle
#: tutte in un paio di secondi.
STEP = 0.05

DEFAULT_FILE = Path("data/calibration.csv")


@app.command()
def export(
    out: Annotated[Path, typer.Option("--out", help="Dove scrivere il CSV.")] = DEFAULT_FILE,
    limit: Annotated[int, typer.Option("--limit", help="Quanti annunci esportare.")] = 30,
    min_score: Annotated[int, typer.Option("--min", help="Punteggio minimo da includere.")] = 0,
) -> None:
    """Scrive il CSV da etichettare a mano.

    Esporta di proposito anche annunci di punteggio basso: se si etichettassero
    solo i primi trenta, la taratura imparerebbe a distinguere il buono
    dall'ottimo e non saprebbe più riconoscere ciò che va scartato.
    """
    with session_scope() as session:
        righe = list(
            session.execute(
                select(Match, Job)
                .join(Job, Match.job_id == Job.id)
                .where(Match.score.is_not(None), Match.score >= min_score)
                .order_by(Match.score.desc())
                .limit(limit)
            )
        )

    if not righe:
        console.print("[red]Nessun match valutato.[/] Esegui prima: jobboard match --commit")
        raise typer.Exit(1)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["match_id", "voto", "ruolo", "azienda", "punteggio_sistema", *CRITERIA, "url"]
        )
        for match, job in righe:
            sotto = match.subscores or {}
            writer.writerow(
                [
                    match.id,
                    "",  # <- da riempire a mano
                    job.title,
                    job.company,
                    match.score,
                    *[sotto.get(nome, "") for nome in CRITERIA],
                    job.apply_url or job.url,
                ]
            )

    console.print(
        f"[green]Scritte {len(righe)} righe[/] in {out}.\n"
        "Riempi la colonna [bold]voto[/] con un numero da 0 a 100: quanto ti sembra "
        "valga la pena candidarti a quell'annuncio. Poi:\n"
        "  [bold]python scripts/calibrate.py evaluate[/]"
    )


@app.command()
def evaluate(
    file: Annotated[Path, typer.Option("--file", help="Il CSV etichettato.")] = DEFAULT_FILE,
    apply_best: Annotated[
        bool, typer.Option("--apply", help="Stampa i pesi migliori pronti da incollare.")
    ] = False,
) -> None:
    """Confronta i pesi attuali con i migliori possibili sugli esempi etichettati."""
    voti, matrice, identificativi = _read_labels(file)
    if len(voti) < 10:
        console.print(
            f"[red]Solo {len(voti)} esempi etichettati.[/] Sotto la decina qualunque "
            "risultato è rumore: compilane almeno venti."
        )
        raise typer.Exit(1)

    attuali = np.array([RUBRIC_WEIGHTS[c] for c in CRITERIA], dtype=np.float64)
    griglia = _weight_grid()

    console.print(
        f"[bold]{len(voti)}[/] esempi etichettati, {len(griglia)} combinazioni di pesi.\n"
    )

    rho_attuale = _spearman(matrice @ attuali, voti)
    _render_current(matrice, voti, attuali, rho_attuale)

    migliori, rho_migliore = _best(griglia, matrice, voti)
    _render_best(migliori, rho_migliore, rho_attuale)
    _render_stability(griglia, matrice, voti, attuali)
    _render_worst_errors(matrice, voti, attuali, identificativi)

    if apply_best:
        console.print("\n[bold]Da incollare in jobboard/ai/rubric.py:[/]")
        console.print("RUBRIC_WEIGHTS: dict[str, float] = {")
        for nome, peso in zip(CRITERIA, migliori, strict=True):
            console.print(f'    "{nome}": {peso:.2f},')
        console.print("}")


# --- lettura ------------------------------------------------------------------


def _read_labels(file: Path) -> tuple[NDArray[np.float64], NDArray[np.float64], list[str]]:
    """CSV -> voti, matrice dei sotto-punteggi, etichette leggibili."""
    if not file.exists():
        console.print(
            f"[red]{file} non esiste.[/] Esegui prima: python scripts/calibrate.py export"
        )
        raise typer.Exit(1)

    voti: list[float] = []
    righe: list[list[float]] = []
    nomi: list[str] = []

    with file.open(encoding="utf-8", newline="") as handle:
        for riga in csv.DictReader(handle):
            grezzo = (riga.get("voto") or "").strip()
            if not grezzo:
                continue  # non ancora etichettata
            try:
                voto = float(grezzo.replace(",", "."))
            except ValueError:
                console.print(f"[yellow]voto non numerico ignorato: {grezzo!r}[/]")
                continue

            # Un criterio vuoto vale neutro, la stessa convenzione di
            # ``weighted_total``: due regole diverse per lo stesso dato mancante
            # renderebbero la taratura incoerente con il sistema che tara.
            righe.append([_number(riga.get(nome), NEUTRAL) for nome in CRITERIA])
            voti.append(voto)
            nomi.append(f"{riga.get('ruolo', '?')} — {riga.get('azienda', '?')}")

    return (
        np.array(voti, dtype=np.float64),
        np.array(righe, dtype=np.float64),
        nomi,
    )


def _number(value: str | None, fallback: float) -> float:
    try:
        return float((value or "").strip())
    except ValueError:
        return fallback


# --- ricerca ------------------------------------------------------------------


def _weight_grid() -> NDArray[np.float64]:
    """Tutti i vettori di pesi non negativi che sommano a 1, a passo :data:`STEP`."""
    passi = round(1 / STEP)
    combinazioni = [
        c for c in itertools.product(range(passi + 1), repeat=len(CRITERIA)) if sum(c) == passi
    ]
    return np.array(combinazioni, dtype=np.float64) * STEP


def _best(
    griglia: NDArray[np.float64], matrice: NDArray[np.float64], voti: NDArray[np.float64]
) -> tuple[NDArray[np.float64], float]:
    previsti = matrice @ griglia.T  # (esempi, combinazioni)
    correlazioni = _spearman_columns(previsti, voti)
    vincitore = int(np.argmax(correlazioni))
    return griglia[vincitore], float(correlazioni[vincitore])


# --- statistica ---------------------------------------------------------------


def _ranks(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Ranghi medi, che è ciò che rende Spearman insensibile ai pari merito."""
    ordine = values.argsort()
    ranghi = np.empty_like(ordine, dtype=np.float64)
    ranghi[ordine] = np.arange(len(values), dtype=np.float64)

    # Ai valori uguali si assegna il rango medio: senza, l'ordine casuale di due
    # annunci con lo stesso punteggio conterebbe come un errore di previsione.
    unici, inversa = np.unique(values, return_inverse=True)
    if len(unici) < len(values):
        for indice in range(len(unici)):
            pari = inversa == indice
            ranghi[pari] = ranghi[pari].mean()
    return ranghi


def _spearman(previsti: NDArray[np.float64], voti: NDArray[np.float64]) -> float:
    """Correlazione di rango: misura l'*ordine*, che è ciò che la dashboard mostra."""
    a, b = _ranks(previsti), _ranks(voti)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _spearman_columns(
    previsti: NDArray[np.float64], voti: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Spearman di ogni colonna contro gli stessi voti, in un colpo solo."""
    return np.array([_spearman(previsti[:, i], voti) for i in range(previsti.shape[1])])


# --- resa a schermo -----------------------------------------------------------


def _render_current(
    matrice: NDArray[np.float64],
    voti: NDArray[np.float64],
    attuali: NDArray[np.float64],
    rho: float,
) -> None:
    previsti = matrice @ attuali
    errore = float(np.abs(previsti - voti).mean())

    table = Table(title="Pesi attuali", header_style="bold")
    table.add_column("Criterio")
    table.add_column("Peso", justify="right")
    table.add_column("Correlazione col voto", justify="right")
    for nome, peso in zip(CRITERIA, attuali, strict=True):
        singolo = _spearman(matrice[:, CRITERIA.index(nome)], voti)
        table.add_row(nome, f"{peso:.0%}", f"{singolo:+.2f}")
    console.print(table)
    console.print(
        f"correlazione di rango complessiva [bold]{rho:+.2f}[/], "
        f"errore medio [bold]{errore:.1f}[/] punti su 100\n"
    )


def _render_best(migliori: NDArray[np.float64], rho: float, rho_attuale: float) -> None:
    table = Table(title="Pesi migliori sugli esempi etichettati", header_style="bold")
    table.add_column("Criterio")
    table.add_column("Attuale", justify="right")
    table.add_column("Proposto", justify="right")
    for nome, proposto in zip(CRITERIA, migliori, strict=True):
        table.add_row(nome, f"{RUBRIC_WEIGHTS[nome]:.0%}", f"{proposto:.0%}")
    console.print(table)

    guadagno = rho - rho_attuale
    console.print(f"correlazione [bold]{rho:+.2f}[/] contro {rho_attuale:+.2f} ({guadagno:+.2f})")
    if guadagno < 0.05:
        console.print(
            "[green]I pesi attuali vanno bene.[/] Il guadagno è dentro il rumore di "
            "un campione di questa taglia: non toccarli."
        )


def _render_stability(
    griglia: NDArray[np.float64],
    matrice: NDArray[np.float64],
    voti: NDArray[np.float64],
    attuali: NDArray[np.float64],
) -> None:
    """Il controllo che distingue una taratura da un'illusione.

    Sei pesi liberi su trenta esempi trovano sempre una combinazione che sembra
    ottima. Se quella trovata sulla prima metà non funziona anche sulla seconda,
    ha imparato il rumore e non il criterio.
    """
    pari, dispari = np.arange(len(voti)) % 2 == 0, np.arange(len(voti)) % 2 == 1
    if pari.sum() < 5 or dispari.sum() < 5:
        return

    pesi_a, _ = _best(griglia, matrice[pari], voti[pari])
    pesi_b, _ = _best(griglia, matrice[dispari], voti[dispari])
    incrociato_a = _spearman(matrice[dispari] @ pesi_a, voti[dispari])
    incrociato_b = _spearman(matrice[pari] @ pesi_b, voti[pari])
    base_a = _spearman(matrice[dispari] @ attuali, voti[dispari])
    base_b = _spearman(matrice[pari] @ attuali, voti[pari])

    console.print(
        f"\n[bold]Controllo di stabilità[/] (pesi cercati su una metà, verificati sull'altra)\n"
        f"  metà A -> B: {incrociato_a:+.2f} contro {base_a:+.2f} dei pesi attuali\n"
        f"  metà B -> A: {incrociato_b:+.2f} contro {base_b:+.2f} dei pesi attuali"
    )
    if incrociato_a <= base_a or incrociato_b <= base_b:
        console.print(
            "[yellow]Le due metà non sono d'accordo:[/] i pesi migliori su un campione "
            "peggiorano sull'altro. Sono rumore, non un criterio. Servono più esempi."
        )
    else:
        differenza = np.abs(pesi_a - pesi_b).max()
        console.print(
            f"[green]Le due metà concordano[/] (scarto massimo fra i pesi {differenza:.0%}): "
            "la proposta è credibile."
        )


def _render_worst_errors(
    matrice: NDArray[np.float64],
    voti: NDArray[np.float64],
    attuali: NDArray[np.float64],
    nomi: list[str],
) -> None:
    """I casi su cui il sistema sbaglia di più: è lì che si capisce cosa manca."""
    errori = (matrice @ attuali) - voti
    peggiori = np.argsort(-np.abs(errori))[:5]

    table = Table(title="Dove il sistema sbaglia di più", header_style="bold")
    table.add_column("Annuncio", overflow="ellipsis", max_width=46)
    table.add_column("Voto", justify="right")
    table.add_column("Sistema", justify="right")
    table.add_column("Errore", justify="right")
    previsti = matrice @ attuali
    for indice in peggiori:
        scarto = abs(errori[indice])
        segno = "sopravvaluta" if errori[indice] > 0 else "sottovaluta"
        colore = "red" if scarto > 25 else "yellow"
        table.add_row(
            nomi[indice],
            f"{voti[indice]:.0f}",
            f"{previsti[indice]:.0f}",
            f"[{colore}]{segno} {scarto:.0f}[/]",
        )
    console.print(table)


def main() -> None:
    get_settings()  # fallisce subito e con un messaggio chiaro se .env manca
    app()


if __name__ == "__main__":
    main()
