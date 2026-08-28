"""Test dell'estrazione del testo dai CV."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobboard.cv import ExtractionError, extract
from jobboard.cv.extract import _clean, _quality


def test_single_column_pdf(single_column_cv: Path) -> None:
    doc = extract(single_column_cv)

    assert doc.method == "pypdfium2", "un CV a colonna singola non deve costare il fallback"
    assert doc.pages == 1
    assert doc.language == "it"
    # Le frasi devono restare intere, non spezzate o intrecciate.
    assert "servizio di fatturazione" in doc.text
    assert "da sei ore a venti minuti" in doc.text
    assert "PostgreSQL" in doc.text


def test_two_column_pdf_is_still_readable(two_column_cv: Path) -> None:
    """Il layout a due colonne e' il caso che giustifica il doppio estrattore."""
    doc = extract(two_column_cv)

    assert doc.char_count > 400
    assert "Filippo Nembrini" in doc.text
    # La frase attraversa piu' righe: se le colonne fossero intrecciate,
    # queste parole finirebbero separate da testo dell'altra colonna.
    assert "fatturazione" in doc.text
    assert "FastAPI" in doc.text


def test_docx_includes_table_content(docx_cv: Path) -> None:
    """Le tabelle in Word contengono spesso date e stack: perderle e' perdere dati."""
    doc = extract(docx_cv)

    assert doc.method == "python-docx"
    assert doc.pages is None, "un DOCX non ha un numero di pagine finche' non viene impaginato"
    assert "Backend Developer" in doc.text
    assert "2022-01 - presente" in doc.text, "contenuto della tabella perso"
    assert "Docker" in doc.text


def test_unsupported_format(tmp_path: Path) -> None:
    bad = tmp_path / "cv.txt"
    bad.write_text("Filippo Nembrini", encoding="utf-8")

    with pytest.raises(ExtractionError, match="formato non supportato"):
        extract(bad)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="file non trovato"):
        extract(tmp_path / "inesistente.pdf")


def test_empty_pdf_is_rejected_with_a_useful_message(tmp_path: Path) -> None:
    """Un PDF scansionato non deve produrre un profilo vuoto in silenzio."""
    from playwright.sync_api import sync_playwright

    target = tmp_path / "vuoto.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        page.pdf(path=str(target), format="A4")
        browser.close()

    with pytest.raises(ExtractionError, match=r"scansione|caratteri"):
        extract(target)


# --- utilita' interne --------------------------------------------------------


def test_clean_rejoins_hyphenated_line_breaks() -> None:
    """I PDF spezzano le parole a fine riga: senza questo, le skill si perdono."""
    assert "sviluppato" in _clean("ho svilup-\npato un servizio")
    # Un trattino legittimo non va toccato.
    assert "front-end" in _clean("esperienza front-end solida")


def test_clean_normalises_whitespace() -> None:
    assert _clean("a  \t b\r\n\r\n\r\n\r\nc") == "a b\n\nc"


def test_quality_penalises_fragmented_text() -> None:
    """Righe di pochi caratteri in massa sono la firma di colonne lette male."""
    good = "\n".join(["Progettato un servizio di fatturazione in Python e FastAPI."] * 10)
    fragmented = "\n".join(["Pro", "get", "tato", "un", "ser", "viz", "io", "in", "Py", "thon"])

    assert _quality(good) > _quality(fragmented)
    assert _quality("") == 0.0
