"""Accesso agli LLM, dietro un'unica interfaccia.

Il resto del codice non sa quale fornitore sia attivo: chiede testo o un oggetto
Pydantic e basta. Cambiare provider e' una variabile in ``.env``.

Gli embedding non passano da qui: sono locali e gratuiti (``jobboard.ai.embeddings``).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Errore non recuperabile: chiave sbagliata, modello inesistente, prompt rifiutato."""


class LLMTemporaryError(LLMError):
    """Errore transitorio che vale la pena ritentare: 429, 500, 503, timeout.

    Esiste come classe a se' perche' i modelli piu' recenti rispondono
    regolarmente ``503 high demand``: senza retry la pipeline notturna
    fallirebbe a intermittenza senza motivo.
    """


@dataclass(frozen=True)
class LLMUsage:
    """Consumo di una chiamata, per la dashboard dei costi della Fase 10."""

    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResult[R]:
    value: R
    usage: LLMUsage


class LLMProvider(ABC):
    """Interfaccia minima: tutto quello che serve al progetto."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[str]:
        """Testo libero."""

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[T]:
        """Oggetto Pydantic validato.

        Preferito ovunque possibile: un JSON malformato diventa un errore di
        validazione qui, invece di un ``KeyError`` tre livelli piu' in la'.
        """


#: Ritenta solo gli errori transitori, con attesa crescente. Cinque tentativi
#: distribuiti su ~30 secondi: sufficiente per un picco di carico, non tanto da
#: bloccare la pipeline se il servizio e' davvero giu'.
_retry = retry(
    retry=retry_if_exception_type(LLMTemporaryError),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    stop=stop_after_attempt(5),
    reraise=True,
)


class GeminiProvider(LLMProvider):
    """Google AI Studio. Free tier, nessuna carta di credito richiesta."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from google import genai

        settings.require("gemini_api_key")
        self._client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    # -- interfaccia ---------------------------------------------------------

    @_retry
    def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[str]:
        used = model or self.settings.model_scoring
        response = self._call(prompt, used, system, temperature, schema=None)
        text = (response.text or "").strip()
        if not text:
            raise LLMError(f"{used} ha restituito una risposta vuota")
        return LLMResult(text, self._usage(response, used))

    @_retry
    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[T]:
        used = model or self.settings.model_scoring
        response = self._call(prompt, used, system, temperature, schema=schema)

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return LLMResult(parsed, self._usage(response, used))

        # Il parsing lato SDK non e' garantito: si ricade sul JSON grezzo, cosi'
        # un fallimento diventa un ValidationError leggibile e non un None.
        raw = (response.text or "").strip()
        if not raw:
            raise LLMError(f"{used} non ha prodotto output strutturato")
        return LLMResult(schema.model_validate_json(raw), self._usage(response, used))

    # -- dettagli ------------------------------------------------------------

    def _call(
        self,
        prompt: str,
        model: str,
        system: str | None,
        temperature: float,
        schema: type[BaseModel] | None,
    ) -> Any:
        from google.genai import errors, types

        config: dict[str, Any] = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_schema"] = schema

        try:
            return self._client.models.generate_content(
                model=model, contents=prompt, config=types.GenerateContentConfig(**config)
            )
        except errors.ServerError as exc:  # 5xx, incluso "high demand"
            raise LLMTemporaryError(f"{model}: {exc}") from exc
        except errors.ClientError as exc:
            # 429 e' un rate limit: transitorio. Il resto (401, 404, 400) no.
            if getattr(exc, "code", None) == 429:
                raise LLMTemporaryError(f"{model}: quota esaurita, riprovo") from exc
            raise LLMError(f"{model}: {exc}") from exc

    @staticmethod
    def _usage(response: Any, model: str) -> LLMUsage:
        u = getattr(response, "usage_metadata", None)
        return LLMUsage(
            model=model,
            input_tokens=getattr(u, "prompt_token_count", 0) or 0,
            output_tokens=getattr(u, "candidates_token_count", 0) or 0,
        )


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Istanzia il provider indicato da ``LLM_PROVIDER``."""
    settings = settings or get_settings()
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings)
    raise LLMError(
        f"provider '{settings.llm_provider}' non ancora implementato. "
        "Disponibile: gemini. Le implementazioni anthropic e ollama arrivano "
        "solo se servira' cambiare."
    )
