"""Test del router di tier (Fase 7.1)."""

from __future__ import annotations

from jobboard.apply.router import decide_tier
from jobboard.models.enums import ApplicationTier, AtsType
from tests.conftest_cv import annuncio


def test_ats_noto_con_apply_url_e_tier_a() -> None:
    job = annuncio(ats_type=AtsType.GREENHOUSE, apply_url="https://boards.greenhouse.io/x/jobs/1")
    assert decide_tier(job) is ApplicationTier.A_AUTO


def test_ats_sconosciuto_con_apply_url_e_tier_b() -> None:
    job = annuncio(ats_type=AtsType.RECRUITEE, apply_url="https://example.com/apply/1")
    assert decide_tier(job) is ApplicationTier.B_ASSISTED


def test_senza_apply_url_e_tier_c_anche_con_un_ats_noto() -> None:
    """Un ATS dei quattro non basta: senza il link diretto non c'e' un form da aprire."""
    job = annuncio(ats_type=AtsType.GREENHOUSE, apply_url=None)
    assert decide_tier(job) is ApplicationTier.C_MANUAL


def test_ats_sconosciuto_senza_apply_url_e_tier_c() -> None:
    job = annuncio(ats_type=AtsType.UNKNOWN, apply_url=None)
    assert decide_tier(job) is ApplicationTier.C_MANUAL
