"""Test della coda e del gestore ``run_pipeline``.

Come il resto della suite: nessun database e nessuna rete. Quello che si prova
qui e' la parte che decide *come* un lavoro viene ritentato e *cosa* la
dashboard vede mentre gira — cioe' esattamente le due cose che, sbagliate, non
si notano finche' non costano una run notturna o una barra ferma a meta'.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from jobboard.models import Source
from jobboard.models.base import utcnow
from jobboard.models.enums import RunStatus, TaskType
from jobboard.pipeline.criteria import MatchCriteria
from jobboard.pipeline.ingest import IngestReport, SourceOutcome, collect
from jobboard.pipeline.match import MatchReport
from jobboard.pipeline.progress import avanza, fascia
from jobboard.queue import HANDLERS, TaskError
from jobboard.sources.base import RawJob, SearchQuery

# --- ritentativi --------------------------------------------------------------


def test_un_errore_normale_e_ritentabile() -> None:
    """Il caso comune: una API che singhiozza deve poter riprovare."""
    assert TaskError("503 dal fornitore").definitivo is False


def test_un_errore_definitivo_dichiara_di_non_voler_riprovare() -> None:
    """La proprieta' che spegne il ritentativo, e che ``_fallisci`` legge.

    Non e' un dettaglio di stile: ``run_pipeline`` rifa' l'intera raccolta a
    ogni presa, e il budget JSearch e' di circa duecento chiamate al mese. Tre
    tentativi su un profilo non confermato — che non cambia da solo fra una
    presa e l'altra — ne brucerebbero il triplo senza cambiare esito.
    """
    errore = TaskError("il profilo non e' stato confermato", definitivo=True)
    assert errore.definitivo is True


def test_i_gestori_registrati_coprono_i_tipi_che_la_dashboard_sa_accodare() -> None:
    """Un tipo senza gestore fallisce con "fase non ancora sviluppata".

    E' il messaggio giusto per ``apply``, che arrivera' in Fase 7. Sarebbe il
    messaggio sbagliato per il bottone "Aggiorna adesso", che la dashboard
    mostra gia': questo test lega le due cose.
    """
    import jobboard.handlers  # noqa: F401  (importarlo e' quello che li registra)

    assert TaskType.RUN_PIPELINE in HANDLERS
    assert TaskType.REPARSE_PROFILE in HANDLERS


# --- task orfani ---------------------------------------------------------------
#
# Solo la decisione pura: _task_orfani() interroga il database e non ha un
# fixture qui (vedi la nota in cima al file). Quello che si puo' e si deve
# provare senza database e' la soglia stessa: che non scatti su un task appena
# preso, e che scatti su uno rimasto 'running' troppo a lungo.


def test_un_task_appena_preso_non_e_orfano() -> None:
    from jobboard.queue import _task_e_orfano

    adesso = utcnow()
    assert not _task_e_orfano(adesso, adesso=adesso)


def test_un_task_running_da_oltre_un_ora_e_orfano() -> None:
    """E' esattamente il task 14 del 1 settembre 2026: claimed_at vecchio,
    nessun processo vivo dietro, nessun errore scritto da nessuno."""
    from jobboard.queue import _task_e_orfano

    adesso = utcnow()
    preso = adesso - dt.timedelta(minutes=61)
    assert _task_e_orfano(preso, adesso=adesso)


def test_una_rivalutazione_completa_non_supera_la_soglia_per_errore() -> None:
    """La soglia deve restare sopra i tempi di un run_pipeline con rescore, che
    puo' superare abbondantemente i cinque minuti tipici della sola rubrica:
    non deve interrompere un lavoro legittimo ancora in corso."""
    from jobboard.queue import _task_e_orfano

    adesso = utcnow()
    preso = adesso - dt.timedelta(minutes=30)
    assert not _task_e_orfano(preso, adesso=adesso)


# --- avanzamento --------------------------------------------------------------


def test_senza_ascoltatori_l_avanzamento_non_costa_niente() -> None:
    """La pipeline da riga di comando passa ``None`` e non deve inciampare."""
    avanza(None, 50, "a meta'")
    assert fascia(None, 0, 50) is None


def test_una_fascia_comprime_gli_estremi_senza_spostarli() -> None:
    visti: list[int] = []
    scalato = fascia(lambda p, _m: visti.append(p), 20, 60)
    assert scalato is not None

    for percentuale in (0, 50, 100):
        scalato(percentuale, "")

    assert visti == [20, 40, 60]


def test_la_percentuale_di_una_run_completa_non_torna_mai_indietro() -> None:
    """La regressione che ``fascia`` esiste per impedire.

    ``run_pipeline`` esegue due pipeline che contano ognuna da 0 a 100. Passate
    tali e quali alla barra, questa arriverebbe in fondo a meta' lavoro e
    ripartirebbe da zero: da fuori e' indistinguibile da un task ripreso da capo
    dopo un errore.
    """
    visti: list[int] = []
    sink = visti.append

    raccolta = fascia(lambda p, _m: sink(p), 2, 55)
    matching = fascia(lambda p, _m: sink(p), 57, 100)
    assert raccolta is not None and matching is not None

    # Le percentuali che le due pipeline emettono davvero, nel loro ordine.
    for percentuale in (0, 11, 22, 33, 44, 85, 90, 100):
        raccolta(percentuale, "")
    for percentuale in (5, 20, 35, 48, 62, 76, 90, 100):
        matching(percentuale, "")

    assert visti == sorted(visti)
    assert visti[0] >= 0 and visti[-1] == 100


# --- raccolta: chi sta rispondendo -------------------------------------------


class _ClientFinto:
    calls = 2

    def __enter__(self) -> _ClientFinto:
        return self

    def __exit__(self, *_esc: object) -> None:
        return None


class _AdapterFinto:
    """Il minimo che ``collect`` chiama su un adapter."""

    def __init__(self, _settings: Any, _config: Any, rate_limit_per_min: int = 30) -> None:
        pass

    def missing_settings(self) -> list[str]:
        return []

    def new_client(self) -> _ClientFinto:
        return _ClientFinto()

    def fetch(self, _query: SearchQuery, _http: _ClientFinto) -> list[RawJob]:
        return [
            RawJob(
                source="finta",
                external_id="1",
                title="Backend Developer",
                company="Acme Srl",
                url="https://example.com/1",
            )
        ]


def _fonte(slug: str) -> Source:
    return Source(adapter=slug, display_name=slug, enabled=True, config={})


def test_la_raccolta_annuncia_la_fonte_prima_di_interrogarla(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il messaggio deve dire su chi si e' fermi, non chi e' gia' finito.

    Una fonte che non risponde tiene il turno per tutto il timeout: se il nome
    comparisse *dopo* la chiamata, la dashboard mostrerebbe per venti secondi il
    nome della fonte precedente, cioe' l'unica che di sicuro non e' il problema.
    """
    monkeypatch.setattr("jobboard.pipeline.ingest.get_adapter_class", lambda _slug: _AdapterFinto)

    messaggi: list[str] = []
    collect(
        [_fonte("adzuna"), _fonte("jooble")],
        SearchQuery(keywords=("backend",)),
        progress=lambda _p, m: messaggi.append(m),
    )

    assert messaggi == ["adzuna (1/2)", "jooble (2/2)"]


# --- riepilogo di fine run ----------------------------------------------------


def _raccolta(**overrides: Any) -> IngestReport:
    report = IngestReport(batch_id="b", query=SearchQuery(keywords=("backend",)), dry_run=False)
    report.outcomes = [
        SourceOutcome(slug="adzuna", status=RunStatus.OK, fetched=40, api_calls=6),
        SourceOutcome(slug="jooble", status=RunStatus.FAILED, error="timeout"),
    ]
    report.persisted_new = 12
    report.persisted_updated = 28
    for chiave, valore in overrides.items():
        setattr(report, chiave, valore)
    return report


def test_il_riepilogo_nomina_le_fonti_cadute() -> None:
    """Dire "parziale" senza dire quale manda a confrontare due elenchi a occhio."""
    from jobboard.handlers import _riepilogo

    riepilogo = _riepilogo(
        _raccolta(),
        MatchReport(criteria=MatchCriteria()),
        soglia=65,
        notifica_annunci=0,
        notifica_errore=None,
        controllo_email=None,
        errore_email=None,
    )

    assert riepilogo["fonti_fallite"] == ["jooble"]
    assert riepilogo["annunci_nuovi"] == 12
    assert riepilogo["chiamate_api"] == 6
    assert riepilogo["soglia"] == 65
    assert riepilogo["notifica_annunci"] == 0
    assert riepilogo["notifica_errore"] is None


def test_una_raccolta_con_una_fonte_caduta_resta_parziale_non_fallita() -> None:
    """Otto fonti su nove sono una run utile, non una run fallita.

    E' la regola che tiene in piedi la run notturna: senza, basterebbe una API
    di terzi giu' per non avere annunci nuovi quella mattina.
    """
    assert _raccolta().status is RunStatus.PARTIAL
