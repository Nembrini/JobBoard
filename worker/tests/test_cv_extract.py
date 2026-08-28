"""Test dell'estrazione del testo dai CV."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobboard.cv import ExtractionError, extract
from jobboard.cv.extract import (
    _MIN_WORD_INTEGRITY,
    _Candidate,
    _clean,
    _numeric_tokens,
    _pick_best,
    _quality,
    _word_integrity,
)


def test_single_column_pdf(single_column_cv: Path) -> None:
    doc = extract(single_column_cv)

    assert doc.method in ("pypdfium2", "pdfplumber")
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


# --- scelta fra estrattori ---------------------------------------------------


def test_pick_best_prefers_the_extraction_that_kept_the_numbers() -> None:
    """Regressione su un caso reale.

    Su un CV vero pypdfium2 ha prodotto un testo di qualita' superiore ma senza
    la cifra "239": "distribuite su circa 239 robot" diventava "circa robot".
    Le cifre sono i Result dei bullet ACR, quindi vincono sulla prosa.
    """
    lost = _Candidate("pypdfium2", "Distribuite su circa robot e macchine presso 1000 clienti.", 1)
    kept = _Candidate(
        "pdfplumber", "Distribuite su circa 239 robot e macchine presso 1000 clienti.", 1
    )

    assert _pick_best([lost, kept]).method == "pdfplumber"
    assert _pick_best([kept, lost]).method == "pdfplumber", "l'ordine non deve contare"


def test_pick_best_rejects_a_candidate_whose_prose_collapsed() -> None:
    """Recuperare una cifra non vale un testo illeggibile."""
    prose = _Candidate("pypdfium2", "\n".join(["Progettato un servizio di fatturazione."] * 12), 1)
    garbage = _Candidate("pdfplumber", "\n".join(["1", "2", "3", "9", "8", "42", "239"] * 5), 1)

    assert _pick_best([prose, garbage]).method == "pypdfium2"


def test_pick_best_with_a_single_candidate() -> None:
    """Se pdfplumber fallisce si tiene comunque il risultato disponibile."""
    only = _Candidate("pypdfium2", "Un testo qualsiasi abbastanza lungo.", 1)
    assert _pick_best([only]) is only


def test_numeric_tokens_catches_percentages_and_thousands() -> None:
    tokens = _numeric_tokens("Ridotto dell'80% su 1.190 cicli nel 2024, da 6 a 2 ore.")
    assert {"80%", "1.190", "2024", "6", "2"} <= tokens


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


def test_pick_best_rejects_extraction_that_lost_word_boundaries() -> None:
    """Regressione sul caso reale piu' grave.

    Su questo CV pdfplumber recuperava una cifra in piu' ma restituiva
    'macchinedatagliolaser' invece di 'macchine da taglio laser': 50 parole su
    187 sopra i 20 caratteri. Un testo cosi' e' inutilizzabile, e nessuna
    euristica basata sulla forma se ne accorge — righe lunghe, tante lettere,
    nessun frammento corto. Vince la leggibilita', anche perdendo una cifra.
    """
    fused = _Candidate(
        "pdfplumber",
        "macchinedatagliolaser,distribuitesucirca239robotemacchinepressooltre1000clienti.",
        1,
    )
    readable = _Candidate(
        "pypdfium2",
        "macchine da taglio laser, distribuite su circa robot e macchine presso 1000 clienti.",
        1,
    )

    assert _pick_best([fused, readable]).method == "pypdfium2"
    assert _pick_best([readable, fused]).method == "pypdfium2"


def test_word_integrity_detects_fused_words() -> None:
    assert _word_integrity("macchine da taglio laser distribuite su robot") == 1.0
    assert _word_integrity("macchinedatagliolaserdistribuitesurobot") == 0.0
    assert _word_integrity("") == 0.0


def test_word_integrity_tolerates_the_odd_long_word() -> None:
    """Una parola lunga legittima non deve far scartare un'estrazione buona."""
    text = " ".join(["parola"] * 30 + ["internazionalizzazione"])
    assert _word_integrity(text) > _MIN_WORD_INTEGRITY
