"""Estrazione, riscrittura e impaginazione del CV."""

from .extract import ExtractedDocument, ExtractionError, extract

__all__ = ["ExtractedDocument", "ExtractionError", "extract"]
