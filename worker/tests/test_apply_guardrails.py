"""Test dei guardrail (Fase 7.5): decisioni pure, nessun database."""

from __future__ import annotations

from jobboard.apply.guardrails import check_daily_cap, check_new_company


def test_sotto_il_tetto_passa() -> None:
    assert check_daily_cap(3, cap=10).ok


def test_al_tetto_si_ferma() -> None:
    esito = check_daily_cap(10, cap=10)
    assert not esito.ok
    assert "10/10" in (esito.reason or "")


def test_sopra_il_tetto_si_ferma_comunque() -> None:
    assert not check_daily_cap(11, cap=10).ok


def test_prima_candidatura_verso_un_azienda_richiede_conferma() -> None:
    esito = check_new_company(0, confirmed=False)
    assert not esito.ok
    assert esito.needs_company_confirmation


def test_prima_candidatura_con_conferma_esplicita_passa() -> None:
    esito = check_new_company(0, confirmed=True)
    assert esito.ok
    assert not esito.needs_company_confirmation


def test_una_seconda_candidatura_verso_la_stessa_azienda_non_richiede_conferma() -> None:
    esito = check_new_company(1, confirmed=False)
    assert esito.ok
