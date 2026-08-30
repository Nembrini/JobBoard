"""Test strutturali sui selettori noti (Fase 7.2).

Non provano che i selettori funzionino su un form vero — nessun test di questo
repository puo' farlo, vedi ``jobboard/apply/browser.py`` — solo che la tabella
sia internamente coerente: chiavi valide, nessun selettore vuoto.
"""

from __future__ import annotations

from jobboard.apply.fields import BOOLEAN_FIELDS, TEXT_FIELDS
from jobboard.apply.selectors import BY_ATS, known_fields
from jobboard.models.enums import TIER_A_ATS, AtsType

_CHIAVI_VALIDE = set(TEXT_FIELDS) | set(BOOLEAN_FIELDS) | {"resume", "cover_letter"}


def test_ogni_ats_di_tier_a_ha_una_voce() -> None:
    for ats in TIER_A_ATS:
        assert ats in BY_ATS, f"{ats} e' Tier A ma non ha selettori noti"


def test_ogni_voce_ha_una_chiave_logica_valida() -> None:
    for ats, campi in BY_ATS.items():
        for campo in campi:
            messaggio = f"{ats}: chiave sconosciuta {campo.logical_key!r}"
            assert campo.logical_key in _CHIAVI_VALIDE, messaggio


def test_ogni_voce_ha_almeno_un_selettore_non_vuoto() -> None:
    for ats, campi in BY_ATS.items():
        for campo in campi:
            assert campo.css, f"{ats}/{campo.logical_key}: nessun selettore"
            assert all(s.strip() for s in campo.css)


def test_ogni_ats_di_tier_a_sa_trovare_il_campo_del_curriculum() -> None:
    for ats in TIER_A_ATS:
        chiavi = {c.logical_key for c in known_fields(ats)}
        assert "resume" in chiavi, f"{ats}: nessun selettore per il curriculum"


def test_un_ats_fuori_tier_a_non_ha_selettori_dedicati() -> None:
    assert known_fields(AtsType.RECRUITEE) == ()
