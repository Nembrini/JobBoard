"""Test degli embedding locali.

Il modello vero non viene caricato: pesa 449 MB e sarebbe una dipendenza di rete
in mezzo alla suite. Qui si testa tutto cio' che sta *intorno* al modello — i
prefissi, la serializzazione, il coseno, il riscalamento — che e' esattamente la
parte dove un errore non da' eccezioni, solo risultati leggermente peggiori.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np
import pytest

from jobboard.ai import embeddings
from jobboard.ai.embeddings import (
    Embedder,
    EmbeddingError,
    cosine,
    from_bytes,
    spread,
    to_bytes,
)


class _FakeModel:
    """Registra i testi ricevuti e restituisce vettori deterministici."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.seen: list[str] = []

    def embed(self, texts: Sequence[str]) -> Iterator[np.ndarray]:
        self.seen.extend(texts)
        for i in range(len(texts)):
            vector = np.zeros(self.dim, dtype=np.float32)
            vector[i % self.dim] = 1.0
            yield vector


@pytest.fixture
def embedder(monkeypatch: pytest.MonkeyPatch) -> Embedder:
    fake = _FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda name, spec, cache: fake)
    return Embedder("intfloat/multilingual-e5-small", Path("."))


# --- prefissi ----------------------------------------------------------------


def test_profile_and_jobs_get_the_prefixes_e5_expects(embedder: Embedder) -> None:
    """La famiglia E5 e' addestrata con questi prefissi.

    Ometterli non solleva niente: produce vettori peggiori, in silenzio. E' il
    motivo per cui i prefissi stanno nella ModelSpec e non nel chiamante.
    """
    embedder.embed_profile("dieci anni di Python")
    embedder.embed_jobs(["cercasi backend developer", "cercasi cuoco"])

    model = embedder._model
    assert isinstance(model, _FakeModel)
    assert model.seen == [
        "query: dieci anni di Python",
        "passage: cercasi backend developer",
        "passage: cercasi cuoco",
    ]


def test_unknown_model_is_rejected_instead_of_guessed() -> None:
    """Un modello senza ModelSpec verrebbe usato senza prefissi: meglio fermarsi."""
    with pytest.raises(EmbeddingError, match="sconosciuto"):
        Embedder("openai/text-embedding-3-small", Path("."))


def test_a_model_that_changed_dimension_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se il modello scaricato non e' quello atteso, meglio un errore subito."""
    monkeypatch.setattr(embeddings, "_load_model", lambda name, spec, cache: _FakeModel(dim=256))
    wrong = Embedder("intfloat/multilingual-e5-small", Path("."))

    with pytest.raises(EmbeddingError, match="forma"):
        wrong.embed_profile("qualsiasi cosa")


def test_no_jobs_means_an_empty_matrix_not_a_crash(embedder: Embedder) -> None:
    result = embedder.embed_jobs([])
    assert result.shape == (0, 384)


# --- serializzazione ---------------------------------------------------------


def test_bytes_roundtrip_preserves_the_vector() -> None:
    vector = np.array([0.5, -0.25, 1.0, 0.0], dtype=np.float32)
    assert np.array_equal(from_bytes(to_bytes(vector)), vector)


def test_serialisation_is_four_bytes_per_dimension() -> None:
    """Il formato e' float32 esplicito: 384 dimensioni = 1536 byte, sempre."""
    blob = to_bytes(np.ones(384, dtype=np.float32))
    assert len(blob) == 384 * 4
    assert np.frombuffer(blob, dtype="<f4").shape == (384,)


def test_float64_input_is_stored_as_float32() -> None:
    """Un vettore in doppia precisione non deve raddoppiare lo spazio in tabella."""
    assert len(to_bytes(np.ones(10, dtype=np.float64))) == 40


def test_a_truncated_blob_is_rejected() -> None:
    with pytest.raises(EmbeddingError, match="multiplo"):
        from_bytes(b"\x00\x00\x00")


def test_the_decoded_vector_is_writable() -> None:
    """``np.frombuffer`` restituisce una vista in sola lettura: serve una copia."""
    decoded = from_bytes(to_bytes(np.ones(4, dtype=np.float32)))
    decoded[0] = 2.0  # non deve sollevare


# --- confronto ---------------------------------------------------------------


def test_cosine_ranks_the_closer_vector_first() -> None:
    query = np.array([1.0, 0.0], dtype=np.float32)
    documents = np.array([[1.0, 0.0], [0.7, 0.7], [0.0, 1.0]], dtype=np.float32)

    scores = cosine(query, documents)
    assert scores[0] > scores[1] > scores[2]
    assert scores[0] == pytest.approx(1.0)
    assert scores[2] == pytest.approx(0.0, abs=1e-6)


def test_cosine_normalises_its_input() -> None:
    """Un vettore riletto dal database potrebbe non essere unitario."""
    scores = cosine(
        np.array([3.0, 0.0], dtype=np.float32),
        np.array([[10.0, 0.0]], dtype=np.float32),
    )
    assert scores[0] == pytest.approx(1.0)


def test_cosine_survives_a_zero_vector() -> None:
    scores = cosine(
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([[0.0, 0.0]], dtype=np.float32),
    )
    assert scores[0] == pytest.approx(0.0)


def test_cosine_of_nothing_is_an_empty_array() -> None:
    assert cosine(np.ones(4, dtype=np.float32), np.empty((0, 4), dtype=np.float32)).size == 0


# --- riscalamento ------------------------------------------------------------


def test_spread_opens_up_the_compressed_range_of_e5() -> None:
    """Il motivo per cui questa funzione esiste, con numeri veri.

    Misurati sul profilo reale: un annuncio da infermiere prende 0.7993, uno da
    backend developer 0.8790. Sommare quei valori grezzi a un BM25 che usa tutto
    l'intervallo 0-1 significa dichiarare un peso del 60% per il coseno e
    ottenerne uno del 5%.
    """
    reali = np.array([0.8790, 0.8966, 0.8830, 0.8177, 0.7993, 0.8102], dtype=np.float32)

    riscalati = spread(reali)

    assert riscalati.min() == pytest.approx(0.0)
    assert riscalati.max() == pytest.approx(1.0)
    # L'ordine non cambia: si riscala, non si riordina.
    assert np.argsort(riscalati).tolist() == np.argsort(reali).tolist()
    # I tre pertinenti restano tutti sopra i tre non pertinenti, ma ora con un
    # margine leggibile invece di sei centesimi.
    assert riscalati[:3].min() - riscalati[3:].max() > 0.5


def test_spread_is_neutral_when_there_is_nothing_to_compare() -> None:
    """Un solo candidato non e' ne' il migliore ne' il peggiore."""
    assert spread(np.array([0.87], dtype=np.float32)) == pytest.approx(0.5)
    assert spread(np.full(4, 0.87, dtype=np.float32)) == pytest.approx(np.full(4, 0.5))


def test_spread_of_nothing_is_nothing() -> None:
    assert spread(np.empty(0, dtype=np.float32)).size == 0
