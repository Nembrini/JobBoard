"""Estrazione, riscrittura e impaginazione del CV.

I due versi del percorso: ``extract``/``structure`` portano un PDF dentro il
``MasterProfile`` (Fase 1), ``generate`` porta il ``MasterProfile`` fuori come
PDF su misura per un annuncio (Fase 6).

``render`` e ``fit`` non sono riesportati qui: importano Playwright e Jinja2, e
chi importa questo package per estrarre un CV non deve pagarne il costo.
"""

from .extract import ExtractedDocument, ExtractionError, extract
from .generate import GeneratedCV, GenerationError, generate, storage_path_for
from .structure import structure

__all__ = [
    "ExtractedDocument",
    "ExtractionError",
    "GeneratedCV",
    "GenerationError",
    "extract",
    "generate",
    "storage_path_for",
    "structure",
]
