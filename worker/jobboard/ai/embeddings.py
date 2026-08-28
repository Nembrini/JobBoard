"""Embedding del testo, in locale e su CPU. Nessuna chiamata a pagamento.

E' il motore dello Stadio 1 del matching: confronta il profilo con centinaia di
annunci al giorno, quindi deve costare zero. ``fastembed`` esegue un modello ONNX
sulla CPU; il modello si scarica una volta sola e poi resta in ``data/models``.

Due trappole di questo modello, entrambe verificate su dati veri:

1. **I prefissi sono obbligatori.** La famiglia E5 e' addestrata con ``query:``
   davanti alla richiesta e ``passage:`` davanti al documento. Ometterli non da'
   errore, degrada la qualita' in silenzio — il caso peggiore di bug.
2. **Il coseno assoluto non vuol dire niente.** Su questo profilo un annuncio da
   infermiere ottiene 0.80 e uno da backend developer 0.88: l'intero intervallo
   utile e' largo 0.08. Una soglia fissa e' priva di senso, e sommare il coseno
   grezzo a un punteggio BM25 farebbe pesare per il 60% una costante. Da qui
   :func:`spread`, che riscala i punteggi *dentro il lotto* prima di combinarli.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ..config import get_settings

log = logging.getLogger(__name__)

#: Un vettore o una matrice di vettori. Sempre float32: la precisione doppia non
#: aggiunge nulla a un coseno e raddoppierebbe lo spazio occupato in tabella.
Vector = NDArray[np.float32]

#: Formato di serializzazione per la colonna ``bytea``: float32 little-endian.
#: Esplicito e non il dtype nativo, perche' il byte order nativo e' una proprieta'
#: della macchina e questi byte devono sopravvivere a un cambio di PC.
_DTYPE = np.dtype("<f4")


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    """Cosa serve sapere di un modello, oltre al suo nome."""

    dim: int
    #: Prefisso per il lato "richiesta" (il profilo).
    query_prefix: str = ""
    #: Prefisso per il lato "documento" (l'annuncio).
    passage_prefix: str = ""
    #: Valorizzato solo per i modelli che fastembed non conosce e vanno
    #: registrati a mano indicando il repo Hugging Face.
    hf_repo: str | None = None
    model_file: str = "onnx/model.onnx"
    #: Token oltre i quali il testo viene troncato. Conta per l'ordine in cui si
    #: compone il testo di un annuncio: quello che sta dopo non viene letto.
    max_tokens: int = 512


#: I modelli utilizzabili, con le loro proprieta'. Un modello fuori da questo
#: elenco viene rifiutato invece di essere usato con i prefissi sbagliati.
KNOWN_MODELS: dict[str, ModelSpec] = {
    # Predefinito: 384 dimensioni, un centinaio di lingue. Il file ONNX pesa 449 MB
    # (i pesi sono quasi tutti nella matrice di embedding da 250k token, non nei
    # layer): esiste anche model_qint8_avx512_vnni.onnx a un quarto dello spazio,
    # basta cambiare model_file. fastembed 0.8
    # non lo include fra i modelli integrati (ha solo la variante large da
    # 2.24 GB), quindi si registra a mano dal repo ufficiale.
    "intfloat/multilingual-e5-small": ModelSpec(
        dim=384,
        query_prefix="query: ",
        passage_prefix="passage: ",
        hf_repo="intfloat/multilingual-e5-small",
    ),
    # Stessa famiglia, qualita' superiore, 2.24 GB da scaricare e molto piu' lento
    # in inferenza. Integrato in fastembed: nessuna registrazione necessaria.
    "intfloat/multilingual-e5-large": ModelSpec(
        dim=1024, query_prefix="query: ", passage_prefix="passage: "
    ),
    # Alternativa senza prefissi, se un giorno E5 diventasse un problema.
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": ModelSpec(dim=384),
}


class Embedder:
    """Un modello caricato, pronto a produrre vettori.

    Caricarlo costa qualche secondo: va tenuto vivo per tutta la durata di una
    run, non istanziato per annuncio. Ci pensa :func:`get_embedder`.
    """

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        spec = KNOWN_MODELS.get(model_name)
        if spec is None:
            raise EmbeddingError(
                f"modello di embedding sconosciuto: {model_name!r}. "
                f"Disponibili: {', '.join(sorted(KNOWN_MODELS))}. "
                "Aggiungerne uno significa dichiararne anche i prefissi: usarli "
                "sbagliati peggiora i risultati senza dare errore."
            )
        self.model_name = model_name
        self.spec = spec
        self._model = _load_model(model_name, spec, cache_dir)

    @property
    def dim(self) -> int:
        return self.spec.dim

    def embed_profile(self, text: str) -> Vector:
        """Il lato "richiesta" del confronto: il CV."""
        vector: Vector = self._embed([self.spec.query_prefix + text])[0]
        return vector

    def embed_jobs(self, texts: Sequence[str]) -> Vector:
        """Il lato "documento": gli annunci, in lotto."""
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        return self._embed([self.spec.passage_prefix + t for t in texts])

    def _embed(self, prefixed: list[str]) -> Vector:
        raw: Any = list(self._model.embed(prefixed))
        vectors = np.asarray(raw, dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dim:
            raise EmbeddingError(
                f"{self.model_name} ha prodotto vettori di forma {vectors.shape}, "
                f"attesa (_, {self.dim})"
            )
        return vectors


def _load_model(model_name: str, spec: ModelSpec, cache_dir: Path) -> Any:
    from fastembed import TextEmbedding

    if spec.hf_repo:
        _register_custom(TextEmbedding, model_name, spec)

    cache_dir.mkdir(parents=True, exist_ok=True)
    log.info("carico il modello di embedding %s da %s", model_name, cache_dir)
    return TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))


def _register_custom(text_embedding: Any, model_name: str, spec: ModelSpec) -> None:
    """Insegna a fastembed un modello che non ha in elenco.

    Idempotente: registrare due volte lo stesso nome solleverebbe, e in un
    processo che carica il modello piu' di una volta succederebbe subito.
    """
    from fastembed.common.model_description import ModelSource, PoolingType

    if any(m["model"] == model_name for m in text_embedding.list_supported_models()):
        return
    text_embedding.add_custom_model(
        model=model_name,
        # Media dei token, poi normalizzazione L2: e' la ricetta della model card
        # di E5. Sbagliarla produce vettori plausibili e inutili.
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=spec.hf_repo),
        dim=spec.dim,
        model_file=spec.model_file,
    )


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """L'embedder condiviso dal processo. Il modello si carica una volta sola.

    Senza parametri di proposito: ``Settings`` e' un modello Pydantic e non e'
    hashabile, quindi passarlo qui farebbe esplodere la cache invece di
    configurarla. Chi ha bisogno di un modello diverso costruisce un
    :class:`Embedder`.
    """
    settings = get_settings()
    return Embedder(settings.embedding_model, settings.embedding_cache_dir)


# --- serializzazione ---------------------------------------------------------


def to_bytes(vector: Vector) -> bytes:
    """Vettore -> colonna ``bytea``."""
    return np.ascontiguousarray(vector, dtype=_DTYPE).tobytes()


def from_bytes(blob: bytes) -> Vector:
    """Colonna ``bytea`` -> vettore."""
    if len(blob) % _DTYPE.itemsize:
        raise EmbeddingError(f"{len(blob)} byte non sono un multiplo di float32")
    # frombuffer restituisce una vista in sola lettura sul buffer originale: la
    # copia serve perche' il chiamante possa normalizzare senza sorprese.
    return np.frombuffer(blob, dtype=_DTYPE).astype(np.float32)


# --- confronto ---------------------------------------------------------------


def cosine(query: Vector, documents: Vector) -> Vector:
    """Similarita' coseno fra un vettore e una matrice di vettori.

    I modelli in :data:`KNOWN_MODELS` normalizzano gia' l'output, ma la
    normalizzazione viene rifatta qui: un vettore riletto dal database potrebbe
    venire da una versione precedente del modello, e un coseno maggiore di 1
    sarebbe un bug difficile da vedere.
    """
    if documents.size == 0:
        return np.empty(0, dtype=np.float32)
    scores: Vector = _unit(documents) @ _unit(query)
    return scores


def _unit(vectors: Vector) -> Vector:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    # Un vettore nullo non ha direzione: lo si lascia nullo invece di dividere per
    # zero, cosi' il suo coseno con qualunque cosa vale 0.
    safe = np.where(norms == 0, 1.0, norms)
    normalized: Vector = (vectors / safe).astype(np.float32)
    return normalized


def spread(scores: Vector) -> Vector:
    """Riscala i punteggi su 0-1 **rispetto al lotto**, non in assoluto.

    Serve perche' i coseni di E5 vivono schiacciati in alto: su dati reali un
    annuncio del tutto fuori tema prende 0.80 e uno perfettamente in tema 0.89.
    Combinare quei numeri con un BM25 che usa tutto l'intervallo 0-1 significa
    dare al coseno un peso nominale del 60% e reale del 5%.

    Con un solo candidato, o con tutti i punteggi identici, non c'e' niente da
    discriminare: si restituisce 0.5, che e' neutro.
    """
    if scores.size == 0:
        return scores
    lo, hi = float(scores.min()), float(scores.max())
    if hi - lo < 1e-9:
        return np.full_like(scores, 0.5)
    rescaled: Vector = ((scores - lo) / (hi - lo)).astype(np.float32)
    return rescaled
