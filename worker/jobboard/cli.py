"""CLI del worker.

Punto d'ingresso per l'uso manuale e per Windows Task Scheduler. La dashboard non
chiama mai questi comandi direttamente: accoda un :class:`~jobboard.models.Task` e
il consumer lo raccoglie.
"""

from __future__ import annotations

import platform
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .commands import candidate_app, profile_app
from .config import get_settings


def _force_utf8_output() -> None:
    """Scrive sempre in UTF-8, qualunque codepage abbia la console.

    Su Windows Python apre stdout con la codepage locale — ``cp1252`` quando
    l'output e' rediretto o il comando gira da Task Scheduler. Stampare un
    carattere che quella tabella non contiene non produce un ``?``: solleva
    ``UnicodeEncodeError`` e **termina il processo**. In un progetto che tratta
    annunci in mezza Europa e' questione di giorni: basta un'azienda ceca, un
    nome polacco o un accento combinante uscito dal PDF di un CV.

    ``errors="replace"`` copre il caso residuo di testo malformato: e' preferibile
    un carattere sbagliato a una run notturna che muore a meta'.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # pytest sostituisce gli stream con oggetti propri
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_output()

app = typer.Typer(
    name="jobboard",
    help="Worker locale: ingest annunci, matching, generazione CV, candidature.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(profile_app)
app.add_typer(candidate_app)
console = Console()


@app.command()
def version() -> None:
    """Stampa la versione del worker."""
    console.print(f"jobboard-worker [bold]{__version__}[/] su Python {platform.python_version()}")


@app.command()
def doctor(
    check_db: Annotated[
        bool, typer.Option("--db/--no-db", help="Verifica anche la connessione al database.")
    ] = True,
) -> None:
    """Verifica configurazione e prerequisiti.

    Da eseguire dopo ogni modifica a ``.env``: fa emergere subito un errore di
    configurazione, invece di lasciarlo esplodere a meta' della pipeline notturna.
    """
    settings = get_settings()

    table = Table(title="Configurazione", show_header=True, header_style="bold")
    table.add_column("Voce")
    table.add_column("Stato")
    table.add_column("Dettaglio", overflow="fold")

    def row(name: str, ok: bool, detail: str = "") -> None:
        table.add_row(name, "[green]OK[/]" if ok else "[red]MANCANTE[/]", detail)

    # Segreti: si riporta solo se sono valorizzati, mai il valore. Della connection
    # string si mostra solo la parte dopo la '@', che non contiene la password.
    db_host = (
        settings.database_url.split("@")[-1] if "@" in settings.database_url else "(default locale)"
    )
    row("DATABASE_URL", "localhost" not in settings.database_url, db_host)
    # Si controlla solo la chiave del provider attivo: le altre sono irrilevanti.
    row(
        f"{settings.llm_provider.upper()}_API_KEY",
        bool(settings.llm_api_key.get_secret_value()),
        f"provider attivo: {settings.llm_provider}",
    )
    row("SUPABASE_URL", bool(settings.supabase_url), settings.supabase_url)
    row("SUPABASE_SERVICE_ROLE_KEY", bool(settings.supabase_service_role_key.get_secret_value()))
    row("ADZUNA_APP_ID", bool(settings.adzuna_app_id))
    row("ADZUNA_APP_KEY", bool(settings.adzuna_app_key.get_secret_value()))
    row("JOOBLE_API_KEY", bool(settings.jooble_api_key.get_secret_value()))
    row("RAPIDAPI_KEY", bool(settings.rapidapi_key.get_secret_value()), "per JSearch")
    row("GMAIL_APP_PASSWORD", bool(settings.gmail_app_password.get_secret_value()), "dalla Fase 8")

    console.print(table)

    behaviour = Table(title="Comportamento", show_header=True, header_style="bold")
    behaviour.add_column("Parametro")
    behaviour.add_column("Valore")
    behaviour.add_row(
        "DRY_RUN",
        "[yellow]true — nessuna candidatura viene inviata davvero[/]"
        if settings.dry_run
        else "[red]false — le candidature partono per davvero[/]",
    )
    behaviour.add_row("LLM_PROVIDER", settings.llm_provider)
    behaviour.add_row("MODEL_SCORING", settings.model_scoring)
    behaviour.add_row("MODEL_CV", settings.model_cv)
    behaviour.add_row("EMBEDDING_MODEL", settings.embedding_model)
    behaviour.add_row("DAILY_APPLICATION_CAP", str(settings.daily_application_cap))
    behaviour.add_row("MATCH_THRESHOLD", str(settings.match_threshold))
    behaviour.add_row("DAILY_RUN_HOUR", f"{settings.daily_run_hour:02d}:00")
    behaviour.add_row("TASK_POLL_SECONDS", str(settings.task_poll_seconds))
    console.print(behaviour)

    if check_db:
        _check_database()

    _check_embedding()
    _check_playwright()


def _check_database() -> None:
    from sqlalchemy import text

    from .db import get_engine

    try:
        with get_engine().connect() as conn:
            server = conn.execute(text("select version()")).scalar_one()
        console.print(f"[green]Database raggiungibile[/] — {str(server).split(',')[0]}")
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        console.print(f"[red]Database non raggiungibile[/] — {type(exc).__name__}: {exc}")


def _check_embedding() -> None:
    """Verifica il modello di embedding **senza scaricarlo**.

    Il primo scaricamento e' di alcune centinaia di MB: farlo partire da un comando
    diagnostico sarebbe una sorpresa sgradevole, quindi qui si guarda solo la cache.
    """
    from .ai.embeddings import KNOWN_MODELS

    settings = get_settings()
    if settings.embedding_model not in KNOWN_MODELS:
        console.print(
            f"[red]EMBEDDING_MODEL sconosciuto[/] — {settings.embedding_model}. "
            f"Ammessi: {', '.join(sorted(KNOWN_MODELS))}"
        )
        return

    cache = settings.embedding_cache_dir
    folder = f"models--{settings.embedding_model.replace('/', '--')}"
    if (cache / folder).exists():
        console.print(f"[green]Modello di embedding gia' in cache[/] — {cache / folder}")
    else:
        console.print(
            f"[yellow]Modello di embedding da scaricare[/] — {settings.embedding_model}, "
            "circa 450 MB da scaricare al primo uso"
        )


def _check_playwright() -> None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            version = browser.version
            browser.close()
        console.print(f"[green]Playwright Chromium disponibile[/] — {version}")
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        console.print(
            f"[red]Playwright non pronto[/] — {type(exc).__name__}. "
            "Esegui: [bold]python -m playwright install chromium[/]"
        )


@app.command(name="gen-web-schema")
def gen_web_schema() -> None:
    """Rigenera ``web/src/db/schema.ts`` dai modelli SQLAlchemy.

    Da eseguire dopo ogni ``alembic upgrade head``. Sostituisce
    ``drizzle-kit pull``, che su questo database va in crash sui vincoli NOT NULL
    che Postgres espone come pseudo-CHECK.
    """
    from .gen_web_schema import table_count, write

    target = write()
    console.print(
        f"[green]Scritte {table_count()} tabelle[/] in {target.relative_to(target.parents[3])}"
    )


@app.command()
def ingest(
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--commit", help="Stampa senza scrivere sul database.")
    ] = True,
    source: Annotated[
        str | None, typer.Option("--source", help="Limita a un singolo adapter.")
    ] = None,
) -> None:
    """Raccoglie annunci dalle fonti attive. [Fase 2]"""
    raise typer.Exit(_not_implemented("ingest", "Fase 2"))


@app.command()
def match() -> None:
    """Calcola i punteggi di compatibilita' sugli annunci non ancora valutati. [Fase 3]"""
    raise typer.Exit(_not_implemented("match", "Fase 3"))


@app.command()
def run(
    once: Annotated[bool, typer.Option("--once", help="Esegue una volta e termina.")] = False,
) -> None:
    """Pipeline completa: ingest, dedup, matching, notifiche. [Fase 8]"""
    raise typer.Exit(_not_implemented("run", "Fase 8"))


@app.command()
def worker() -> None:
    """Avvia il consumer della coda e lo scheduler. [Fase 5]"""
    raise typer.Exit(_not_implemented("worker", "Fase 5"))


def _not_implemented(command: str, phase: str) -> int:
    console.print(f"[yellow]'{command}' non e' ancora implementato — arriva con la {phase}.[/]")
    return 1


if __name__ == "__main__":
    app()
