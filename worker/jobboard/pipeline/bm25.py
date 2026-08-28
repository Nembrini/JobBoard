"""BM25 sulle competenze: il contrappeso lessicale all'embedding.

L'embedding capisce che "sviluppatore backend" e "backend engineer" sono la
stessa cosa, ma **diluisce le tecnologie**: un annuncio Java e uno Python con la
stessa struttura di frasi hanno vettori quasi identici, e la differenza è
esattamente ciò che conta per capire se puoi candidarti. BM25 fa il lavoro
opposto — pesa le corrispondenze esatte e premia i termini rari — e i due errori
non si sommano perché non sono lo stesso errore.

Due scelte non ovvie:

**Le competenze sono frasi, non parole.** "Spring Boot", "REST API", "CI/CD"
spezzettati in unigrammi diventano rumore: "boot" e "api" compaiono ovunque.
Qui un termine di ricerca è un n-gramma e viene cercato come tale.

**La IDF è quella smussata.** La formula classica di Robertson diventa
*negativa* per un termine presente in più di metà dei documenti: in un corpus di
annunci per sviluppatori, "developer" ne fa parte, e un contributo negativo
farebbe scendere il punteggio di un annuncio perché contiene la parola giusta.
Con ``ln(1 + …)`` il contributo tende a zero senza mai cambiare segno.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

#: Parole: lettere, cifre, i separatori interni che tengono insieme "ci/cd" e
#: "node.js", e i simboli **finali** di "c++", "c#", "f#".
#:
#: La coda ``[+#]*`` non e' un dettaglio: senza, "C++" diventa "c" — un token che
#: non corrisponde a niente — e una competenza dichiarata nel profilo smette di
#: contare, senza errori e senza che il punteggio sembri sbagliato.
_TOKEN = re.compile(r"[a-z0-9]+(?:[.+#/][a-z0-9]+)*[+#]*", re.IGNORECASE)

#: Parametri di Okapi BM25. ``k1`` governa la saturazione della frequenza —
#: la decima ripetizione di "Java" non vale quanto la seconda — e ``b`` quanto
#: penalizzare i documenti lunghi. Sono i valori di riferimento della
#: letteratura: si toccano solo con dati alla mano.
K1 = 1.5
B = 0.75

#: Lunghezza massima di un termine di ricerca in parole. Tre copre "amazon web
#: services" e "google cloud platform"; oltre non ci sono nomi di tecnologie.
MAX_NGRAM = 3


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN.finditer(text)]


def ngrams(tokens: Sequence[str], max_n: int = MAX_NGRAM) -> Counter[str]:
    """Tutti gli n-grammi fino a ``max_n``, uniti da uno spazio.

    Precalcolarli costa una passata sul documento e rende il punteggio di ogni
    termine una lettura da dizionario, invece di una scansione per termine.
    """
    contatore: Counter[str] = Counter()
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            contatore[" ".join(tokens[i : i + n])] += 1
    return contatore


@dataclass(frozen=True)
class Bm25:
    """Un indice costruito su un lotto di documenti.

    L'indice è **relativo al lotto**: la IDF dipende da quanti documenti
    contengono un termine, quindi due run con annunci diversi danno punteggi
    diversi allo stesso annuncio. È voluto — serve a ordinare il raccolto di
    oggi, non a produrre un numero confrontabile fra giorni diversi.
    """

    #: Un ``Counter`` di n-grammi per documento.
    documents: tuple[Counter[str], ...]
    #: Lunghezza in token di ogni documento, prima degli n-grammi.
    lengths: NDArray[np.float32]
    average_length: float

    @classmethod
    def build(cls, texts: Sequence[str]) -> Bm25:
        tokenizzati = [tokenize(t) for t in texts]
        lunghezze = np.array([len(t) for t in tokenizzati], dtype=np.float32)
        media = float(lunghezze.mean()) if lunghezze.size else 0.0
        return cls(
            documents=tuple(ngrams(t) for t in tokenizzati),
            lengths=lunghezze,
            average_length=media or 1.0,
        )

    def __len__(self) -> int:
        return len(self.documents)

    def score(
        self, terms: Sequence[str], weights: Sequence[float] | None = None
    ) -> NDArray[np.float32]:
        """Punteggio di ogni documento rispetto ai termini dati.

        ``weights`` permette di far pesare di più una competenza centrale del
        profilo rispetto a una marginale. Assente, pesano tutte uguale.
        """
        punteggi = np.zeros(len(self.documents), dtype=np.float32)
        if not self.documents or not terms:
            return punteggi

        normalizzati = [" ".join(tokenize(t)) for t in terms]
        pesi = list(weights) if weights is not None else [1.0] * len(normalizzati)
        if len(pesi) != len(normalizzati):
            raise ValueError("weights e terms hanno lunghezze diverse")

        n_doc = len(self.documents)
        denominatore_lunghezza = K1 * (1 - B + B * self.lengths / self.average_length)

        for termine, peso in zip(normalizzati, pesi, strict=True):
            if not termine:
                continue
            frequenze = np.array([doc.get(termine, 0) for doc in self.documents], dtype=np.float32)
            presenti = int(np.count_nonzero(frequenze))
            if presenti == 0:
                continue
            idf = math.log(1 + (n_doc - presenti + 0.5) / (presenti + 0.5))
            punteggi += peso * idf * (frequenze * (K1 + 1)) / (frequenze + denominatore_lunghezza)

        return punteggi
