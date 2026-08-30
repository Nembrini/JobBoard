"""I prompt lunghi, tenuti come file di testo invece che come stringhe Python.

Un prompt di sessanta righe dentro un modulo diventa illeggibile appena qualcuno
lo indenta: si perde in mezzo al codice, il diff di una modifica sostanziale
sembra una riformattazione, e riscriverlo richiede di aprire un file `.py`. Qui
sono file `.md`, che si leggono su GitHub e si sostituiscono per intero.

Il commento HTML in testa a ciascuno non arriva al modello: `load` lo toglie.
Serve a chi apre il file per modificarlo e ha bisogno di sapere cosa fa gia' il
codice — perche' quello che il codice verifica non va chiesto anche al prompt.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_CARTELLA = Path(__file__).resolve().parent

#: Commento HTML in apertura: nota per chi edita il file, non istruzione per il
#: modello. Si toglie prima dell'invio, altrimenti sarebbero token pagati per
#: spiegare al modello com'e' organizzato il nostro repository.
_INTESTAZIONE = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


@lru_cache(maxsize=8)
def load(nome: str) -> str:
    """Il testo di un prompt, senza la nota redazionale in testa.

    In cache: durante una run il CV di venti annunci rilegge lo stesso file venti
    volte, e il contenuto non cambia mentre il processo gira.
    """
    percorso = _CARTELLA / f"{nome}.md"
    if not percorso.is_file():
        disponibili = ", ".join(sorted(p.stem for p in _CARTELLA.glob("*.md"))) or "nessuno"
        raise FileNotFoundError(f"prompt '{nome}' inesistente. Disponibili: {disponibili}")
    return _INTESTAZIONE.sub("", percorso.read_text(encoding="utf-8")).strip()


__all__ = ["load"]
