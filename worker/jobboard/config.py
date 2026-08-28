"""Configurazione del worker, letta da ``worker/.env``.

Distinzione voluta rispetto alla tabella ``settings``: qui stanno segreti e
parametri di deploy, che cambiano solo riconfigurando la macchina. Le preferenze
che Filippo modifica dalla dashboard (soglia, orario, notifiche on/off) stanno nel
database, perche' devono essere scrivibili da Vercel.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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
    anthropic_api_key: SecretStr = SecretStr("")
    #: Alto volume, basso costo: estrazione requisiti e scoring della rubrica.
    model_scoring: str = "claude-haiku-4-5-20251001"
    #: Basso volume, qualita' massima: riscrittura del CV.
    model_cv: str = "claude-opus-5"
    embedding_model: str = "intfloat/multilingual-e5-small"

    # --- fonti ----------------------------------------------------------------
    adzuna_app_id: str = ""
    adzuna_app_key: SecretStr = SecretStr("")
    jooble_api_key: SecretStr = SecretStr("")
    rapidapi_key: SecretStr = SecretStr("")

    # --- email (dalla Fase 8) -------------------------------------------------
    gmail_address: str = ""
    gmail_app_password: SecretStr = SecretStr("")
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"

    # --- comportamento --------------------------------------------------------
    #: Finche' e' ``True`` nessuna candidatura raggiunge davvero un ATS: il worker
    #: simula l'invio e registra tutto. Default prudente di proposito.
    dry_run: bool = True
    daily_application_cap: int = 10
    match_threshold: int = 65
    daily_run_hour: int = 7
    task_poll_seconds: int = 30
    heartbeat_seconds: int = 30

    #: URL pubblico della dashboard, usato nei link del digest email.
    public_app_url: str = "http://localhost:3000"

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
