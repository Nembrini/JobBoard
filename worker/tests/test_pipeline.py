"""Test della pipeline: normalizzazione, retribuzione, testo, dedup.

Tutto in locale: nessuna chiamata di rete, nessun database. Le fonti vengono
simulate costruendo :class:`RawJob` a mano, che e' anche il modo in cui si
documenta cosa ciascuna API restituisce davvero.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from jobboard.models.enums import AtsType, ContractType, SalaryPeriod, Seniority, WorkMode
from jobboard.pipeline import dedup
from jobboard.pipeline import normalize as norm
from jobboard.pipeline import salary as sal
from jobboard.pipeline import text as txt
from jobboard.sources.base import RawJob, title_matches


def _raw(**overrides: object) -> RawJob:
    base: dict[str, object] = {
        "source": "prova",
        "external_id": "1",
        "title": "Backend Developer",
        "company": "Acme Srl",
        "url": "https://example.com/1",
    }
    return RawJob(**{**base, **overrides})  # type: ignore[arg-type]


# --- guardia contro la corruzione dei pattern ---------------------------------


def test_no_control_characters_in_the_source() -> None:
    """Regressione su un guasto reale e silenzioso.

    Uno script di manutenzione ha scritto ``\\b`` dentro una stringa Python non
    raw: e' diventato un **backspace** (0x08) invece del confine di parola delle
    regex. Trenta pattern sono rimasti sintatticamente validi e semanticamente
    morti — nessun errore, nessun test rosso, solo classificazioni sempre vuote.
    """
    radice = Path(__file__).resolve().parent.parent / "jobboard"
    ammessi = {"\n", "\t"}
    colpevoli = []

    for percorso in radice.rglob("*.py"):
        testo = percorso.read_text(encoding="utf-8")
        for numero, riga in enumerate(testo.splitlines(), start=1):
            sospetti = [c for c in riga if ord(c) < 32 and c not in ammessi]
            if sospetti:
                colpevoli.append(f"{percorso.name}:{numero} {[hex(ord(c)) for c in sospetti]}")

    assert not colpevoli, "caratteri di controllo nel sorgente: " + "; ".join(colpevoli)


# --- filtro per parole chiave -------------------------------------------------


@pytest.mark.parametrize(
    "titolo",
    [
        "Senior Software Engineer",
        "Backend Developer (Java)",
        "Software Developers Wanted",
        "Software Engineering Manager",
    ],
)
def test_title_matches_finds_the_real_job_titles(titolo: str) -> None:
    """Regressione reale: il confronto per frase non trovava nulla.

    Cercando "software developer" come sottostringa, nessuno di questi titoli
    corrispondeva — ed erano tutti annunci da tenere. Quattro fonti su nove
    restituivano zero risultati.
    """
    assert title_matches(titolo, ("software developer",))


def test_an_italian_title_needs_an_italian_keyword() -> None:
    """Il filtro confronta parole, non traduce.

    Un annuncio milanese si intitola "Sviluppatore Backend": con la sola ricerca
    inglese non passa. Per questo i termini di ricerca vengono seminati anche in
    italiano (vedi ``_SYNONYMS_IT`` in ``pipeline.ingest``).
    """
    assert not title_matches("Sviluppatore Backend", ("software developer",))
    assert title_matches("Sviluppatore Backend", ("sviluppatore backend",))


def test_the_seeded_keywords_cover_both_languages() -> None:
    from jobboard.pipeline.ingest import _keywords_from_profile
    from jobboard.schemas import Contact, Experience, MasterProfile

    profilo = MasterProfile(
        contact=Contact(full_name="Filippo Nembrini"),
        headline="Software Developer",
        experiences=[
            Experience(
                id="acme-backend-developer",
                company="Acme",
                role="Backend Developer",
                start="2024-01",
            )
        ],
    )

    parole = _keywords_from_profile(profilo)
    assert "software developer" in parole
    assert "backend developer" in parole
    assert "sviluppatore backend" in parole
    # I termini inglesi vengono prima: le fonti a budget consumano dall'inizio.
    assert parole.index("software developer") < parole.index("sviluppatore software")


@pytest.mark.parametrize(
    "titolo",
    ["Sales Jedi", "Office Assistant", "Account Executive", "Compounding Pharmacy Technician"],
)
def test_title_matches_rejects_unrelated_roles(titolo: str) -> None:
    assert not title_matches(titolo, ("software developer", "backend developer"))


def test_title_matches_ignores_seniority_words() -> None:
    """ "Senior" non e' un criterio di pertinenza: e' in mezzo titolo."""
    assert not title_matches("Senior Account Manager", ("senior software developer",))


def test_title_matches_can_use_tags_as_well() -> None:
    """Su RemoteOK la classificazione vera dell'annuncio sta nei tag."""
    assert title_matches("Remote Engineer Wanted", ("backend",), extra="golang backend api")


def test_no_keywords_means_everything_passes() -> None:
    assert title_matches("Qualunque cosa", ())


def test_short_tokens_are_not_matched_by_prefix() -> None:
    """ "qa" non deve pescare "Qatar"."""
    assert not title_matches("Sales Manager Qatar", ("qa",))
    assert title_matches("QA Engineer", ("qa",))


# --- famiglia di ruolo --------------------------------------------------------


@pytest.mark.parametrize(
    ("titolo", "atteso"),
    [
        ("Fullstack Developer", "Fullstack Developer"),
        ("Backend Developer", "Backend Developer"),
        ("Senior Software Engineer", "Software Developer"),
        ("Android Developer", "Mobile Developer"),
        ("Machine Learning Engineer", "Machine Learning Engineer"),
        ("Site Reliability Engineer", "DevOps / SRE"),
        ("Sviluppatore Java", "Software Developer"),
        ("Sales Jedi", None),
    ],
)
def test_job_family(titolo: str, atteso: str | None) -> None:
    """E' la colonna "tipo di lavoro" della dashboard: deve dire qualcosa di vero."""
    assert norm.job_family(titolo) == atteso


def test_specific_families_win_over_generic_ones() -> None:
    """ "Machine Learning Engineer" contiene "engineer": l'ordine della tabella conta."""
    assert norm.job_family("Machine Learning Engineer") != "Software Developer"


# --- modalita' di lavoro ------------------------------------------------------


def test_source_flag_beats_the_description() -> None:
    job = _raw(is_remote=True, description="Our office in Milan is lovely")
    assert norm.work_mode(job, job.description) is WorkMode.REMOTE


def test_hybrid_in_the_title_wins_over_the_remote_flag() -> None:
    """Gli aggregatori appiattiscono l'ibrido su una spunta "remoto" si'/no."""
    job = _raw(title="Backend Developer (Hybrid)", is_remote=True)
    assert norm.work_mode(job, "") is WorkMode.HYBRID


def test_the_description_is_the_last_resort() -> None:
    job = _raw(description="Lavoro da remoto, tre giorni a settimana.")
    assert norm.work_mode(job, job.description) is WorkMode.REMOTE


def test_no_signal_means_unknown_not_onsite() -> None:
    """In sede per default filtrerebbe via annunci buoni: e' un'invenzione."""
    assert norm.work_mode(_raw(), "Cerchiamo una persona in gamba.") is WorkMode.UNKNOWN


# --- contratto e livello ------------------------------------------------------


@pytest.mark.parametrize(
    ("suggerimento", "atteso"),
    [
        ("Full-time", ContractType.PERMANENT),
        ("Part-time", ContractType.PART_TIME),
        ("Internship", ContractType.INTERNSHIP),
        ("Freelance", ContractType.CONTRACT),
        ("Tempo determinato", ContractType.FIXED_TERM),
        ("", ContractType.UNKNOWN),
    ],
)
def test_contract_type(suggerimento: str, atteso: ContractType) -> None:
    assert norm.contract_type(_raw(contract_hint=suggerimento), "") is atteso


def test_a_full_time_internship_is_an_internship() -> None:
    """L'ordine della tabella conta: la voce piu' specifica vince."""
    job = _raw(title="Software Engineering Intern", contract_hint="Full-time")
    assert norm.contract_type(job, "") is ContractType.INTERNSHIP


@pytest.mark.parametrize(
    ("titolo", "atteso"),
    [
        ("Senior Backend Developer", Seniority.SENIOR),
        ("Junior Developer", Seniority.JUNIOR),
        ("Software Engineering Intern", Seniority.INTERN),
        ("Tech Lead", Seniority.LEAD),
        ("Principal Engineer", Seniority.PRINCIPAL),
        ("Backend Developer", Seniority.UNKNOWN),
    ],
)
def test_seniority_from_title(titolo: str, atteso: Seniority) -> None:
    assert norm.seniority(_raw(title=titolo)) is atteso


def test_the_source_field_beats_the_title() -> None:
    """ "Senior" nel titolo e' marketing; il campo della fonte e' un dato."""
    job = _raw(title="Senior Developer", seniority_hint="Entry level")
    assert norm.seniority(job) is Seniority.JUNIOR


# --- titolo e luogo -----------------------------------------------------------


@pytest.mark.parametrize(
    "titolo",
    ["Softwareentwickler (m/w/d)", "Softwareentwickler - m/w/d", "Softwareentwickler m/w/d"],
)
def test_german_gender_suffixes_are_removed(titolo: str) -> None:
    """Con il suffisso la chiave canonica non collide e la dedup fallisce."""
    assert norm.tidy_title(titolo) == "Softwareentwickler"


@pytest.mark.parametrize(
    ("grezzo", "paese", "atteso"),
    [
        ("Milano, Italia", None, ("Milano", None, "IT")),
        ("Berlin, Germany", None, ("Berlin", None, "DE")),
        ("San Francisco, CA", "US", ("San Francisco", "CA", "US")),
        ("Italia", None, (None, None, "IT")),
        ("Remote", None, (None, None, None)),
        ("Europe", None, (None, None, None)),
        (None, "NL", (None, None, "NL")),
    ],
)
def test_split_location(
    grezzo: str | None, paese: str | None, atteso: tuple[str | None, str | None, str | None]
) -> None:
    assert norm.split_location(grezzo, paese) == atteso


def test_the_declared_country_wins_over_the_text() -> None:
    """Il campo strutturato e' un dato; il testo e' quello che ha scritto qualcuno."""
    assert norm.split_location("Zurich, Germany", "CH")[2] == "CH"


# --- retribuzione -------------------------------------------------------------


def test_no_salary_is_not_stated_not_zero() -> None:
    """La dashboard promette "RAL se dichiarata": mai una stima, mai uno zero."""
    for testo in ("", "competitive salary", "salario interessante", None):
        assert sal.parse(testo).is_stated is False


@pytest.mark.parametrize(
    ("testo", "minimo", "massimo", "valuta", "periodo"),
    [
        ("30.000 - 40.000 EUR annui", 30000, 40000, "EUR", SalaryPeriod.YEARLY),
        ("€45.000 all'anno", 45000, None, "EUR", SalaryPeriod.YEARLY),
        ("$211.4K - $290.6K", 211400, 290600, "USD", SalaryPeriod.YEARLY),
        ("15 €/ora", 15, None, "EUR", SalaryPeriod.HOURLY),
        ("£55,000 per year", 55000, None, "GBP", SalaryPeriod.YEARLY),
    ],
)
def test_salary_from_free_text(
    testo: str, minimo: int, massimo: int | None, valuta: str, periodo: SalaryPeriod
) -> None:
    risultato = sal.parse(testo)
    assert (risultato.min, risultato.max) == (minimo, massimo)
    assert risultato.currency == valuta
    assert risultato.period is periodo


def test_thousands_separator_is_read_by_position_not_by_language() -> None:
    """ "€30.000" vale trentamila in italiano e trenta in inglese.

    La regola e' posizionale: un separatore seguito da esattamente tre cifre
    separa le migliaia. Funziona su entrambe le convenzioni.
    """
    assert sal.parse("€30.000 annui").min == 30000
    assert sal.parse("$30,000 per year").min == 30000
    assert sal.parse("$1,234.56 per hour").min == 1234


def test_italian_extra_monthly_payments_are_honoured() -> None:
    """1.800 x 14 mensilita' sono 25.200 all'anno, non 21.600.

    Non e' una stima: il numero di mensilita' e' dichiarato nell'annuncio, e in
    Italia e' 13 o 14 molto piu' spesso di 12.
    """
    assert sal.parse("1.800 € al mese x 14 mensilità").eur_year_min == 25200


def test_hourly_rates_become_comparable_annual_figures() -> None:
    assert sal.parse("15 €/ora").eur_year_min == 15 * 1720


def test_conversion_is_skipped_when_the_currency_is_unknown() -> None:
    """Meglio nessun valore confrontabile che uno inventato."""
    risultato = sal.parse("40.000 - 50.000 annui", default_currency=None)
    assert risultato.is_stated is True
    assert risultato.eur_year_min is None


def test_a_predicted_salary_is_never_treated_as_stated() -> None:
    """Adzuna stima la RAL quando l'annuncio non la dichiara: va scartata."""
    from jobboard.sources.adzuna import _to_raw_job

    entry = {
        "id": "1",
        "title": "Backend Developer",
        "salary_min": 35000,
        "salary_max": 45000,
        "salary_is_predicted": "1",
    }
    job = _to_raw_job(entry, "it")
    assert job is not None
    assert job.salary_min is None and job.salary_max is None


def test_a_declared_salary_survives() -> None:
    from jobboard.sources.adzuna import _to_raw_job

    entry = {
        "id": "1",
        "title": "Backend Developer",
        "salary_min": 35000,
        "salary_max": 45000,
        "salary_is_predicted": "0",
    }
    job = _to_raw_job(entry, "it")
    assert job is not None
    assert (job.salary_min, job.salary_max) == (35000, 45000)


# --- testo e impronte ---------------------------------------------------------


def test_html_becomes_readable_text_with_the_bullets_intact() -> None:
    """Nelle job description i requisiti sono quasi sempre un ``<ul>``."""
    risultato = txt.html_to_text(
        "<p>Cerchiamo:</p><ul><li>Python</li><li>PostgreSQL</li></ul><script>x=1</script>"
    )
    assert "- Python" in risultato
    assert "- PostgreSQL" in risultato
    assert "x=1" not in risultato


def test_company_suffixes_do_not_break_the_match() -> None:
    """ "Acme S.r.l." su un portale e "Acme" su un altro sono la stessa azienda."""
    assert txt.normalize_company("Acme S.r.l.") == txt.normalize_company("Acme")
    assert txt.normalize_company("Acme GmbH") == txt.normalize_company("ACME")


def test_a_name_made_only_of_suffixes_keeps_its_words() -> None:
    """Una chiave vuota collegherebbe fra loro aziende diverse."""
    assert txt.normalize_company("Group Holding") != ""


def test_similar_texts_have_close_fingerprints() -> None:
    a = "Cerchiamo un backend developer con esperienza in Python, FastAPI e PostgreSQL. " * 4
    b = a + "Offriamo smart working e formazione continua."
    diverso = "Cercasi cuoco per ristorante di pesce, esperienza in cucina mediterranea. " * 4

    assert txt.hamming(txt.simhash(a), txt.simhash(b)) <= dedup.MAX_HAMMING_DISTANCE
    assert txt.hamming(txt.simhash(a), txt.simhash(diverso)) > dedup.MAX_HAMMING_DISTANCE


def test_the_fingerprint_survives_the_trip_through_postgres() -> None:
    """Postgres non ha interi a 64 bit senza segno: la conversione va e torna."""
    impronta = txt.simhash("un testo qualsiasi abbastanza lungo da contare qualcosa")
    assert txt.from_signed_64(txt.to_signed_64(impronta)) == impronta


def test_a_fingerprint_with_the_top_bit_set_becomes_negative() -> None:
    alto = (1 << 63) | 12345
    assert txt.to_signed_64(alto) < 0
    assert txt.from_signed_64(txt.to_signed_64(alto)) == alto


# --- dedup --------------------------------------------------------------------


def _normalized(**overrides: object) -> norm.NormalizedJob:
    return norm.normalize(_raw(**overrides))


def test_the_same_job_from_two_sources_becomes_one() -> None:
    a = _normalized(source="adzuna", external_id="a", location="Milano, Italia")
    b = _normalized(source="jooble", external_id="b", location="Milano, Italia")

    gruppi = dedup.group([a, b])
    assert len(gruppi) == 1
    assert gruppi[0].sources == ["adzuna", "jooble"]


def test_two_different_jobs_stay_separate() -> None:
    a = _normalized(title="Backend Developer", location="Milano, Italia")
    b = _normalized(title="Frontend Developer", external_id="2", location="Roma, Italia")
    assert len(dedup.group([a, b])) == 2


def test_the_ats_link_always_wins() -> None:
    """E' l'unico che porta al form vero, quindi l'unico che abilita il Tier A."""
    aggregatore = _normalized(source="jsearch", external_id="a", url="https://jsearch/redirect")
    ats = _normalized(
        source="greenhouse",
        external_id="b",
        url="https://boards.greenhouse.io/acme/jobs/7",
        apply_url="https://boards.greenhouse.io/acme/jobs/7",
        ats_type=AtsType.GREENHOUSE,
        ats_board_token="acme",
        ats_job_id="7",
    )

    unito = dedup.merge([aggregatore, ats])
    assert unito.ats_type is AtsType.GREENHOUSE
    assert unito.apply_url == "https://boards.greenhouse.io/acme/jobs/7"
    assert unito.ats_board_token == "acme"


def test_the_declared_salary_survives_the_merge() -> None:
    """Ogni variante puo' avere il pezzo che manca alle altre."""
    con_ral = _normalized(source="adzuna", external_id="a", salary_min=40000, salary_currency="EUR")
    senza = _normalized(source="greenhouse", external_id="b", ats_type=AtsType.GREENHOUSE)

    unito = dedup.merge([senza, con_ral])
    assert unito.salary.is_stated
    assert unito.salary.min == 40000


def test_the_longest_description_wins() -> None:
    """Jooble restituisce un estratto di due righe, la board ATS il testo intero."""
    breve = _normalized(source="jooble", external_id="a", description="Due righe.")
    lunga = _normalized(
        source="lever", external_id="b", description="<p>" + "Testo. " * 200 + "</p>"
    )

    assert len(dedup.merge([breve, lunga]).description_clean) > 500


def test_the_oldest_publication_date_wins() -> None:
    """Gli aggregatori riportano quando hanno indicizzato, non quando e' uscito."""
    vecchio = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    recente = dt.datetime(2026, 8, 20, tzinfo=dt.UTC)

    unito = dedup.merge(
        [
            _normalized(source="jsearch", external_id="a", posted_at=recente),
            _normalized(source="greenhouse", external_id="b", posted_at=vecchio),
        ]
    )
    assert unito.posted_at == vecchio


def test_identical_text_from_different_companies_is_not_merged() -> None:
    """Le agenzie ripubblicano lo stesso testo per clienti diversi."""
    testo = "<p>" + "Cerchiamo backend developer con Python e PostgreSQL. " * 20 + "</p>"
    a = _normalized(company="Acme", description=testo, location="Milano, Italia")
    b = _normalized(company="Globex", external_id="2", description=testo, location="Roma, Italia")

    assert len(dedup.group([a, b])) == 2


def test_a_short_snippet_is_never_matched_by_fingerprint() -> None:
    """Su due righe di testo il SimHash produce impronte casuali."""
    a = _normalized(company="Acme", title="Backend Developer", description="Due righe.")
    b = _normalized(
        company="Acme", external_id="2", title="Frontend Developer", description="Altre due."
    )
    assert len(dedup.group([a, b])) == 2


def test_german_compound_titles_are_classified() -> None:
    """Regressione reale: nessun annuncio tedesco veniva classificato.

    Il tedesco compone i nomi: "Softwareentwickler" e' una parola sola, e un
    pattern con il confine di parola in coda non ci trovava dentro ne'
    "software" ne' "entwickler". La Germania e' uno dei mercati scelti.
    """
    assert norm.job_family("Softwareentwickler C++ / Qt") == "Software Developer"
    assert norm.job_family("Senior Softwareentwickler") == "Software Developer"
    assert norm.job_family("Software Engineering Manager") == "Software Developer"


def test_non_technical_titles_stay_unclassified() -> None:
    """Meglio nessuna famiglia che una sbagliata: la colonna deve dire il vero."""
    for titolo in ("Trimmer", "Assistant Manager", "Senior Game Producer"):
        assert norm.job_family(titolo) is None
