"""CLI del worker.

Punto d'ingresso per l'uso manuale e per Windows Task Scheduler. La dashboard non
chiama mai questi comandi direttamente: accoda un :class:`~jobboard.models.Task` e
il consumer lo raccoglie.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .commands import (
    apply_app,
    backup_app,
    candidate_app,
    costs_app,
    cv_app,
    email_app,
    info_app,
    ingest_command,
    match_command,
    matches_app,
    profile_app,
    sources_app,
    work_app,
)
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
app.add_typer(info_app)
app.add_typer(sources_app)
app.add_typer(matches_app)
app.add_typer(cv_app)
app.add_typer(apply_app)
app.add_typer(work_app)
app.add_typer(email_app)
app.add_typer(costs_app)
app.add_typer(backup_app)
app.command(name="ingest")(ingest_command)
app.command(name="match")(match_command)
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

    def row(name: str, valore: str, detail: str = "") -> None:
        stato, nota = _stato_segreto(valore)
        table.add_row(name, stato, "; ".join(x for x in (nota, detail) if x))

    # Segreti: si riporta solo se sono valorizzati, mai il valore. Della connection
    # string si mostra solo la parte dopo la '@', che non contiene la password.
    db_host = (
        settings.database_url.split("@")[-1] if "@" in settings.database_url else "(default locale)"
    )
    row(
        "DATABASE_URL",
        "" if "localhost" in settings.database_url else settings.database_url,
        db_host,
    )
    # Si controlla solo la chiave del provider attivo: le altre sono irrilevanti.
    row(
        f"{settings.llm_provider.upper()}_API_KEY",
        settings.llm_api_key.get_secret_value(),
        f"provider attivo: {settings.llm_provider}",
    )
    row("SUPABASE_URL", settings.supabase_url, settings.supabase_url)
    row("SUPABASE_SERVICE_ROLE_KEY", settings.supabase_service_role_key.get_secret_value())
    row("ADZUNA_APP_ID", settings.adzuna_app_id)
    row("ADZUNA_APP_KEY", settings.adzuna_app_key.get_secret_value())
    row("JOOBLE_API_KEY", settings.jooble_api_key.get_secret_value())
    row("RAPIDAPI_KEY", settings.rapidapi_key.get_secret_value(), "per JSearch")
    row("GMAIL_APP_PASSWORD", settings.gmail_app_password.get_secret_value(), "dalla Fase 8")

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
    behaviour.add_row("BACKUP_KEEP_COUNT", str(settings.backup_keep_count))
    console.print(behaviour)

    if check_db:
        _check_database()
        _check_auto_worker()
        _check_task_orfani()

    _check_embedding()
    _check_playwright()
    _check_scheduler()


def _stato_segreto(valore: str) -> tuple[str, str]:
    """Giudica un valore di configurazione dalla sua *forma*, non dalla presenza.

    Un `bool(valore)` non basta, e per due volte non e' bastato. Il tranello sta
    nel formato di ``.env``: python-dotenv riconosce un commento in coda solo
    quando davanti c'e' un valore. Scrivere

        RAPIDAPI_KEY=            # per JSearch

    non lascia la variabile vuota — le assegna il commento. La chiave risulta
    quindi "presente", supera ogni controllo, e l'API risponde 403 mandando a
    cercare il problema dalla parte sbagliata. E' successo con AUTH_SECRET e poi
    con RAPIDAPI_KEY; la terza volta tocchera' a GMAIL_APP_PASSWORD, che nel
    file ha la stessa forma.

    Nessun segreto vero contiene spazi o comincia per '#': tanto basta.
    """
    if not valore:
        return "[red]MANCANTE[/]", ""
    if valore.lstrip().startswith("#") or "#" in valore:
        return "[red]E' UN COMMENTO[/]", "il valore e' il commento della riga: spostalo sopra"
    if any(c.isspace() for c in valore):
        return "[yellow]SOSPETTO[/]", "contiene spazi: virgolette o commento rimasti dentro?"
    return "[green]OK[/]", ""


def _check_database() -> None:
    from sqlalchemy import text

    from .db import get_engine

    try:
        with get_engine().connect() as conn:
            server = conn.execute(text("select version()")).scalar_one()
        console.print(f"[green]Database raggiungibile[/] — {str(server).split(',')[0]}")
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        console.print(f"[red]Database non raggiungibile[/] — {type(exc).__name__}: {exc}")


def _check_auto_worker() -> None:
    """Verifica l'interruttore ``auto_worker`` scritto dalla pagina Impostazioni.

    Spento, ``jb work --once`` (il tick di Task Scheduler) non reclama nessun
    task e non scrive nemmeno il battito — lo stesso effetto pratico di
    un'attività disabilitata in Task Scheduler, ma acceso da un click sulla
    pagina Impostazioni invece che da Windows, e altrettanto silenzioso da
    qui: nessun errore, solo una coda che non si svuota più.
    """
    from .db import session_scope
    from .queue_settings import load_auto_worker_settings

    try:
        with session_scope() as session:
            preferenza = load_auto_worker_settings(session)
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        console.print(
            f"[yellow]Impossibile leggere l'avvio automatico[/] — {type(exc).__name__}: {exc}"
        )
        return

    if preferenza.enabled:
        console.print(
            "[green]Avvio automatico acceso[/] — 'JobBoard - worker' può reclamare i task"
        )
    else:
        console.print(
            "[red]Avvio automatico spento[/] nella pagina Impostazioni — 'JobBoard - worker' "
            "gira ogni minuto ma non reclama nulla. Riaccendilo in Impostazioni > Avvio automatico."
        )


def _check_task_orfani() -> None:
    """Segnala un task rimasto ``running`` piu' a lungo del credibile.

    ``jb work`` lo recupera gia' da solo al giro successivo (vedi
    ``queue._recupera_orfani``): questo controllo serve solo a farlo vedere
    subito a chi guarda ``jb doctor``, invece di lasciarlo scoprire da una
    barra di progresso ferma in dashboard.
    """
    from .queue import TASK_ORFANO_DOPO, _task_orfani

    try:
        orfani = _task_orfani()
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        console.print(f"[yellow]Impossibile controllare la coda[/] — {type(exc).__name__}: {exc}")
        return

    if not orfani:
        console.print("[green]Nessun task abbandonato in coda[/]")
        return

    minuti = int(TASK_ORFANO_DOPO.total_seconds() // 60)
    for riga in orfani:
        console.print(
            f"[yellow]Task #{riga.id} ({riga.task_type}) e' 'running' da piu' di "
            f"{minuti} minuti[/] — 'jb work' lo rimette in coda da solo al prossimo giro"
        )


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


#: Le tre attivita' che ``setup-scheduler.cmd`` crea, con il motivo per cui ciascuna
#: conta: se manca o e' disabilitata non e' un problema di configurazione del
#: worker, e' un problema di chi la deve raccogliere.
_ATTIVITA_SCHEDULATE = (
    (
        "JobBoard - worker",
        "consumer della coda ogni minuto — senza, i bottoni della dashboard non fanno nulla",
    ),
    ("JobBoard - trigger giornaliero", "raccolta automatica alle 07:00"),
    ("JobBoard - backup notturno", "backup CSV alle 03:00"),
)

#: ``TaskState`` di .NET (``Get-ScheduledTask``), stabile a prescindere dalla lingua
#: di Windows. Il testo di ``schtasks`` invece e' localizzato — su
#: un'installazione italiana stampa "Disabilitata", non "Disabled" — quindi non e'
#: quello da cui leggere uno stato in un programma.
_STATI_TASK_SCHEDULER = {
    "0": "Unknown",
    "1": "Disabled",
    "2": "Queued",
    "3": "Ready",
    "4": "Running",
}


def _stato_attivita_pianificata(nome: str) -> str | None:
    """Lo stato di un'attivita' di Task Scheduler, o ``None`` se non si riesce a saperlo.

    ``None`` copre sia PowerShell irraggiungibile sia un timeout: in entrambi i
    casi non c'e' niente da dire con sicurezza, e ``doctor`` deve poterlo
    segnalare come "non verificato" invece di spacciarlo per "assente".
    """
    try:
        risultato = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-ScheduledTask -TaskName '{nome}' "
                "-ErrorAction SilentlyContinue).State.value__",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    valore = risultato.stdout.strip()
    if not valore:
        return "Missing"
    return _STATI_TASK_SCHEDULER.get(valore, "Unknown")


def _check_scheduler() -> None:
    """Verifica che le attivita' create da ``setup-scheduler.cmd`` esistano e siano attive.

    E' il controllo che sarebbe servito il giorno in cui "JobBoard - worker" e'
    rimasto disabilitato per un giorno e mezzo senza che nessun errore lo dicesse:
    la dashboard accodava normalmente i task dei suoi bottoni, ma nessun processo
    li raccoglieva piu', e in dashboard l'unico sintomo era un pallino offline
    facile da leggere come "il PC e' spento" invece che "l'attivita' e' spenta". Un
    prerequisito silenzioso come Playwright o l'embedding, controllato allo stesso
    modo — e altrettanto inutile da controllare a meta' della pipeline notturna.

    Solo Windows: Task Scheduler non esiste altrove, e le attivita' le crea solo
    ``setup-scheduler.cmd``, anche lui Windows-only.
    """
    if platform.system() != "Windows":
        return

    for nome, ruolo in _ATTIVITA_SCHEDULATE:
        stato = _stato_attivita_pianificata(nome)
        if stato is None:
            console.print(
                f"[yellow]Impossibile verificare l'attivita' di Task Scheduler[/] {nome!r} "
                "— controllala a mano in Utilita' di pianificazione."
            )
        elif stato == "Missing":
            console.print(
                f"[red]Attivita' di Task Scheduler assente[/] — {nome!r} ({ruolo}). "
                "Esegui: [bold].\\setup-scheduler[/]"
            )
        elif stato == "Disabled":
            console.print(
                f"[red]Attivita' di Task Scheduler disabilitata[/] — {nome!r} ({ruolo}). "
                "Riabilitala in Utilita' di pianificazione, o con: "
                f'schtasks /change /tn "{nome}" /enable'
            )
        else:
            console.print(f"[green]Attivita' di Task Scheduler attiva[/] — {nome!r} ({ruolo})")


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
def run(
    once: Annotated[bool, typer.Option("--once", help="Esegue una volta e termina.")] = False,
) -> None:
    """Pipeline completa: ingest, dedup, matching, notifiche. [Fase 8]"""
    raise typer.Exit(_not_implemented("run", "Fase 8"))


def _not_implemented(command: str, phase: str) -> int:
    console.print(f"[yellow]'{command}' non e' ancora implementato — arriva con la {phase}.[/]")
    return 1


if __name__ == "__main__":
    app()
