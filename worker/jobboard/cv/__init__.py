"""Estrazione, riscrittura e impaginazione del CV."""

from .extract import ExtractedDocument, ExtractionError, extract
from .structure import structure

__all__ = ["ExtractedDocument", "ExtractionError", "extract", "structure"]
