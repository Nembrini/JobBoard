"""Comando ``cv``: genera a mano il CV su misura per un annuncio.

Serve a due cose che dalla dashboard non si fanno: provare il generatore su un
annuncio scelto **senza caricare niente sul bucket** (``--no-upload``), e vedere
il documento sul disco mentre si tara il template.

Il lavoro vero lo fa :func:`jobboard.cv.generate.generate`, lo stesso codice che
esegue il task accodato dalla dashboard: due strade non devono poter produrre due
CV diversi dallo stesso annuncio.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from ..db import session_scope
from ..models import Job, Match

if TYPE_CHECKING:
    from ..cv.generate import GeneratedCV

console = Console()
cv_app = typer.Typer(
    name="cv",
    help="CV su misura: generazione, anteprima, verifica ATS.",
    no_args_is_help=True,
)


@cv_app.command("generate")
def generate_command(
    match_id: Annotated[int, typer.Argument(help="Id del match, da 'jobboard matches list'.")],
    upload_pdf: Annotated[
        bool,
        typer.Option("--upload/--no-upload", help="Carica anche su Supabase Storage."),
    ] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="Dove scrivere il PDF. Default: data/cv/.")
    ] = None,
    lingua: Annotated[
        str | None,
        typer.Option("--lang", help="Forza la lingua (it/en/de/es/fr) invece di dedurla."),
    ] = None,
) -> None:
    """Genera il CV su misura per un annuncio gia' valutato."""
    from ..ai.client import get_provider
    from ..config import get_settings
    from ..cv.generate import GenerationError, generate, storage_path_for
    from ..store import load_applicant_info, load_profile

    settings = get_settings()

    with session_scope() as session:
        match = session.get(Match, match_id)
        if match is None:
            console.print(f"[red]Il match {match_id} non esiste.[/]")
            raise typer.Exit(1)
        job = session.get(Job, match.job_id)
        if job is None:  # pragma: no cover - la FK lo impedisce
            console.print("[red]L'annuncio di questo match non esiste piu'.[/]")
            raise typer.Exit(1)

        salvato = load_profile(session)
        if salvato is None:
            console.print("[red]Nessun profilo: esegui prima 'jobboard profile import'.[/]")
            raise typer.Exit(1)
        if not salvato.reviewed:
            console.print(
                "[red]Il profilo non e' confermato.[/] Rivedilo nella pagina CV della "
                "dashboard, oppure esegui 'jobboard profile load'."
            )
            raise typer.Exit(1)
        profilo = salvato.profile
        gaps = list(match.gaps or [])
        pool_salvato = load_applicant_info(session)
        pool = pool_salvato.bank if pool_salvato else None

    destinazione = out or (settings.data_dir / "cv" / f"match-{match_id}.pdf")
    console.print(
        f"Annuncio [bold]{job.title}[/] — {job.company}\n"
        f"Profilo di {profilo.contact.full_name}, {len(profilo.experiences)} esperienze"
    )

    try:
        risultato = generate(
            get_provider(settings),
            profilo,
            job,
            destinazione,
            gaps=gaps,
            lingua=lingua,
            applicant_info=pool,
            settings=settings,
        )
    except GenerationError as exc:
        # Il messaggio elenca le affermazioni respinte: e' l'informazione utile,
        # perche' dice se il problema e' il modello o il profilo.
        console.print(f"\n[red]CV rifiutato dal validatore:[/] {exc}")
        raise typer.Exit(1) from exc

    _render_esito(risultato, destinazione)

    if upload_pdf:
        from ..store.objects import upload

        percorso = storage_path_for(job.id, profilo)
        upload(percorso, risultato.pdf)
        console.print(f"[green]caricato:[/] {percorso}")
    else:
        console.print(
            "[yellow]--no-upload: il PDF resta solo sul disco.[/] "
            "Ripeti con [bold]--upload[/] per metterlo nel bucket."
        )


def _render_esito(risultato: GeneratedCV, destinazione: Path) -> None:
    tabella = Table(title="CV generato", header_style="bold")
    tabella.add_column("Voce")
    tabella.add_column("Valore", overflow="fold")

    pagine = str(risultato.pagine)
    tabella.add_row("Pagine", pagine if risultato.pagine == 1 else f"[red]{pagine}[/]")
    tabella.add_row("Lingua", risultato.lingua)
    tabella.add_row("Tentativi", str(risultato.tentativi))
    tabella.add_row("Compressioni", str(risultato.fit.compressioni))
    tabella.add_row("Densita'", f"{risultato.fit.densita.punto}pt")
    tabella.add_row("Chiamate LLM", str(risultato.llm_calls))
    tabella.add_row("Token", f"{risultato.input_tokens} in / {risultato.output_tokens} out")
    tabella.add_row("Keyword", ", ".join(risultato.cv.top_keywords[:5]))
    tabella.add_row("Bullet", str(risultato.cv.bullet_count()))
    tabella.add_row("Parole", str(risultato.cv.word_count()))
    tabella.add_row("File", str(destinazione))
    console.print(tabella)

    for tentativo, violazioni in enumerate(risultato.violazioni_corrette, start=1):
        # Non sono errori: sono tentativi respinti e poi corretti. Vale la pena
        # vederli, perche' se il modello sbaglia sempre lo stesso punto la
        # correzione sta nel prompt, non in un tentativo in piu'.
        console.print(f"\n[yellow]tentativo {tentativo} respinto:[/]")
        for violazione in violazioni:
            console.print(f"  · {violazione}")

    for violazioni in risultato.fit.compressioni_scartate:
        console.print("\n[yellow]una compressione e' stata scartata perche' inventava:[/]")
        for violazione in violazioni:
            console.print(f"  · {violazione}")

    if risultato.pagine > 1:
        console.print(
            f"\n[red]Il CV occupa {risultato.pagine} pagine.[/] "
            "Il contenuto e' piu' di quanto ne regga una: conviene guardare il "
            "MasterProfile, non il template."
        )


@cv_app.command("check")
def check_command(
    pdf: Annotated[Path, typer.Argument(help="Il PDF da verificare.")],
) -> None:
    """Verifica un PDF come lo vedrebbe un parser ATS.

    Non sostituisce un ATS vero, ma coglie i due guasti che rendono un CV
    invisibile: nessun testo estraibile (e' un'immagine) e sezioni che il parser
    non riesce a riconoscere.
    """
    from ..cv.render import HEADINGS, extract_text, page_count

    if not pdf.is_file():
        console.print(f"[red]{pdf} non esiste.[/]")
        raise typer.Exit(1)

    pagine = page_count(pdf)
    testo = extract_text(pdf)

    console.print(f"Pagine: [bold]{pagine}[/]" + ("" if pagine == 1 else " [red](più di una)[/]"))
    console.print(f"Caratteri estraibili: [bold]{len(testo)}[/]")

    if len(testo) < 200:
        console.print(
            "[red]Testo quasi assente.[/] Per un ATS questo PDF e' un foglio bianco: "
            "probabilmente e' stato prodotto come immagine."
        )
        raise typer.Exit(1)

    alto = testo.upper()
    riconosciute = {
        lingua: [v for k, v in headings.items() if k != "in_corso" and v.upper() in alto]
        for lingua, headings in HEADINGS.items()
    }
    lingua, trovate = max(riconosciute.items(), key=lambda voce: len(voce[1]))
    console.print(f"Sezioni riconosciute ({lingua}): [bold]{', '.join(trovate) or 'nessuna'}[/]")

    if len(trovate) < 3:
        console.print(
            "[yellow]Poche sezioni riconoscibili.[/] Un parser ATS segmenta il documento "
            "sugli heading: senza, legge tutto come un blocco unico."
        )
        raise typer.Exit(1)

    console.print("[green]Il PDF e' leggibile da un parser ATS.[/]")
