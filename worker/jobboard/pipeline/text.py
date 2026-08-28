"""Utilità di testo condivise dalla pipeline: HTML, impronte, SimHash."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile("[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_WORD = re.compile(r"[\w'-]+", re.UNICODE)

#: Tag il cui contenuto non è testo dell'annuncio. ``script`` e ``style`` sono
#: ovvi; ``nav`` e ``footer`` compaiono nelle descrizioni incollate da una pagina.
_DROP_TAGS = ("script", "style", "noscript", "nav", "footer", "svg")


def html_to_text(raw: str) -> str:
    """HTML di una job description -> testo leggibile.

    Le liste puntate diventano righe con un trattino invece di sparire: nelle job
    description i requisiti sono quasi sempre un ``<ul>``, e appiattirli in un
    unico paragrafo rende il testo peggiore sia per l'LLM sia per la lettura.
    """
    if not raw:
        return ""
    if "<" not in raw:
        return collapse(raw)

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for tag in soup.find_all(["br", "p", "div", "h1", "h2", "h3", "h4", "tr"]):
        tag.insert_after("\n")

    return collapse(soup.get_text())


def collapse(text: str) -> str:
    """Normalizza spazi e righe vuote senza toccare la struttura a paragrafi."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def normalize_key(value: str | None) -> str:
    """Forma canonica per i confronti: minuscolo, senza accenti né punteggiatura.

    ``"Università degli Studi"`` e ``"UNIVERSITA DEGLI STUDI"`` devono produrre la
    stessa chiave, altrimenti la dedup non riconosce due annunci della stessa
    azienda scritti da due aggregatori diversi.
    """
    if not value:
        return ""
    ascii_only = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(_WORD.findall(ascii_only.lower()))


#: Suffissi societari da togliere prima di confrontare due nomi d'azienda:
#: "Acme S.r.l." su un portale e "Acme" su un altro sono la stessa azienda.
_COMPANY_SUFFIXES = frozenset(
    {
        "srl", "s r l", "spa", "s p a", "sas", "snc", "sapa",
        "gmbh", "ag", "ug", "kg", "ohg", "mbh",
        "bv", "nv", "sa", "sarl", "sl", "slu",
        "ltd", "limited", "llc", "inc", "incorporated", "corp", "corporation",
        "plc", "co", "company", "group", "holding", "holdings", "international",
        "italia", "italy", "deutschland", "germany", "europe", "emea",
    }
)  # fmt: skip


def normalize_company(name: str | None) -> str:
    """Chiave canonica per un nome d'azienda."""
    parole = _join_initials(normalize_key(name).split())
    filtrate = [p for p in parole if p not in _COMPANY_SUFFIXES]
    # Se il nome era fatto solo di suffissi non resta niente: meglio il nome
    # completo di una chiave vuota, che collegherebbe fra loro aziende diverse.
    return " ".join(filtrate or parole)


def _join_initials(parole: list[str]) -> list[str]:
    """Riunisce le sigle puntate: ``["s", "r", "l"] -> ["srl"]``.

    La normalizzazione trasforma "S.r.l." in "s r l", e a quel punto il filtro
    dei suffissi — che ragiona per parola — non riconosce piu' niente: "Acme
    S.r.l." e "Acme" producevano due chiavi diverse e restavano due aziende.
    Servono almeno due lettere isolate di fila, per non fondere iniziali
    legittime dentro un nome.
    """
    out: list[str] = []
    buffer: list[str] = []
    for parola in [*parole, ""]:
        if len(parola) == 1 and parola.isalpha():
            buffer.append(parola)
            continue
        if len(buffer) >= 2:
            out.append("".join(buffer))
        else:
            out.extend(buffer)
        buffer = []
        if parola:
            out.append(parola)
    return out


def content_hash(text: str) -> str:
    """SHA-256 del testo normalizzato: dice se un annuncio è cambiato."""
    return hashlib.sha256(normalize_key(text).encode("utf-8")).hexdigest()


#: Bit dell'impronta SimHash. 64 entra in un ``BIGINT`` di Postgres.
_SIMHASH_BITS = 64
_SIMHASH_MASK = (1 << _SIMHASH_BITS) - 1


def simhash(text: str, *, shingle: int = 3) -> int:
    """Impronta locale-sensibile: due testi simili hanno impronte vicine.

    Serve per la dedup di secondo livello. Due aggregatori che ripubblicano lo
    stesso annuncio non restituiscono testi identici — troncano, aggiungono un
    disclaimer, cambiano l'ordine dei paragrafi — quindi lo SHA-256 non li
    riconosce, mentre la distanza di Hamming fra due SimHash sì.

    Si lavora su gruppi di tre parole invece che su parole singole: due annunci
    tecnici qualsiasi condividono moltissime parole ("esperienza", "team",
    "sviluppo") e l'impronta a parole singole li dichiarerebbe simili tutti.
    """
    parole = normalize_key(text).split()
    if not parole:
        return 0

    if len(parole) < shingle:
        gruppi = [" ".join(parole)]
    else:
        gruppi = [" ".join(parole[i : i + shingle]) for i in range(len(parole) - shingle + 1)]

    pesi = [0] * _SIMHASH_BITS
    for gruppo in gruppi:
        digest = int.from_bytes(hashlib.blake2b(gruppo.encode(), digest_size=8).digest(), "big")
        for bit in range(_SIMHASH_BITS):
            pesi[bit] += 1 if digest >> bit & 1 else -1

    impronta = 0
    for bit, peso in enumerate(pesi):
        if peso > 0:
            impronta |= 1 << bit
    return impronta


def hamming(a: int, b: int) -> int:
    """Numero di bit diversi fra due impronte. 0 = identiche, 64 = opposte."""
    return int(((a ^ b) & _SIMHASH_MASK).bit_count())


def to_signed_64(value: int) -> int:
    """SimHash a 64 bit -> intero con segno, per la colonna ``BIGINT``.

    Postgres non ha interi a 64 bit senza segno. La conversione è reversibile e
    il confronto avviene sui bit, quindi il segno non cambia nulla.
    """
    value &= _SIMHASH_MASK
    return value - (1 << _SIMHASH_BITS) if value >= 1 << (_SIMHASH_BITS - 1) else value


def from_signed_64(value: int) -> int:
    return value & _SIMHASH_MASK
