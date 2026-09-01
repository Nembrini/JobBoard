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
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

# google-genai stampa due righe a OGNI chiamata a generate_content, comprese
# quelle andate a buon fine: un INFO e poi un WARNING sulla "automatic function
# calling" (AFC), che qui non e' mai in gioco — nessun metodo di questo modulo
# passa mai ``tools`` alla richiesta. Non sono filtrabili da
# ``GenerateContentConfig``, solo dalla soglia del logger che le emette. Gia'
# scambiate una volta per l'errore vero mentre il problema reale (un worker
# interrotto a meta' generate_cv, vedi ``queue._recupera_orfani``) non lasciava
# altro segno nel log: la riga scompariva col processo.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

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

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[dict[str, Any]]:
        """JSON grezzo, guidato dallo schema ma **non** validato.

        Serve quando l'output va corretto prima di poter passare la validazione:
        e' il caso della strutturazione del CV, dove gli id delle voci vengono
        assegnati in modo deterministico dal codice invece di essere lasciati al
        modello, che li produrrebbe incoerenti o duplicati.
        """


def _log_prima_di_riprovare(stato: RetryCallState) -> None:
    """Si stampa nell'attesa fra un tentativo e il successivo.

    Senza, un 503 "high demand" di Gemini e' silenzio totale per fino a ~30
    secondi filati (cinque tentativi, backoff fino a 16s ciascuno): il log si
    ferma subito dopo "tentativo N" e non riparte finche' la richiesta non
    torna. E' esattamente quello che ha prodotto il task 14 del 1 settembre
    2026 — un 503 ritentato in silenzio, con la generazione del CV rimasta
    interrotta a meta' perche' quel silenzio e' stato letto come un blocco (vedi
    ``jobboard.queue._recupera_orfani``, che ora recupera un worker morto cosi',
    ma non sostituisce il non dover sembrare morto in primo luogo).
    """
    eccezione = stato.outcome.exception() if stato.outcome else None
    log.info(
        "tentativo %d fallito (%s), riprovo tra %.0fs",
        stato.attempt_number,
        eccezione,
        stato.upcoming_sleep,
    )


#: Ritenta solo gli errori transitori, con attesa crescente. Cinque tentativi
#: distribuiti su ~30 secondi: sufficiente per un picco di carico, non tanto da
#: bloccare la pipeline se il servizio e' davvero giu'.
_retry = retry(
    retry=retry_if_exception_type(LLMTemporaryError),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    stop=stop_after_attempt(5),
    reraise=True,
    before_sleep=_log_prima_di_riprovare,
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

    @_retry
    def generate_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResult[dict[str, Any]]:
        import json

        used = model or self.settings.model_scoring
        response = self._call(prompt, used, system, temperature, schema=schema)
        raw = (response.text or "").strip()
        if not raw:
            raise LLMError(f"{used} non ha prodotto output strutturato")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{used} ha prodotto JSON non valido: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError(f"{used} ha prodotto {type(data).__name__} invece di un oggetto")
        return LLMResult(data, self._usage(response, used))

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
            config["response_schema"] = _to_gemini_schema(schema)

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


#: Parole chiave che l'API Gemini accetta in ``response_schema``. Tutto il resto
#: — a partire da ``additionalProperties``, che Pydantic emette per via di
#: ``extra="forbid"`` — fa fallire la richiesta con 400 INVALID_ARGUMENT.
_GEMINI_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "anyOf",
        "minItems",
        "maxItems",
    }
)


def _to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Traduce lo schema JSON di un modello Pydantic in quello che Gemini accetta.

    Serve perche' i due dialetti non coincidono: Pydantic produce JSON Schema
    completo, Gemini ne accetta un sottoinsieme. In particolare:

    * ``additionalProperties`` non esiste lato Gemini e fa fallire la richiesta;
    * i ``$ref`` verso ``$defs`` vanno inlineati, perche' i riferimenti non sono
      supportati;
    * ``anyOf: [T, null]``, che Pydantic genera per ogni campo opzionale,
      diventa il tipo ``T`` con ``nullable``.

    I modelli restano quindi liberi di essere severi per la *nostra*
    validazione, senza che questo vincoli il formato della richiesta.
    """
    root = model.model_json_schema()
    defs: dict[str, Any] = root.pop("$defs", {})
    converted = _convert(root, defs, seen=())
    if not isinstance(converted, dict):  # pragma: no cover - lo schema radice e' sempre un oggetto
        raise LLMError(f"schema di {model.__name__} non convertibile")
    return converted


def _convert(node: Any, defs: dict[str, Any], seen: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_convert(item, defs, seen) for item in node]
    if not isinstance(node, dict):
        return node

    if ref := node.get("$ref"):
        name = str(ref).rsplit("/", 1)[-1]
        if name in seen:
            # Schema ricorsivo: Gemini non puo' esprimerlo, si degrada a oggetto
            # libero invece di ricorrere all'infinito.
            return {"type": "object"}
        return _convert(defs.get(name, {}), defs, (*seen, name))

    # anyOf: [T, null]  ->  T nullable
    if any_of := node.get("anyOf"):
        non_null = [b for b in any_of if b.get("type") != "null"]
        if len(non_null) == 1 and len(non_null) < len(any_of):
            converted = _convert(non_null[0], defs, seen)
            if isinstance(converted, dict):
                converted["nullable"] = True
                if desc := node.get("description"):
                    converted.setdefault("description", desc)
            return converted

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties":
            # Le chiavi qui sono NOMI DI CAMPO, non parole chiave dello schema:
            # filtrarle contro _GEMINI_SCHEMA_KEYS svuoterebbe l'oggetto.
            out[key] = {name: _convert(sub, defs, seen) for name, sub in value.items()}
        elif key == "required":
            out[key] = list(value)
        else:
            out[key] = _convert(value, defs, seen)

    if desc := node.get("description"):
        out.setdefault("description", desc)
    return out


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
