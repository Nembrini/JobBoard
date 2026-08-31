"""Test del pool di informazioni applicante."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobboard.schemas import ApplicantInfoBank, ApplicantInfoItem


def _voce(**overrides: object) -> ApplicantInfoItem:
    defaults: dict[str, object] = {
        "id": "disponibilita-trasferte",
        "label": "Disponibilità",
        "text": "Disponibile a trasferte di due giorni al mese.",
    }
    return ApplicantInfoItem(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_id_non_kebab_case_e_rifiutato() -> None:
    with pytest.raises(ValidationError):
        _voce(id="Disponibilità Trasferte")


def test_id_duplicati_nel_pool_sono_rifiutati() -> None:
    with pytest.raises(ValidationError):
        ApplicantInfoBank(items=[_voce(), _voce()])


def test_to_prompt_block_espone_l_id_e_l_etichetta() -> None:
    bank = ApplicantInfoBank(items=[_voce()])
    testo = bank.to_prompt_block()
    assert "[id: disponibilita-trasferte]" in testo
    assert "Disponibilità: Disponibile a trasferte di due giorni al mese." in testo


def test_to_prompt_block_vuoto_se_il_pool_e_vuoto() -> None:
    assert ApplicantInfoBank().to_prompt_block() == ""


def test_known_texts_mappa_id_al_testo() -> None:
    seconda = _voce(id="lingua-cinese", label="Lingue", text="HSK 3")
    bank = ApplicantInfoBank(items=[_voce(), seconda])
    assert bank.known_texts() == {
        "disponibilita-trasferte": "Disponibile a trasferte di due giorni al mese.",
        "lingua-cinese": "HSK 3",
    }
