"""I criteri dello Stadio 0: cosa non ha senso valutare.

Lo Stadio 0 non giudica la qualità di un annuncio, decide se sia proponibile.
Sono cose che si sanno prima di leggere il testo: se il lavoro è in un paese
dove servirebbe un visto, se chiede otto anni di esperienza, se è in una lingua
che non parli. Escluderle qui costa una condizione booleana; farle arrivare allo
Stadio 2 costa una chiamata LLM a testa.

**Regola trasversale: un dato mancante non esclude mai.** Un terzo degli annunci
raccolti non dichiara il paese e due quinti non dichiarano il livello. Trattare
quel silenzio come una risposta negativa trasformerebbe un buco nei dati della
fonte in un'offerta persa — e la fonte non la ripubblica il giorno dopo. Il
filtro esclude solo quando l'annuncio *afferma* qualcosa di incompatibile.

I criteri vivono nella tabella ``settings``, non in ``.env``: la dashboard deve
poterli cambiare, e cambiarli non deve richiedere di riavviare il worker.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting
from ..models.enums import ContractType, Seniority, WorkMode
from ..schemas import CandidateAnswers, MasterProfile

log = logging.getLogger(__name__)

#: Chiave della riga ``settings`` con i criteri di matching.
MATCHING_SETTING_KEY = "matching"

#: Mercati di default: Italia, i paesi europei in cui un cittadino UE può
#: lavorare senza pratiche, e i due grandi hub remoti europei.
DEFAULT_COUNTRIES = ("IT", "DE", "NL", "ES", "FR", "PT", "IE", "AT", "BE", "PL", "CH", "GB")

#: Mesi di esperienza professionale che separano un livello dal successivo.
#: Sono le soglie con cui il mercato europeo scrive gli annunci, non una
#: convenzione interna: un annuncio "senior" chiede da cinque anni in su.
_SENIORITY_MONTHS: tuple[tuple[int, Seniority], ...] = (
    (0, Seniority.INTERN),
    (1, Seniority.JUNIOR),
    (30, Seniority.MID),
    (66, Seniority.SENIOR),
    (102, Seniority.LEAD),
)


@dataclass(frozen=True)
class MatchCriteria:
    """Cosa rende un annuncio proponibile, prima ancora di leggerlo."""

    #: Paesi ammessi, ISO alpha-2 maiuscolo. Vuoto significa "ovunque".
    countries: frozenset[str] = frozenset()
    #: Un annuncio remoto vale anche fuori dai mercati scelti. Predefinito ``True``:
    #: è il motivo per cui si guarda il remoto.
    remote_ignores_country: bool = True

    #: Il tuo livello, dedotto dagli anni di esperienza e sovrascrivibile.
    seniority: Seniority = Seniority.UNKNOWN
    #: Quanti livelli sopra e sotto restano proponibili.
    seniority_tolerance: int = 1

    #: Lingue che parli, ISO 639-1. Un annuncio scritto in una lingua fuori da
    #: questo insieme viene escluso — non per snobismo, ma perché scriverne il CV
    #: in una lingua che non parli è la premessa di un colloquio imbarazzante.
    languages: frozenset[str] = frozenset()

    #: Paesi in cui puoi lavorare senza che l'azienda debba sponsorizzarti.
    #: Deriva da ``candidate_profile.work_authorization``.
    authorized_countries: frozenset[str] = frozenset()

    excluded_contract_types: frozenset[ContractType] = frozenset()
    excluded_work_modes: frozenset[WorkMode] = frozenset()
    #: Nomi azienda **normalizzati** (``pipeline.text.normalize_company``).
    blocked_companies: frozenset[str] = frozenset()

    #: Annunci più vecchi di così sono quasi sempre già chiusi.
    max_age_days: int = 45
    #: Escluso solo quando l'annuncio dichiara una RAL inferiore. Il silenzio non
    #: esclude: la maggioranza degli annunci non la dichiara affatto.
    min_salary_eur_year: int | None = None

    #: Quanti superstiti dello Stadio 1 passano alla rubrica LLM. E' un tetto unico e
    #: condiviso da tutte le fonti insieme, applicato all'intero arretrato non ancora
    #: valutato — non "quaranta al giorno fra gli annunci di oggi". Una fonte a budget
    #: come JSearch, che porta pochi annunci nuovi ma li aggiunge a un arretrato che le
    #: fonti senza tetto riempiono molto più in fretta, perde quasi sempre questa
    #: competizione: da qui ``stage2_reserved_floor``.
    stage2_top_n: int = 100

    #: Quanti dei posti di cui sopra sono riservati agli annunci arrivati (anche) da una
    #: fonte con un ``daily_call_budget`` — oggi solo JSearch/LinkedIn — anche quando il
    #: loro punteggio ibrido da solo non basterebbe a competere con l'arretrato delle
    #: fonti senza tetto. Tolto dal totale, non aggiunto sopra: il costo di una run resta
    #: prevedibile. Vedi ``pipeline.match.select_finalists``.
    stage2_reserved_floor: int = 10

    #: Cosa non è stato possibile verificare, per dirlo a voce alta invece di
    #: lasciar credere che il filtro abbia lavorato.
    inactive: tuple[str, ...] = field(default_factory=tuple)

    def accepts_seniority(self, level: Seniority) -> bool:
        """``True`` se il livello dell'annuncio è a portata.

        ``UNKNOWN`` da entrambi i lati passa sempre: da parte dell'annuncio
        perché il silenzio non è un rifiuto, da parte tua perché senza il tuo
        livello non c'è niente rispetto a cui misurare.
        """
        if self.seniority is Seniority.UNKNOWN or level is Seniority.UNKNOWN:
            return True
        return abs(level.rank - self.seniority.rank) <= self.seniority_tolerance

    def to_json(self) -> dict[str, Any]:
        """Forma serializzabile per la colonna JSONB. ``inactive`` è derivato, non si salva."""
        return {
            "countries": sorted(self.countries),
            "remote_ignores_country": self.remote_ignores_country,
            "seniority": self.seniority.value,
            "seniority_tolerance": self.seniority_tolerance,
            "languages": sorted(self.languages),
            "authorized_countries": sorted(self.authorized_countries),
            "excluded_contract_types": sorted(c.value for c in self.excluded_contract_types),
            "excluded_work_modes": sorted(m.value for m in self.excluded_work_modes),
            "blocked_companies": sorted(self.blocked_companies),
            "max_age_days": self.max_age_days,
            "min_salary_eur_year": self.min_salary_eur_year,
            "stage2_top_n": self.stage2_top_n,
            "stage2_reserved_floor": self.stage2_reserved_floor,
        }


def load_criteria(session: Session, *, profile: MasterProfile | None = None) -> MatchCriteria:
    """Legge i criteri dal database, creandoli al primo giro dal profilo.

    L'ordine è: quello che c'è in ``settings`` vince, perché è ciò che Filippo ha
    scelto dalla dashboard; il profilo serve solo a scrivere la prima riga e a
    riempire i campi che quella riga non ha.
    """
    from ..store import load_candidate, load_profile

    riga = session.get(Setting, MATCHING_SETTING_KEY)
    salvati: dict[str, Any] = dict(riga.value) if riga else {}

    if profile is None:
        stored = load_profile(session)
        profile = stored.profile if stored else None
    candidate = load_candidate(session)
    answers = candidate.answers if candidate else None

    criteri = _build(salvati, profile, answers)

    if riga is None:
        session.add(
            Setting(
                key=MATCHING_SETTING_KEY,
                value=criteri.to_json(),
                description="Filtri dello Stadio 0 e soglie del matching, modificabili dalla UI",
            )
        )
        session.flush()
        log.info("criteri di matching inizializzati dal profilo: %s", criteri.to_json())

    return criteri


def _build(
    salvati: dict[str, Any],
    profile: MasterProfile | None,
    answers: CandidateAnswers | None,
) -> MatchCriteria:
    lingue = _languages(salvati, profile, answers)
    autorizzati = _authorized(salvati, answers)
    livello = _seniority(salvati, profile)

    inattivi: list[str] = []
    if not lingue:
        inattivi.append(
            "lingue: nessuna dichiarata, il filtro sulla lingua dell'annuncio è spento "
            "(compila languages in candidate_profile.json)"
        )
    if not autorizzati:
        inattivi.append(
            "work authorization: nessun paese dichiarato, il filtro sulla sponsorship è spento "
            "(compila work_authorization in candidate_profile.json)"
        )
    if livello is Seniority.UNKNOWN:
        inattivi.append("seniority: non deducibile dal profilo, il filtro sul livello è spento")

    return MatchCriteria(
        countries=frozenset(_codes(salvati.get("countries"), DEFAULT_COUNTRIES)),
        remote_ignores_country=bool(salvati.get("remote_ignores_country", True)),
        seniority=livello,
        seniority_tolerance=_int(salvati.get("seniority_tolerance"), 1),
        languages=lingue,
        authorized_countries=autorizzati,
        excluded_contract_types=frozenset(
            _enums(salvati.get("excluded_contract_types"), ContractType)
        ),
        excluded_work_modes=frozenset(_enums(salvati.get("excluded_work_modes"), WorkMode)),
        blocked_companies=frozenset(
            str(c).strip().lower() for c in _list(salvati.get("blocked_companies"))
        ),
        max_age_days=_int(salvati.get("max_age_days"), 45),
        min_salary_eur_year=_optional_int(salvati.get("min_salary_eur_year")),
        stage2_top_n=_int(salvati.get("stage2_top_n"), 100),
        stage2_reserved_floor=_int(salvati.get("stage2_reserved_floor"), 10),
        inactive=tuple(inattivi),
    )


def _languages(
    salvati: dict[str, Any],
    profile: MasterProfile | None,
    answers: CandidateAnswers | None,
) -> frozenset[str]:
    if salvate := _list(salvati.get("languages")):
        return frozenset(str(c).lower() for c in salvate)
    if answers and answers.languages:
        return frozenset(answers.languages)
    if profile and profile.languages:
        return frozenset(lang.code.lower() for lang in profile.languages)
    return frozenset()


def _authorized(salvati: dict[str, Any], answers: CandidateAnswers | None) -> frozenset[str]:
    """Paesi dove puoi lavorare senza sponsorship.

    ``requires_sponsorship`` e ``none`` non contano come autorizzazione: sono
    esattamente i casi in cui la candidatura verrebbe scartata dal recruiter alla
    prima domanda del form.
    """
    if salvate := _list(salvati.get("authorized_countries")):
        return frozenset(str(c).upper() for c in salvate)
    if not answers:
        return frozenset()
    ammessi = {"citizen", "permanent_resident", "eu_eligible", "visa_holder"}
    return frozenset(
        code.upper() for code, stato in answers.work_authorization.items() if stato in ammessi
    )


def _seniority(salvati: dict[str, Any], profile: MasterProfile | None) -> Seniority:
    salvata = salvati.get("seniority")
    if isinstance(salvata, str):
        try:
            return Seniority(salvata)
        except ValueError:
            log.warning("seniority salvata non valida: %r, la rideduco dal profilo", salvata)
    return derive_seniority(profile) if profile else Seniority.UNKNOWN


def derive_seniority(profile: MasterProfile) -> Seniority:
    """Il tuo livello, dedotto dai mesi di esperienza professionale.

    È una stima, e il campo resta sovrascrivibile da ``settings``: il mercato non
    ragiona solo in mesi. Ma dedurla è meglio che chiedere un numero in più a
    mano, e lasciarla vuota spegnerebbe il filtro che scarta gli annunci
    irraggiungibili — che qui sono più della metà del raccolto.
    """
    mesi = experience_months(profile)
    livello = Seniority.INTERN
    for soglia, candidato in _SENIORITY_MONTHS:
        if mesi >= soglia:
            livello = candidato
    return livello


def experience_months(profile: MasterProfile, *, today: dt.date | None = None) -> int:
    """Mesi di esperienza, **senza contare due volte i periodi sovrapposti**.

    Sommare le durate una per una gonfierebbe il totale di chi ha tenuto due
    lavori insieme, o di chi ha iniziato il nuovo prima di chiudere il vecchio —
    che è normalissimo e capita anche in questo profilo.
    """
    oggi = today or dt.date.today()
    limite = oggi.year * 12 + oggi.month

    intervalli: list[tuple[int, int]] = []
    for esperienza in profile.experiences:
        inizio = _month_ordinal(esperienza.start)
        fine = _month_ordinal(esperienza.end) if esperienza.end else limite
        if inizio is None or fine is None or fine < inizio:
            continue
        intervalli.append((inizio, min(fine, limite)))

    if not intervalli:
        return 0

    totale = 0
    corrente_inizio, corrente_fine = min(intervalli)
    for inizio, fine in sorted(intervalli)[1:]:
        if inizio <= corrente_fine + 1:  # contigui o sovrapposti: si fondono
            corrente_fine = max(corrente_fine, fine)
        else:
            totale += corrente_fine - corrente_inizio + 1
            corrente_inizio, corrente_fine = inizio, fine
    return totale + corrente_fine - corrente_inizio + 1


def _month_ordinal(year_month: str | None) -> int | None:
    """``"2024-10"`` -> numero progressivo di mesi. Formato garantito dallo schema."""
    if not year_month:
        return None
    try:
        anno, mese = year_month.split("-")
        return int(anno) * 12 + int(mese)
    except (ValueError, AttributeError):  # pragma: no cover - lo schema lo impedisce
        return None


# --- lettura difensiva del JSONB ---------------------------------------------
# I valori arrivano da una colonna JSONB che la dashboard può scrivere: qui non
# si può dare per scontato nemmeno il tipo.


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _codes(value: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    codici = tuple(str(v).upper() for v in _list(value) if str(v).strip())
    return codici or fallback


def _int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    return fallback


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _enums[E: ContractType | WorkMode](value: object, enum_cls: type[E]) -> list[E]:
    out: list[E] = []
    for raw in _list(value):
        try:
            out.append(enum_cls(str(raw)))
        except ValueError:
            log.warning("valore ignorato per %s: %r", enum_cls.__name__, raw)
    return out
