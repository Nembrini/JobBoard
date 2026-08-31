"""Configurazione del worker, letta da ``worker/.env``.

Distinzione voluta rispetto alla tabella ``settings``: qui stanno segreti e
parametri di deploy, che cambiano solo riconfigurando la macchina. Le preferenze
che Filippo modifica dalla dashboard (soglia, orario, notifiche on/off) stanno nel
database, perche' devono essere scrivibili da Vercel.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Radice del package ``worker/``.
WORKER_ROOT = Path(__file__).resolve().parent.parent
#: Radice del repository.
REPO_ROOT = WORKER_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WORKER_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- database -------------------------------------------------------------
    #: SESSION pooler di Supabase (porta 5432): la connessione resta assegnata per tutta
    #: la sessione, quindi prepared statement e transazioni lunghe funzionano.
    #: Non l'host diretto ``db.<ref>.supabase.co``: pubblica solo un record AAAA e su
    #: una rete senza IPv6 non si risolve nemmeno.
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/jobboard"
    )
    db_echo: bool = False

    # --- storage --------------------------------------------------------------
    supabase_url: str = ""
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_storage_bucket: str = "resumes"

    # --- AI -------------------------------------------------------------------
    #: Provider degli stadi LLM. Gli embedding sono sempre locali e gratuiti,
    #: quindi questo influenza solo l'estrazione requisiti, lo scoring e il CV.
    llm_provider: Literal["gemini", "anthropic", "ollama"] = "gemini"

    #: Free tier di Google AI Studio: nessuna carta di credito richiesta.
    gemini_api_key: SecretStr = SecretStr("")
    #: Alternativa a consumo, non necessaria con il provider gemini.
    anthropic_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "http://localhost:11434"

    #: Alto volume (~40 annunci al giorno): estrazione requisiti e rubrica.
    model_scoring: str = "gemini-3.5-flash-lite"
    #: Basso volume (pochi al giorno) ma e' il documento che ti rappresenta,
    #: quindi qui si sceglie il modello migliore che il free tier consente.
    model_cv: str = "gemini-3.6-flash"
    #: Classificazione delle risposte dei recruiter (Fase 9.3). Il piano
    #: originale nominava "Haiku": con il provider attivo che e' Gemini (vedi
    #: la decisione in ``ARCHITECTURE.md`` sulla Message Batches API, §3.3),
    #: quel nome era generico per "un modello economico e veloce", non
    #: un'implementazione Anthropic. Stesso livello di ``model_scoring`` per lo
    #: stesso motivo: e' un compito a basso volume ma frequente.
    model_classify: str = "gemini-3.5-flash-lite"

    #: Sempre in locale su CPU, via fastembed. Nessuna chiamata di rete dopo il
    #: primo scaricamento. I modelli ammessi sono elencati in
    #: ``jobboard.ai.embeddings.KNOWN_MODELS``: uno fuori da quell'elenco viene
    #: rifiutato, perche' ognuno ha i suoi prefissi obbligatori.
    embedding_model: str = "intfloat/multilingual-e5-small"

    @property
    def embedding_cache_dir(self) -> Path:
        """Dove fastembed conserva il modello scaricato.

        Sotto ``data/`` e non nella cartella temporanea di sistema, che e' il suo
        default: Windows la svuota, e riscaricare mezzo giga a ogni pulizia e' tempo
        perso a ogni run.
        """
        return self.data_dir / "models"

    @property
    def llm_api_key(self) -> SecretStr:
        """Chiave del provider attivo, per non disseminare if in giro."""
        return {
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
            "ollama": SecretStr("not-needed"),
        }[self.llm_provider]

    # --- fonti ----------------------------------------------------------------
    adzuna_app_id: str = ""
    adzuna_app_key: SecretStr = SecretStr("")
    jooble_api_key: SecretStr = SecretStr("")
    rapidapi_key: SecretStr = SecretStr("")

    # --- email (dalla Fase 8, IMAP dalla Fase 9) -------------------------------
    gmail_address: str = ""
    gmail_app_password: SecretStr = SecretStr("")
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993

    # --- comportamento --------------------------------------------------------
    #: Finche' e' ``True`` nessuna candidatura raggiunge davvero un ATS: il worker
    #: simula l'invio e registra tutto. Default prudente di proposito.
    dry_run: bool = True
    daily_application_cap: int = 10
    match_threshold: int = 65
    daily_run_hour: int = 7
    task_poll_seconds: int = 30
    heartbeat_seconds: int = 30
    #: Quanti archivi di ``jb backup run`` tenere in ``data/backups/`` (Fase 10.3).
    #: Per conteggio, non per eta': un PC spento per settimane non deve
    #: ritrovarsi a zero backup solo perche' l'ultimo e' "vecchio".
    backup_keep_count: int = 14

    #: URL pubblico della dashboard, usato nei link del digest email.
    public_app_url: str = "https://job-board-official.vercel.app"

    # --- percorsi locali ------------------------------------------------------
    #: File temporanei del worker: PDF prima dell'upload, screenshot, cache del
    #: modello di embedding. Git-ignored.
    data_dir: Path = REPO_ROOT / "data"

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, v: str) -> str:
        """SQLAlchemy 2 con psycopg 3 richiede il prefisso esplicito.

        Supabase fornisce la connection string come ``postgresql://``: senza questa
        correzione SQLAlchemy proverebbe a caricare psycopg2, che non e' installato.
        """
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    @field_validator("daily_run_hour")
    @classmethod
    def _valid_hour(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError("daily_run_hour deve essere fra 0 e 23")
        return v

    @field_validator("match_threshold")
    @classmethod
    def _valid_threshold(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("match_threshold deve essere fra 0 e 100")
        return v

    def require(self, *names: str) -> None:
        """Verifica che le chiavi indicate siano valorizzate, altrimenti alza.

        Chiamata all'inizio dei comandi che ne hanno bisogno, cosi' un errore di
        configurazione si manifesta subito e con un messaggio chiaro invece che come
        un 401 a meta' della pipeline.
        """
        missing = []
        for name in names:
            value = getattr(self, name)
            actual = value.get_secret_value() if isinstance(value, SecretStr) else value
            if not actual:
                missing.append(name.upper())
        if missing:
            raise RuntimeError(
                f"Variabili d'ambiente mancanti in worker/.env: {', '.join(missing)}"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
