"""Estrazione del testo grezzo da un CV in PDF o DOCX.

Due estrattori PDF invece di uno perche' hanno difetti opposti:

* ``pypdfium2`` e' veloce e fedele, ma restituisce il testo nell'ordine del content
  stream. Su un CV a due colonne questo intreccia le colonne riga per riga,
  producendo frasi senza senso.
* ``pdfplumber`` ricostruisce il layout dalle coordinate e gestisce le colonne, ma
  e' molto piu' lento.

Si prova il primo e si passa al secondo solo quando il risultato ha l'aspetto di
un'estrazione andata male. Il costo si paga solo sui CV che ne hanno bisogno.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx"})

#: Sotto questa soglia il PDF e' quasi certamente una scansione: non c'e' testo
#: da estrarre, servirebbe un OCR che questo progetto non fa.
_MIN_USABLE_CHARS = 200


class ExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    #: Quale estrattore ha prodotto il risultato tenuto.
    method: Literal["pypdfium2", "pdfplumber", "python-docx"]
    pages: int | None
    language: str | None
    source_name: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def extract(path: Path) -> ExtractedDocument:
    """Estrae il testo da un CV, scegliendo l'estrattore in base al formato."""
    if not path.exists():
        raise ExtractionError(f"file non trovato: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ExtractionError(
            f"formato non supportato: {suffix or '(nessuna estensione)'}. "
            f"Attesi: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    doc = _extract_docx(path) if suffix == ".docx" else _extract_pdf(path)

    if doc.char_count < _MIN_USABLE_CHARS:
        raise ExtractionError(
            f"estratti solo {doc.char_count} caratteri da {path.name}. "
            "Probabilmente e' una scansione o un PDF di sole immagini: "
            "serve un originale con testo selezionabile."
        )
    return doc


# --- PDF ---------------------------------------------------------------------


def _extract_pdf(path: Path) -> ExtractedDocument:
    fast_text, pages = _pdf_pypdfium2(path)

    if _looks_well_extracted(fast_text):
        return _finish(fast_text, "pypdfium2", pages, path)

    log.info("estrazione veloce sospetta su %s, riprovo con pdfplumber", path.name)
    try:
        slow_text, slow_pages = _pdf_pdfplumber(path)
    except Exception as exc:  # pragma: no cover - dipende dal file
        log.warning("pdfplumber ha fallito su %s: %s", path.name, exc)
        return _finish(fast_text, "pypdfium2", pages, path)

    # Tiene il risultato piu' credibile, non semplicemente il secondo.
    if _quality(slow_text) > _quality(fast_text):
        return _finish(slow_text, "pdfplumber", slow_pages, path)
    return _finish(fast_text, "pypdfium2", pages, path)


def _pdf_pypdfium2(path: Path) -> tuple[str, int]:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    try:
        pages = len(pdf)
        chunks = []
        for i in range(pages):
            page = pdf[i]
            textpage = page.get_textpage()
            chunks.append(textpage.get_text_bounded())
            textpage.close()
            page.close()
        return _clean("\n".join(chunks)), pages
    finally:
        pdf.close()


def _pdf_pdfplumber(path: Path) -> tuple[str, int]:
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        chunks = [p.extract_text(layout=True) or "" for p in pdf.pages]
        return _clean("\n".join(chunks)), len(pdf.pages)


# --- DOCX --------------------------------------------------------------------


def _extract_docx(path: Path) -> ExtractedDocument:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]

    # Molti CV in Word mettono le date o le skill dentro tabelle invisibili:
    # ignorarle perderebbe interi blocchi di contenuto.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(dict.fromkeys(cells)))

    return _finish(_clean("\n".join(parts)), "python-docx", None, path)


# --- utilita' ----------------------------------------------------------------


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    # I PDF spezzano le parole a fine riga: "svilup-\npato" -> "sviluppato".
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _quality(text: str) -> float:
    """Punteggio euristico di quanto un'estrazione sembra riuscita.

    Non misura la correttezza — impossibile senza il file originale — ma
    distingue un testo plausibile da colonne intrecciate o caratteri persi.
    """
    if not text:
        return 0.0
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return 0.0
    avg_len = sum(len(ln) for ln in lines) / len(lines)
    letters = sum(c.isalpha() or c.isspace() for c in text) / len(text)
    # Righe di 1-3 caratteri in massa sono la firma di un layout a colonne
    # letto per coordinate sbagliate.
    fragments = sum(1 for ln in lines if len(ln) <= 3) / len(lines)
    return (min(avg_len, 80) / 80) * 0.5 + letters * 0.4 + (1 - fragments) * 0.1


def _looks_well_extracted(text: str) -> bool:
    return len(text) >= _MIN_USABLE_CHARS and _quality(text) >= 0.55


def _detect_language(text: str) -> str | None:
    try:
        import py3langid

        code, _ = py3langid.classify(text[:4000])
        return str(code)
    except Exception:  # pragma: no cover - la lingua non e' mai bloccante
        return None


def _finish(
    text: str,
    method: Literal["pypdfium2", "pdfplumber", "python-docx"],
    pages: int | None,
    path: Path,
) -> ExtractedDocument:
    return ExtractedDocument(
        text=text,
        method=method,
        pages=pages,
        language=_detect_language(text) if text else None,
        source_name=path.name,
    )
