"""Test del piano di campi (Fase 7.2/7.3): da CandidateAnswers + MasterProfile a valori."""

from __future__ import annotations

from pathlib import Path

from jobboard.apply.fields import build_plan
from tests.conftest_apply import candidato
from tests.conftest_cv import annuncio, profilo


def test_nome_e_cognome_si_dividono_sulla_prima_parola() -> None:
    piano = build_plan(candidato(), profilo(), annuncio())
    assert piano.values["first_name"] == "Filippo"
    assert piano.values["last_name"] == "Nembrini"
    assert piano.values["full_name"] == "Filippo Nembrini"


def test_un_nome_composto_di_una_sola_parola_non_ha_cognome() -> None:
    piano = build_plan(candidato(full_name="Madonna"), profilo(), annuncio())
    assert piano.values["first_name"] == "Madonna"
    assert piano.values["last_name"] == ""


def test_email_e_telefono_passano_diretti() -> None:
    piano = build_plan(candidato(), profilo(), annuncio())
    assert piano.values["email"] == "filippo@example.com"
    assert piano.values["phone"] == "+39 333 1234567"


def test_campi_opzionali_assenti_non_finiscono_nel_piano() -> None:
    """Nessuna stringa vuota: un campo non dichiarato manca dal dizionario, non c'e' vuoto."""
    piano = build_plan(candidato(phone=None, github_url=None), profilo(), annuncio())
    assert "phone" not in piano.values
    assert "github_url" not in piano.values


def test_intervallo_di_ral_si_scrive_come_range() -> None:
    piano = build_plan(candidato(), profilo(), annuncio())
    assert piano.values["salary_expectation"] == "45000-55000 EUR"


def test_ral_singola_non_ripete_l_intervallo() -> None:
    piano = build_plan(
        candidato(salary_expectation_min=50000, salary_expectation_max=50000),
        profilo(),
        annuncio(),
    )
    assert piano.values["salary_expectation"] == "50000 EUR"


def test_senza_ral_numerica_si_usa_la_nota_testuale() -> None:
    piano = build_plan(
        candidato(
            salary_expectation_min=None,
            salary_expectation_max=None,
            ats_answers={
                "years_of_experience": 4,
                "salary_note": "In linea con il mercato",
            },
        ),
        profilo(),
        annuncio(),
    )
    assert piano.values["salary_expectation"] == "In linea con il mercato"


def test_booleani_dichiarati_finiscono_nel_dizionario_booleano() -> None:
    piano = build_plan(candidato(), profilo(), annuncio())
    assert piano.booleans == {
        "requires_sponsorship_now": False,
        "requires_sponsorship_future": False,
        "willing_to_relocate": True,
        "willing_to_travel": True,
    }


def test_sponsorship_non_dichiarata_resta_fuori_dal_piano() -> None:
    """Un ``None`` non diventa mai ``False``: sarebbe una risposta inventata."""
    piano = build_plan(
        candidato(
            ats_answers={
                "years_of_experience": 4,
                "requires_sponsorship_now": None,
                "requires_sponsorship_future": None,
            }
        ),
        profilo(),
        annuncio(),
    )
    assert "requires_sponsorship_now" not in piano.booleans
    assert "requires_sponsorship_future" not in piano.booleans
    # willing_to_relocate ha un default non-None sullo schema: c'e' sempre.
    assert "willing_to_relocate" in piano.booleans


def test_domande_extra_finiscono_nel_piano_con_la_loro_chiave() -> None:
    risposte = {"years_of_experience": 4, "extra": {"Perche' questa azienda?": "X"}}
    piano = build_plan(candidato(ats_answers=risposte), profilo(), annuncio())
    assert piano.values["Perche' questa azienda?"] == "X"


def test_il_percorso_del_cv_finisce_nel_piano() -> None:
    percorso = Path("/tmp/cv.pdf")
    piano = build_plan(candidato(), profilo(), annuncio(), resume_path=percorso)
    assert piano.resume_path == percorso


def test_gli_avvisi_del_candidato_si_ritrovano_nel_piano() -> None:
    piano = build_plan(candidato(languages={}), profilo(), annuncio())
    assert any("lingua" in avviso for avviso in piano.warnings)
