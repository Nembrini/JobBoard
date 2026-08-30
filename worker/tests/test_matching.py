"""Test dell'imbuto di matching: criteri, filtri, BM25, ordinamento, rubrica.

Nessun database e nessuna chiamata di rete. I modelli SQLAlchemy si istanziano
in memoria — i ``default=`` delle colonne li applica Postgres al momento della
INSERT, quindi qui ogni campo che il codice legge va valorizzato a mano, ed è la
ragione per cui esiste :func:`make_job`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from jobboard.ai import rubric
from jobboard.ai.client import LLMResult, LLMUsage
from jobboard.ai.rubric import (
    NEUTRAL,
    RUBRIC_WEIGHTS,
    JobAssessment,
    assess,
    build_prompt,
    neutralize_unknowable,
    weighted_total,
)
from jobboard.models import Job
from jobboard.models.enums import AtsType, ContractType, SalaryPeriod, Seniority, WorkMode
from jobboard.pipeline import criteria as criteria_mod
from jobboard.pipeline import rank as rank_mod
from jobboard.pipeline.bm25 import Bm25, ngrams, tokenize
from jobboard.pipeline.criteria import MatchCriteria, derive_seniority, experience_months
from jobboard.pipeline.filters import apply_filters
from jobboard.pipeline.match import _row, _write_stage1, select_finalists
from jobboard.pipeline.rank import Ranked
from jobboard.schemas import Bullet, Contact, Experience, MasterProfile, Project, Skills

NOW = dt.datetime(2026, 8, 28, tzinfo=dt.UTC)


def make_job(**overrides: Any) -> Job:
    """Un annuncio completo di tutti i campi che i filtri leggono."""
    campi: dict[str, Any] = {
        "id": 1,
        "title": "Backend Developer",
        "company": "Acme",
        "company_normalized": "acme",
        "canonical_key": "acme|backend developer|milano",
        "content_hash": "x" * 64,
        "simhash": 0,
        "location_raw": "Milano",
        "city": "Milano",
        "region": None,
        "country": "IT",
        "work_mode": WorkMode.HYBRID,
        "salary_is_stated": False,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "salary_eur_year_min": None,
        "salary_eur_year_max": None,
        "contract_type": ContractType.PERMANENT,
        "seniority": Seniority.MID,
        "job_family": "Backend Developer",
        "description_raw": "",
        "description_clean": "Sviluppo di API REST in Java con Spring Boot e Oracle.",
        "lang": "it",
        "url": "https://example.com/1",
        "apply_url": None,
        "ats_type": AtsType.UNKNOWN,
        "ats_board_token": None,
        "ats_job_id": None,
        "posted_at": NOW - dt.timedelta(days=3),
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "is_active": True,
        "embedding": None,
        "embedding_model": None,
    }
    campi.update(overrides)
    return Job(**campi)


def make_profile(**overrides: Any) -> MasterProfile:
    dati: dict[str, Any] = {
        "contact": Contact(full_name="Filippo Nembrini", email="f@example.com", city="Milano"),
        "headline": "Software Developer",
        "experiences": [
            Experience(
                id="acme-backend",
                company="Acme",
                role="Backend Developer",
                start="2024-10",
                end="2025-08",
                tech=["Java", "Oracle"],
                bullets=[
                    Bullet(
                        id="acme-backend-1",
                        text="API REST in Java su database Oracle.",
                        skills=["REST API"],
                    )
                ],
            )
        ],
        "skills": Skills(hard=["Java", "Kotlin", "SQL", "Spring Boot"]),
    }
    dati.update(overrides)
    return MasterProfile(**dati)


# --- criteri ------------------------------------------------------------------


def test_experience_months_does_not_double_count_overlaps() -> None:
    """Due lavori sovrapposti non raddoppiano gli anni di esperienza.

    Succede davvero: si inizia il nuovo prima di chiudere il vecchio. Sommare le
    durate una per una promuoverebbe un junior a senior sulla carta.
    """
    profilo = make_profile(
        experiences=[
            Experience(id="a", company="A", role="Dev", start="2024-01", end="2024-12"),
            Experience(id="b", company="B", role="Dev", start="2024-06", end="2025-06"),
        ]
    )
    assert experience_months(profilo, today=dt.date(2026, 1, 1)) == 18


def test_experience_months_counts_an_ongoing_job_up_to_today() -> None:
    profilo = make_profile(
        experiences=[Experience(id="a", company="A", role="Dev", start="2025-01", end=None)]
    )
    assert experience_months(profilo, today=dt.date(2025, 6, 30)) == 6


def test_experience_months_merges_contiguous_periods() -> None:
    """Gennaio-giugno e luglio-dicembre sono un anno, non due tronconi da sommare a parte."""
    profilo = make_profile(
        experiences=[
            Experience(id="a", company="A", role="Dev", start="2024-01", end="2024-06"),
            Experience(id="b", company="B", role="Dev", start="2024-07", end="2024-12"),
        ]
    )
    assert experience_months(profilo, today=dt.date(2025, 1, 1)) == 12


def test_derive_seniority_from_months() -> None:
    def con_mesi(mesi: int) -> Seniority:
        fine = dt.date(2020, 1, 1)
        inizio_ordinale = fine.year * 12 + fine.month - mesi + 1
        inizio = f"{inizio_ordinale // 12:04d}-{inizio_ordinale % 12 or 12:02d}"
        profilo = make_profile(
            experiences=[Experience(id="a", company="A", role="Dev", start=inizio, end="2020-01")]
        )
        return derive_seniority(profilo)

    assert con_mesi(6) is Seniority.JUNIOR
    assert con_mesi(29) is Seniority.JUNIOR
    assert con_mesi(30) is Seniority.MID
    assert con_mesi(70) is Seniority.SENIOR
    assert con_mesi(120) is Seniority.LEAD


def test_derive_seniority_without_experience_is_intern() -> None:
    assert derive_seniority(make_profile(experiences=[])) is Seniority.INTERN


def test_unknown_seniority_never_excludes() -> None:
    """Da entrambi i lati: il silenzio dell'annuncio non è un rifiuto."""
    criteri = MatchCriteria(seniority=Seniority.JUNIOR)
    assert criteri.accepts_seniority(Seniority.UNKNOWN)
    assert MatchCriteria(seniority=Seniority.UNKNOWN).accepts_seniority(Seniority.PRINCIPAL)


def test_seniority_tolerance_is_symmetric() -> None:
    criteri = MatchCriteria(seniority=Seniority.MID, seniority_tolerance=1)
    assert criteri.accepts_seniority(Seniority.JUNIOR)
    assert criteri.accepts_seniority(Seniority.SENIOR)
    assert not criteri.accepts_seniority(Seniority.LEAD)
    assert not criteri.accepts_seniority(Seniority.INTERN)


def test_criteria_report_which_filters_are_off() -> None:
    """Un filtro spento per mancanza di dati deve dirlo, non fingere di aver lavorato."""
    criteri = criteria_mod._build({}, make_profile(), None)
    spenti = " ".join(criteri.inactive)
    assert "lingue" in spenti
    assert "work authorization" in spenti


def test_criteria_json_ignores_malformed_values() -> None:
    """La colonna è JSONB e la scrive la dashboard: non si può dare per scontato il tipo."""
    criteri = criteria_mod._build(
        {
            "countries": "IT",  # stringa invece di lista
            "seniority_tolerance": True,  # bool: in Python è un int, ma non è questo int
            "excluded_contract_types": ["internship", "inesistente"],
            "seniority": "arcimago",
        },
        make_profile(),
        None,
    )
    assert criteri.countries == frozenset(criteria_mod.DEFAULT_COUNTRIES)
    assert criteri.seniority_tolerance == 1
    assert criteri.excluded_contract_types == frozenset({ContractType.INTERNSHIP})
    assert criteri.seniority is not Seniority.UNKNOWN  # ridedotta dal profilo


# --- filtri (Stadio 0) --------------------------------------------------------


def _reasons(jobs: list[Job], criteri: MatchCriteria) -> list[str]:
    return [r.kind for r in apply_filters(jobs, criteri, today=NOW).rejected]


def test_missing_data_never_excludes() -> None:
    """Il caso più importante: un terzo degli annunci non dichiara il paese."""
    criteri = MatchCriteria(
        countries=frozenset({"IT"}),
        languages=frozenset({"it"}),
        seniority=Seniority.MID,
        authorized_countries=frozenset({"IT"}),
    )
    muto = make_job(country=None, lang=None, seniority=Seniority.UNKNOWN)
    risultato = apply_filters([muto], criteri, today=NOW)
    assert risultato.passed == [muto]


def test_blocked_company_is_rejected_by_normalized_name() -> None:
    criteri = MatchCriteria(blocked_companies=frozenset({"acme"}))
    assert _reasons([make_job(company="Acme S.r.l.")], criteri) == ["azienda"]


def test_language_not_spoken_is_rejected() -> None:
    criteri = MatchCriteria(languages=frozenset({"it", "en"}))
    assert _reasons([make_job(lang="de")], criteri) == ["lingua"]
    assert not _reasons([make_job(lang="en")], criteri)


def test_remote_job_escapes_the_market_filter_but_not_sponsorship() -> None:
    """Il remoto è il motivo per cui si guarda fuori dai propri mercati.

    Non però fuori dai paesi in cui si può lavorare: un remote da azienda
    statunitense chiede quasi sempre di essere autorizzati negli Stati Uniti.
    """
    criteri = MatchCriteria(
        countries=frozenset({"IT", "DE"}),
        authorized_countries=frozenset({"IT", "DE"}),
        remote_ignores_country=True,
    )
    remoto_us = make_job(country="US", work_mode=WorkMode.REMOTE)
    sede_us = make_job(country="US", work_mode=WorkMode.ON_SITE)

    assert _reasons([remoto_us], criteri) == ["sponsorship"]
    assert _reasons([sede_us], criteri) == ["paese"]


def test_market_filter_alone_lets_authorized_countries_through() -> None:
    criteri = MatchCriteria(countries=frozenset({"IT", "DE"}))
    assert not _reasons([make_job(country="DE", lang="de")], criteri)


def test_excluded_contract_and_work_mode() -> None:
    criteri = MatchCriteria(
        excluded_contract_types=frozenset({ContractType.INTERNSHIP}),
        excluded_work_modes=frozenset({WorkMode.ON_SITE}),
    )
    assert _reasons([make_job(contract_type=ContractType.INTERNSHIP)], criteri) == ["contratto"]
    assert _reasons([make_job(work_mode=WorkMode.ON_SITE)], criteri) == ["modalità"]


def test_stale_posting_is_rejected_but_an_undated_one_is_not() -> None:
    criteri = MatchCriteria(max_age_days=30)
    vecchio = make_job(posted_at=NOW - dt.timedelta(days=60))
    senza_data = make_job(posted_at=None)
    assert _reasons([vecchio], criteri) == ["età"]
    assert not _reasons([senza_data], criteri)


def test_salary_filter_only_bites_on_a_stated_salary() -> None:
    """Il silenzio sulla RAL non è una RAL bassa: è la regola di tutta la pipeline."""
    criteri = MatchCriteria(min_salary_eur_year=40_000)
    dichiarata = make_job(
        salary_is_stated=True,
        salary_eur_year_max=30_000,
        salary_currency="EUR",
        salary_period=SalaryPeriod.YEARLY,
    )
    stimata = make_job(salary_is_stated=False, salary_eur_year_max=30_000)
    assert _reasons([dichiarata], criteri) == ["retribuzione"]
    assert not _reasons([stimata], criteri)


def test_rejection_reason_fits_the_column() -> None:
    """``match.filtered_reason`` è ``String(200)``: un motivo più lungo la farebbe fallire."""
    criteri = MatchCriteria(blocked_companies=frozenset({"a" * 300}))
    scarto = apply_filters([make_job(company="a" * 300)], criteri, today=NOW).rejected[0]
    assert len(scarto.reason) <= 200


def test_filter_result_counts_by_kind() -> None:
    criteri = MatchCriteria(languages=frozenset({"it"}), seniority=Seniority.JUNIOR)
    jobs = [
        make_job(id=1, lang="de"),
        make_job(id=2, lang="de"),
        make_job(id=3, seniority=Seniority.PRINCIPAL),
        make_job(id=4),
    ]
    risultato = apply_filters(jobs, criteri, today=NOW)
    assert risultato.counts == {"lingua": 2, "livello": 1}
    assert len(risultato.passed) == 1
    assert risultato.examined == 4


# --- BM25 ---------------------------------------------------------------------


def test_tokenizer_keeps_technology_names_intact() -> None:
    """Spezzare "c++" o "ci/cd" li rende introvabili, ed è metà del punto di BM25.

    Le parole comuni restano fra i token: BM25 se ne difende da solo con la IDF,
    e toglierle richiederebbe una lista di stopword per ogni lingua trattata.
    """
    assert tokenize("C++, CI/CD e Node.js") == ["c++", "ci/cd", "e", "node.js"]
    assert tokenize("C# e F#") == ["c#", "e", "f#"]


def test_ngrams_include_phrases() -> None:
    contatore = ngrams(["spring", "boot", "java"], max_n=2)
    assert contatore["spring boot"] == 1
    assert contatore["spring"] == 1


def test_a_phrase_term_does_not_match_its_scattered_words() -> None:
    """ "Spring Boot" non deve prendere punti da un annuncio che dice "boot" altrove."""
    indice = Bm25.build(
        [
            "Sviluppo con Spring Boot e Java",
            "Bootstrap del progetto e spring cleaning del codice",
        ]
    )
    punteggi = indice.score(["spring boot"])
    assert punteggi[0] > 0
    assert punteggi[1] == 0


def test_idf_never_goes_negative() -> None:
    """La formula classica di Robertson diventa negativa sopra il 50% dei documenti.

    In un corpus di annunci per sviluppatori "developer" ci sta dentro, e un
    contributo negativo abbasserebbe il punteggio di un annuncio *perché*
    contiene la parola giusta.
    """
    indice = Bm25.build(["developer developer", "developer", "developer di cose"])
    assert all(p > 0 for p in indice.score(["developer"]))


def test_rare_terms_score_higher_than_common_ones() -> None:
    corpus = ["java spring", "java hibernate", "java jsf", "java kotlin android"]
    indice = Bm25.build(corpus)
    comune = indice.score(["java"])
    raro = indice.score(["kotlin"])
    assert raro[3] > comune[3]


def test_weights_scale_the_contribution() -> None:
    indice = Bm25.build(["java kotlin", "kotlin"])
    pieno = indice.score(["java"], [1.0])
    dimezzato = indice.score(["java"], [0.5])
    assert pieno[0] == pytest.approx(dimezzato[0] * 2)


def test_mismatched_weights_are_an_error_not_a_silent_truncation() -> None:
    indice = Bm25.build(["java"])
    with pytest.raises(ValueError, match="lunghezze diverse"):
        indice.score(["java", "kotlin"], [1.0])


def test_empty_corpus_and_empty_query_are_harmless() -> None:
    assert Bm25.build([]).score(["java"]).size == 0
    assert list(Bm25.build(["java"]).score([])) == [0.0]


def test_missing_term_contributes_nothing() -> None:
    indice = Bm25.build(["java", "kotlin"])
    assert list(indice.score(["cobol"])) == [0.0, 0.0]


# --- Stadio 1 -----------------------------------------------------------------


def test_embedding_text_leads_with_the_title() -> None:
    """Il modello legge 512 token e poi smette: l'ordine è una scelta, non estetica."""
    testo = rank_mod.job_embedding_text(make_job())
    assert testo.startswith("Backend Developer")
    assert "Acme" in testo.split("\n")[0]


def test_embedding_text_is_capped() -> None:
    lungo = make_job(description_clean="x" * 50_000)
    assert len(rank_mod.job_embedding_text(lungo)) < 5_000


def test_bm25_text_repeats_the_title() -> None:
    testo = rank_mod.bm25_text(make_job())
    assert testo.count("Backend Developer") == rank_mod.TITLE_BOOST + 1  # titolo + job_family


def test_profile_terms_keep_the_highest_weight_per_term() -> None:
    """Una tecnologia usata al lavoro e anche in un progetto vale il peso maggiore."""
    profilo = make_profile(
        skills=Skills(hard=["Java"]),
        projects=[Project(id="p", name="P", description="Un progetto", tech=["Java", "Qt"])],
    )
    termini, pesi = rank_mod.profile_terms(profilo)
    pesato = dict(zip(termini, pesi, strict=True))
    assert pesato["java"] == rank_mod._SKILL_WEIGHT
    assert pesato["qt"] == rank_mod._SKILL_WEIGHT / 2


def test_rank_orders_by_the_hybrid_score() -> None:
    from jobboard.ai.embeddings import to_bytes

    profilo = make_profile()
    vettore = np.array([1.0, 0.0], dtype=np.float32)

    vicino = make_job(
        id=1,
        title="Java Backend Developer",
        description_clean="Java, Spring Boot, Oracle",
        embedding=to_bytes(np.array([1.0, 0.0], dtype=np.float32)),
        embedding_model="m",
    )
    lontano = make_job(
        id=2,
        title="Chef de rang",
        description_clean="Servizio in sala, vini",
        embedding=to_bytes(np.array([0.0, 1.0], dtype=np.float32)),
        embedding_model="m",
    )

    classifica = rank_mod.rank([lontano, vicino], profilo, vettore)
    assert [r.job.id for r in classifica] == [1, 2]
    assert classifica[0].hybrid > classifica[1].hybrid


def test_rank_skips_jobs_without_an_embedding_instead_of_scoring_them_zero() -> None:
    """Uno zero li manderebbe in fondo come se fossero stati valutati e bocciati."""
    from jobboard.ai.embeddings import to_bytes

    con = make_job(id=1, embedding=to_bytes(np.array([1.0, 0.0], dtype=np.float32)))
    senza = make_job(id=2, embedding=None)
    classifica = rank_mod.rank([con, senza], make_profile(), np.array([1.0, 0.0], dtype=np.float32))
    assert [r.job.id for r in classifica] == [1]


# --- riserva per le fonti a budget (Stadio 1 -> 2) ----------------------------


def _ranked(*ids: int) -> list[Ranked]:
    """Una classifica gia' ordinata: id crescente, punteggio ibrido decrescente."""
    return [Ranked(job=make_job(id=i), semantic=0.0, keyword=0.0, hybrid=float(-i)) for i in ids]


def test_select_finalists_without_reserve_behaves_like_a_plain_slice() -> None:
    assert [r.job.id for r in select_finalists(_ranked(0, 1, 2, 3, 4), 3, 0, set())] == [0, 1, 2]


def test_select_finalists_with_no_budgeted_ids_behaves_like_a_plain_slice() -> None:
    """Una riserva impostata ma senza candidati a budget non cambia nulla."""
    assert [r.job.id for r in select_finalists(_ranked(0, 1, 2, 3, 4), 3, 2, set())] == [0, 1, 2]


def test_select_finalists_reserves_a_floor_for_budgeted_sources() -> None:
    """Un annuncio a budget fuori dal merito puro entra comunque, grazie alla riserva."""
    # id 4 e' l'ultimo per punteggio ibrido, l'unico a comparire fra le fonti a budget.
    scelti = select_finalists(_ranked(0, 1, 2, 3, 4), quanti=3, reserved_n=1, budget_ids={4})
    assert [r.job.id for r in scelti] == [0, 1, 4]


def test_select_finalists_does_not_duplicate_a_budgeted_job_already_on_merit() -> None:
    """Chi vince gia' un posto per merito non consuma la riserva, e non si duplica."""
    # id 0 e 1 sono a budget e gia' dentro il merito puro (i primi tre su cinque):
    # alla riserva non resta nessun candidato a budget da aggiungere.
    scelti = select_finalists(_ranked(0, 1, 2, 3, 4), quanti=5, reserved_n=2, budget_ids={0, 1})
    assert [r.job.id for r in scelti] == [0, 1, 2]


def test_select_finalists_does_not_pad_when_fewer_budgeted_jobs_exist_than_the_floor() -> None:
    """La riserva prende quel che c'e', non inventa posti per arrivare al numero."""
    scelti = select_finalists(_ranked(0, 1, 2, 3, 4), quanti=5, reserved_n=3, budget_ids={4})
    assert [r.job.id for r in scelti] == [0, 1, 4]


def test_select_finalists_never_exceeds_the_total_cap() -> None:
    """Il costo di una run resta prevedibile: mai piu' di ``quanti`` finalisti."""
    scelti = select_finalists(
        _ranked(*range(20)), quanti=10, reserved_n=4, budget_ids=set(range(20))
    )
    assert len(scelti) == 10


# --- rubrica (Stadio 2) -------------------------------------------------------


def test_rubric_weights_sum_to_one() -> None:
    assert sum(RUBRIC_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_rubric_weight_has_a_field_and_viceversa() -> None:
    """I nomi dei pesi sono anche i nomi dei campi e le chiavi di ``match.subscores``."""
    campi = set(JobAssessment.model_fields)
    assert set(RUBRIC_WEIGHTS) <= campi


def test_requirements_are_generated_before_the_scores() -> None:
    """L'ordine dei campi è parte del prompt: il modello estrae, poi giudica.

    Spostare un punteggio prima dei requisiti gli farebbe dare un voto senza aver
    ancora scritto cosa sta valutando, e non è il genere di regressione che si
    nota guardando i numeri.
    """
    ordine = list(JobAssessment.model_fields)
    ultimo_requisito = max(ordine.index(n) for n in ("must_have", "nice_to_have", "red_flags"))
    primo_punteggio = min(ordine.index(n) for n in RUBRIC_WEIGHTS)
    assert ultimo_requisito < primo_punteggio


def _assessment(**overrides: Any) -> JobAssessment:
    dati: dict[str, Any] = {n: 50 for n in RUBRIC_WEIGHTS}
    dati["rationale"] = "Motivazione."
    dati["must_have"] = ["Java"]
    dati["nice_to_have"] = ["Kotlin"]
    dati.update(overrides)
    return JobAssessment.model_validate(dati)


def test_weighted_total_is_computed_by_us_not_by_the_model() -> None:
    assert weighted_total({n: 100 for n in RUBRIC_WEIGHTS}) == 100
    assert weighted_total({n: 0 for n in RUBRIC_WEIGHTS}) == 0
    assert weighted_total({n: 50 for n in RUBRIC_WEIGHTS}) == 50


def test_weighted_total_respects_the_weights() -> None:
    punteggi = {n: 0 for n in RUBRIC_WEIGHTS}
    punteggi["must_have_coverage"] = 100
    assert weighted_total(punteggi) == 40


def test_a_criterion_missing_from_old_data_counts_as_neutral() -> None:
    """Ricalcolando un punteggio salvato da una rubrica precedente, zero riscriverebbe
    la storia al ribasso."""
    assert weighted_total({"must_have_coverage": 100}) == round(100 * 0.40 + NEUTRAL * 0.60)


def test_out_of_range_scores_are_clamped_not_rejected() -> None:
    valutazione = _assessment(must_have_coverage=105, domain_fit=-3)
    assert valutazione.must_have_coverage == 100
    assert valutazione.domain_fit == 0


def test_an_extra_field_from_the_model_does_not_break_the_run() -> None:
    valutazione = JobAssessment.model_validate(
        {**{n: 50 for n in RUBRIC_WEIGHTS}, "rationale": "ok", "confidence": 0.9}
    )
    assert valutazione.rationale == "ok"


def test_a_missing_score_is_still_an_error() -> None:
    with pytest.raises(ValidationError):
        JobAssessment.model_validate({"rationale": "ok"})


class _FakeProvider:
    """Restituisce una valutazione fissa e registra il prompt ricevuto."""

    def __init__(self, valutazione: JobAssessment) -> None:
        self.valutazione = valutazione
        self.prompts: list[str] = []

    def generate_structured(self, prompt: str, schema: Any, **kwargs: Any) -> LLMResult[Any]:
        self.prompts.append(prompt)
        return LLMResult(self.valutazione, LLMUsage("fake", 10, 5))


def test_an_ad_with_no_requirements_cannot_score_full_coverage() -> None:
    """Il bug trovato alla prima run vera, in forma di test.

    Un annuncio da contabile a Pune con quattro righe di descrizione e nessun
    requisito: il modello ha estratto ``must_have = []`` e ne ha dedotto, con
    logica vacua impeccabile, una copertura del 100%. Quel criterio pesa il 40%,
    e quaranta punti nati dal nulla lo hanno portato primo in classifica.
    """
    valutazione = _assessment(
        must_have=[], must_have_coverage=100, nice_to_have=[], nice_to_have_coverage=80
    )
    corretti = neutralize_unknowable(valutazione, make_job(salary_is_stated=True))
    assert valutazione.must_have_coverage == NEUTRAL
    assert valutazione.nice_to_have_coverage == NEUTRAL
    assert set(corretti) == {"must_have_coverage", "nice_to_have_coverage"}


def test_a_stated_requirement_leaves_its_score_alone() -> None:
    valutazione = _assessment(
        must_have=["Java"], must_have_coverage=90, nice_to_have=["Kotlin"], nice_to_have_coverage=80
    )
    neutralize_unknowable(valutazione, make_job(salary_is_stated=True))
    assert valutazione.must_have_coverage == 90
    assert valutazione.nice_to_have_coverage == 80


def test_salary_fit_is_forced_neutral_when_the_ad_states_nothing() -> None:
    """Regola deterministica: non la si delega a chi risponde in modo probabilistico."""
    provider = _FakeProvider(_assessment(salary_fit=90))
    risultato = assess(provider, make_profile(), make_job(salary_is_stated=False))  # type: ignore[arg-type]
    assert risultato.value.salary_fit == NEUTRAL


def test_salary_fit_is_left_alone_when_the_ad_states_a_salary() -> None:
    provider = _FakeProvider(_assessment(salary_fit=90))
    job = make_job(salary_is_stated=True, salary_min=45_000, salary_currency="EUR")
    risultato = assess(provider, make_profile(), job)  # type: ignore[arg-type]
    assert risultato.value.salary_fit == 90


def test_the_prompt_carries_both_sides_of_the_comparison() -> None:
    prompt = build_prompt(make_profile(), make_job())
    assert "Backend Developer" in prompt  # ruolo del candidato e titolo dell'annuncio
    assert "Spring Boot" in prompt  # competenze dichiarate
    assert "Milano" in prompt
    assert "non dichiarata" in prompt  # la RAL assente viene detta, non taciuta


def test_requirement_fields_turn_languages_into_a_mapping() -> None:
    valutazione = _assessment(
        languages_required=[{"code": "DE", "level": "B2"}, {"code": "en", "level": "C1"}]
    )
    campi = valutazione.requirement_fields()
    assert campi["languages_required"] == {"de": "B2", "en": "C1"}


def test_no_control_characters_in_the_source() -> None:
    """Guardia contro il bug che ha già ucciso trenta regex in questo progetto.

    Uno script di manutenzione ha scritto ``\\b`` dentro una stringa Python non
    raw: è diventato un **backspace** (0x08) invece del confine di parola. I
    pattern sono rimasti sintatticamente validi e semanticamente morti, senza un
    errore né un test rosso.
    """
    from pathlib import Path

    moduli = [
        Path(criteria_mod.__file__),
        Path(rank_mod.__file__),
        Path(rubric.__file__),
        Path(Bm25.__module__.replace(".", "/") + ".py"),
    ]
    for modulo in moduli:
        if not modulo.exists():  # il percorso ricostruito dal nome del modulo
            continue
        testo = modulo.read_text(encoding="utf-8")
        sospetti = {c for c in testo if ord(c) < 32 and c not in "\n\t"}
        assert not sospetti, f"{modulo.name} contiene caratteri di controllo: {sospetti!r}"


# --- persistenza --------------------------------------------------------------


class _FakeSession:
    """Solo quello che ``_row`` usa: raccogliere gli oggetti aggiunti."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def test_a_new_match_row_is_usable_before_the_flush() -> None:
    """I ``default=`` delle colonne li applica Postgres alla INSERT, non il costruttore.

    Senza valorizzarli a mano, ``reached_stage`` vale ``None`` fino al flush e
    ``max(None, 1)`` solleva un ``TypeError`` **dopo** che la run ha gia' speso
    quaranta chiamate LLM. E' successo davvero, alla prima esecuzione con --commit.
    """
    sessione = _FakeSession()
    riga = _row(sessione, {}, 7)  # type: ignore[arg-type]
    assert riga.reached_stage == 0
    assert riga.gaps == []

    _write_stage1(
        sessione,  # type: ignore[arg-type]
        {},
        Ranked(job=make_job(), semantic=0.9, keyword=1.0, hybrid=0.8),
    )
    nuova = sessione.added[-1]
    assert nuova.reached_stage == 1
    assert nuova.hybrid_score == 0.8
