"""L'adapter JSearch contro la forma reale della v5.

Questi test esistono perche' la v5 ha cambiato **quattro cose insieme** senza che
niente lo segnalasse a compilazione: l'endpoint (``/search`` -> ``/search-v2``,
che risponde 404), la forma della risposta (``data`` da elenco a oggetto), il
luogo (i campi strutturati arrivano quasi sempre vuoti) e la data (le due colonne
assolute arrivano vuote, resta solo testo relativo e localizzato).

Il campione qui sotto e' ridotto ma fedele a una risposta vera del 29 agosto
2026: se un giorno la forma cambia ancora, a rompersi e' un test invece della
run notturna.
"""

from __future__ import annotations

import datetime as dt

import pytest

from jobboard.sources.jsearch import _da_relativa, _location, _to_raw_job

#: Un annuncio come lo restituisce davvero la v5. Notare i campi a ``None``:
#: non sono una semplificazione del test, sono il caso normale.
ANNUNCIO = {
    "job_id": "Z1czSEExMjNnNjEyT09RTEFBQUFBQT09",
    "job_title": "| SOFTWARE ENGINEER | 108398 |",
    "employer_name": "Etjca Group",
    "job_publisher": "LinkedIn",
    "job_employment_type": "Full-time",
    "job_apply_link": "https://it.linkedin.com/jobs/view/software-engineer-108398",
    "job_apply_is_direct": False,
    "apply_options": [
        {
            "apply_link": "https://it.linkedin.com/jobs/view/software-engineer-108398",
            "is_direct": False,
            "publisher": "LinkedIn",
        }
    ],
    "job_description": "Panoramica di presentazione del ruolo.",
    "job_city": None,
    "job_state": None,
    "job_country": None,
    "job_location": "Ivrea TO     •  tramite LinkedIn",
    "job_is_remote": False,
    "job_posted_at": "4 giorni fa",
    "job_posted_at_datetime_utc": None,
    "job_posted_at_timestamp": None,
    "job_min_salary": None,
    "job_max_salary": None,
    "job_salary_string": None,
    "job_salary_period": None,
}


def test_il_portale_finisce_nel_publisher() -> None:
    """E' l'unico motivo per cui questa fonte esiste."""
    job = _to_raw_job(ANNUNCIO, "it")
    assert job is not None
    assert job.publisher == "LinkedIn"


def test_il_luogo_perde_la_coda_del_portale() -> None:
    """``job_location`` contiene "Ivrea TO • tramite LinkedIn".

    Senza ripulirla, "tramite LinkedIn" entrerebbe nella citta' e quindi nella
    chiave canonica di dedup: lo stesso annuncio visto da Adzuna come "Ivrea" non
    collide piu', e in dashboard compaiono due righe per un posto solo.
    """
    assert _location(ANNUNCIO) == "Ivrea TO"


def test_i_campi_strutturati_vincono_su_job_location() -> None:
    entry = {**ANNUNCIO, "job_city": "Orbassano", "job_state": "Piemonte"}
    assert _location(entry) == "Orbassano, Piemonte"


def test_il_paese_ripiega_su_quello_richiesto() -> None:
    """``job_country`` e' arrivato valorizzato su 1 annuncio su 10.

    Il ripiego non e' una supposizione sul singolo annuncio: e' il filtro che
    Google ha applicato per restituirlo. Senza, il filtro per paese dello Stadio
    0 non avrebbe niente su cui lavorare.
    """
    job = _to_raw_job(ANNUNCIO, "it")
    assert job is not None and job.country == "IT"

    dichiarato = _to_raw_job({**ANNUNCIO, "job_country": "de"}, "it")
    assert dichiarato is not None and dichiarato.country == "DE"


def test_la_data_viene_dal_testo_relativo_quando_le_altre_mancano() -> None:
    job = _to_raw_job(ANNUNCIO, "it")
    assert job is not None and job.posted_at is not None
    giorni = (dt.datetime.now(dt.UTC) - job.posted_at).days
    assert giorni == 4


def test_la_data_assoluta_ha_la_precedenza() -> None:
    entry = {**ANNUNCIO, "job_posted_at_datetime_utc": "2026-08-01T09:00:00Z"}
    job = _to_raw_job(entry, "it")
    assert job is not None and job.posted_at is not None
    assert job.posted_at.date() == dt.date(2026, 8, 1)


def test_apply_url_solo_se_il_link_e_diretto() -> None:
    """Solo un link diretto puo' portare a una candidatura automatica (Tier A).

    Su un annuncio ripubblicato da LinkedIn non c'e': dichiararlo lo farebbe
    finire nel Tier A, dove il worker proverebbe a fare POST contro una pagina
    che non e' un form ATS.
    """
    assert _to_raw_job(ANNUNCIO, "it").apply_url is None

    diretto = {
        **ANNUNCIO,
        "apply_options": [
            {"apply_link": "https://boards.greenhouse.io/x/jobs/1", "is_direct": True},
            {"apply_link": "https://it.linkedin.com/jobs/view/1", "is_direct": False},
        ],
    }
    assert _to_raw_job(diretto, "it").apply_url == "https://boards.greenhouse.io/x/jobs/1"


ORA = dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("testo", "giorni"),
    [
        ("4 giorni fa", 4),
        ("5 days ago", 5),
        ("vor 3 Tagen", 3),
        ("hace 2 semanas", 14),
        ("2 uur geleden", 0),
        ("há 3 dias", 3),
        ("oggi", 0),
        ("ieri", 1),
        ("un giorno fa", 1),
        ("a day ago", 1),
        ("yesterday", 1),
    ],
)
def test_date_relative_nelle_lingue_dei_mercati(testo: str, giorni: int) -> None:
    """La data arriva localizzata nella lingua del paese interrogato.

    Non e' pignoleria: senza questa lettura **nessun** annuncio JSearch avrebbe
    una data, quindi colonna vuota e ordinamento per data che li manda tutti in
    fondo.
    """
    letta = _da_relativa(testo, ORA)
    assert letta is not None
    assert (ORA - letta).days == giorni


@pytest.mark.parametrize("testo", ["", "   ", "boh", "presto", "da definire"])
def test_una_data_incomprensibile_resta_vuota(testo: str) -> None:
    """Meglio nessuna data che una inventata: a valle "vuoto" e' gestito."""
    assert _da_relativa(testo, ORA) is None


def test_un_annuncio_senza_id_o_titolo_viene_scartato() -> None:
    assert _to_raw_job({**ANNUNCIO, "job_id": None}, "it") is None
    assert _to_raw_job({**ANNUNCIO, "job_title": ""}, "it") is None
