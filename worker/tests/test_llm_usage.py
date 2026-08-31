"""Test del consumo LLM e del suo prezzo (Fase 10.2): nessun database vero.

Stessa ``_FakeSession`` di ``test_notify.py``/``test_tracking_settings.py``:
``record_llm_usage`` e ``load_pricing``/``save_price`` sono pure una volta
tolta la sessione.
"""

from __future__ import annotations

from typing import Any

from jobboard.ai.pricing import (
    PRICING_SETTING_KEY,
    ModelPrice,
    estimate_cost,
    load_pricing,
    save_price,
)
from jobboard.models import LLMUsageLog, Setting
from jobboard.models.enums import LlmUsagePurpose
from jobboard.store.llm_usage import record_llm_usage


class _FakeSession:
    def __init__(self) -> None:
        self.settings: dict[str, Setting] = {}
        self.added: list[Any] = []

    def get(self, model: type[Any], key: str) -> Any:
        assert model is Setting
        return self.settings.get(key)

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, Setting):
            self.settings[obj.key] = obj


# --- record_llm_usage ---------------------------------------------------------


def test_un_run_senza_chiamate_non_scrive_niente() -> None:
    """Un profilo non confermato o un controllo email senza candidature: zero righe."""
    sessione = _FakeSession()
    record_llm_usage(
        sessione,  # type: ignore[arg-type]
        purpose=LlmUsagePurpose.MATCH_SCORING,
        model="gemini-3.5-flash-lite",
        calls=0,
        input_tokens=0,
        output_tokens=0,
    )
    assert sessione.added == []


def test_un_run_con_chiamate_registra_una_riga_aggregata() -> None:
    sessione = _FakeSession()
    record_llm_usage(
        sessione,  # type: ignore[arg-type]
        purpose=LlmUsagePurpose.MATCH_SCORING,
        model="gemini-3.5-flash-lite",
        calls=40,
        input_tokens=90_000,
        output_tokens=11_000,
        batch_id="batch-123",
    )
    assert len(sessione.added) == 1
    riga = sessione.added[0]
    assert isinstance(riga, LLMUsageLog)
    assert riga.purpose is LlmUsagePurpose.MATCH_SCORING
    assert riga.calls == 40
    assert riga.input_tokens == 90_000
    assert riga.batch_id == "batch-123"
    assert riga.reference_id is None


def test_una_riga_puntuale_porta_il_reference_id() -> None:
    """Un CV generato si lega al match, non a un batch: sono due chiavi diverse."""
    sessione = _FakeSession()
    record_llm_usage(
        sessione,  # type: ignore[arg-type]
        purpose=LlmUsagePurpose.CV_TAILOR,
        model="gemini-3.6-flash",
        calls=1,
        input_tokens=3_000,
        output_tokens=800,
        reference_id=42,
    )
    riga = sessione.added[0]
    assert riga.reference_id == 42
    assert riga.batch_id is None


# --- pricing --------------------------------------------------------------


def test_senza_prezzo_configurato_il_costo_e_ignoto() -> None:
    sessione = _FakeSession()
    prezzi = load_pricing(sessione)  # type: ignore[arg-type]
    assert prezzi == {}
    assert estimate_cost(prezzi, "gemini-3.5-flash-lite", 1_000_000, 1_000_000) is None


def test_un_prezzo_salvato_si_rilegge_e_stima_il_costo() -> None:
    sessione = _FakeSession()
    save_price(sessione, "gemini-3.5-flash-lite", ModelPrice(0.10, 0.40, "USD"))  # type: ignore[arg-type]

    prezzi = load_pricing(sessione)  # type: ignore[arg-type]
    assert prezzi["gemini-3.5-flash-lite"] == ModelPrice(0.10, 0.40, "USD")

    stima = estimate_cost(prezzi, "gemini-3.5-flash-lite", 1_000_000, 500_000)
    assert stima is not None
    valore, valuta = stima
    assert valuta == "USD"
    assert round(valore, 4) == round(0.10 + 0.40 * 0.5, 4)


def test_salvare_un_secondo_modello_non_cancella_il_primo() -> None:
    sessione = _FakeSession()
    save_price(sessione, "gemini-3.5-flash-lite", ModelPrice(0.10, 0.40))  # type: ignore[arg-type]
    save_price(sessione, "gemini-3.6-flash", ModelPrice(0.30, 1.20))  # type: ignore[arg-type]

    prezzi = load_pricing(sessione)  # type: ignore[arg-type]
    assert set(prezzi) == {"gemini-3.5-flash-lite", "gemini-3.6-flash"}
    assert sessione.settings[PRICING_SETTING_KEY].value["gemini-3.5-flash-lite"] == {
        "input_per_million": 0.10,
        "output_per_million": 0.40,
        "currency": "USD",
    }


def test_una_riga_malformata_viene_ignorata_non_esplode() -> None:
    """Un valore scritto a mano male lascia quel modello senza prezzo, non rompe la pagina."""
    sessione = _FakeSession()
    sessione.settings[PRICING_SETTING_KEY] = Setting(
        key=PRICING_SETTING_KEY,
        value={"modello-rotto": {"input_per_million": "non un numero"}},
    )
    assert load_pricing(sessione) == {}  # type: ignore[arg-type]


def test_un_modello_senza_prezzo_resta_nd_anche_con_altri_configurati() -> None:
    sessione = _FakeSession()
    save_price(sessione, "gemini-3.5-flash-lite", ModelPrice(0.10, 0.40))  # type: ignore[arg-type]
    prezzi = load_pricing(sessione)  # type: ignore[arg-type]
    assert estimate_cost(prezzi, "gemini-3.6-flash", 100, 100) is None
