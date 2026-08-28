"""Fonti di annunci.

Importare questo package popola il registry: ogni modulo di adapter si iscrive
da sé con ``@register``. Aggiungerne uno significa creare il modulo e aggiungerlo
all'elenco qui sotto — non c'è nessun altro posto da toccare.
"""

from . import adzuna, arbeitnow, ats, jooble, jsearch, remoteok, remotive  # noqa: F401
from .base import (
    HttpClient,
    RawJob,
    SearchQuery,
    SourceAdapter,
    SourceError,
    SourceTemporaryError,
    all_adapter_classes,
    get_adapter_class,
    register,
)

__all__ = [
    "HttpClient",
    "RawJob",
    "SearchQuery",
    "SourceAdapter",
    "SourceError",
    "SourceTemporaryError",
    "all_adapter_classes",
    "get_adapter_class",
    "register",
]
