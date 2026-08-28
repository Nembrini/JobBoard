"""Accesso agli LLM e agli embedding."""

from .client import LLMError, LLMProvider, LLMResult, LLMTemporaryError, LLMUsage, get_provider
from .embeddings import (
    KNOWN_MODELS,
    Embedder,
    EmbeddingError,
    Vector,
    cosine,
    from_bytes,
    get_embedder,
    spread,
    to_bytes,
)

__all__ = [
    "KNOWN_MODELS",
    "Embedder",
    "EmbeddingError",
    "LLMError",
    "LLMProvider",
    "LLMResult",
    "LLMTemporaryError",
    "LLMUsage",
    "Vector",
    "cosine",
    "from_bytes",
    "get_embedder",
    "get_provider",
    "spread",
    "to_bytes",
]
