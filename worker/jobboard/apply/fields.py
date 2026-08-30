"""Da ``CandidateAnswers`` + ``MasterProfile`` a un piano di campi da compilare.

Separato da come i campi vengono scritti nella pagina (``selectors.py``,
``heuristics.py``): qui si decide **cosa** dire, la' **dove** scriverlo. La
stessa separazione di ``ai/tailor.py`` e ``cv/render.py`` per il CV — dati e
presentazione non si mescolano — vale anche qui, ed e' quello che rende
testabile il piano senza un browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models import Job
from ..schemas import CandidateAnswers, MasterProfile

#: Le chiavi logiche che un piano puo' valorizzare. Un selettore o
#: un'euristica dichiarano quali di queste sanno scrivere: l'insieme e' fisso
#: apposta, cosi' aggiungerne una si vede in un posto solo.
TEXT_FIELDS: tuple[str, ...] = (
    "first_name",
    "last_name",
    "full_name",
    "email",
    "phone",
    "city",
    "country",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "years_of_experience",
    "notice_period_days",
    "available_from",
    "salary_expectation",
    "how_did_you_hear",
)

#: Campi si/no. Separati dal testo perche' sul form sono quasi sempre una
#: checkbox o due radio, non una casella da scrivere.
BOOLEAN_FIELDS: tuple[str, ...] = (
    "requires_sponsorship_now",
    "requires_sponsorship_future",
    "willing_to_relocate",
    "willing_to_travel",
)


@dataclass(frozen=True)
class FieldPlan:
    """Cosa scrivere in un form di candidatura, gia' formattato come stringa.

    ``values`` e ``booleans`` non si sovrappongono: ogni chiave di
    ``BOOLEAN_FIELDS`` sta solo nel secondo dizionario, anche quando la
    risposta e' ``None`` (non dichiarata) — in quel caso manca da entrambi, e
    un'euristica che non la trova la lascia in bianco invece di indovinare.
    """

    values: dict[str, str] = field(default_factory=dict)
    booleans: dict[str, bool] = field(default_factory=dict)
    resume_path: Path | None = None
    #: Cosa manca per compilare bene il form, non per bloccarlo: lo stesso
    #: elenco di ``CandidateAnswers.warnings()``, con in piu' quello che
    #: dipende dall'annuncio (nessun ``how_did_you_hear`` specifico, per
    #: esempio non serve perche' ha gia' un default).
    warnings: list[str] = field(default_factory=list)


def _split_name(full_name: str) -> tuple[str, str]:
    """Nome e cognome dalla stringa unica del profilo.

    Euristica, non estrazione: un "Maria Josè Del Bianco" diventa nome
    "Maria" e cognome "Josè Del Bianco". E' sbagliato per i nomi composti, ma
    e' lo stesso errore che farebbe chiunque compili il form guardando solo
    la stringa intera — e il campo resta comunque visibile per una
    correzione a mano prima del submit, che e' il punto di fermarsi li'.
    """
    pezzi = full_name.strip().split()
    if not pezzi:
        return "", ""
    if len(pezzi) == 1:
        return pezzi[0], ""
    return pezzi[0], " ".join(pezzi[1:])


def _salary_expectation(candidate: CandidateAnswers) -> str | None:
    minimo, massimo = candidate.salary_expectation_min, candidate.salary_expectation_max
    if minimo is None and massimo is None:
        return candidate.ats_answers.salary_note
    valuta = candidate.salary_currency
    if minimo is not None and massimo is not None and minimo != massimo:
        return f"{minimo}-{massimo} {valuta}"
    return f"{minimo if minimo is not None else massimo} {valuta}"


def build_plan(
    candidate: CandidateAnswers,
    profile: MasterProfile,
    job: Job,
    *,
    resume_path: Path | None = None,
) -> FieldPlan:
    """Costruisce il piano per un annuncio specifico.

    ``job`` conta per una cosa sola oggi: ``how_did_you_hear`` puo' citare la
    fonte vera invece del default "Company website" quando l'annuncio e'
    arrivato da un aggregatore che ha senso nominare. Il resto del piano non
    dipende dall'annuncio — e' la stessa ragione per cui ``CandidateAnswers``
    e' un profilo a parte e non rientra nel matching.
    """
    nome, cognome = _split_name(candidate.full_name)
    valori: dict[str, str] = {
        "first_name": nome,
        "last_name": cognome,
        "full_name": candidate.full_name,
        "email": candidate.email,
        "how_did_you_hear": candidate.ats_answers.how_did_you_hear,
    }
    if candidate.phone:
        valori["phone"] = candidate.phone
    if candidate.city:
        valori["city"] = candidate.city
    if candidate.country:
        valori["country"] = candidate.country
    if candidate.linkedin_url:
        valori["linkedin_url"] = candidate.linkedin_url
    if candidate.github_url:
        valori["github_url"] = candidate.github_url
    if candidate.portfolio_url:
        valori["portfolio_url"] = candidate.portfolio_url
    if candidate.ats_answers.years_of_experience is not None:
        valori["years_of_experience"] = str(candidate.ats_answers.years_of_experience)
    if candidate.notice_period_days is not None:
        valori["notice_period_days"] = str(candidate.notice_period_days)
    if candidate.ats_answers.available_from:
        valori["available_from"] = candidate.ats_answers.available_from
    stipendio = _salary_expectation(candidate)
    if stipendio:
        valori["salary_expectation"] = stipendio

    booleani: dict[str, bool] = {}
    if candidate.ats_answers.requires_sponsorship_now is not None:
        booleani["requires_sponsorship_now"] = candidate.ats_answers.requires_sponsorship_now
    if candidate.ats_answers.requires_sponsorship_future is not None:
        booleani["requires_sponsorship_future"] = candidate.ats_answers.requires_sponsorship_future
    booleani["willing_to_relocate"] = candidate.willing_to_relocate
    if candidate.ats_answers.willing_to_travel is not None:
        booleani["willing_to_travel"] = candidate.ats_answers.willing_to_travel

    # Domande fuori elenco gia' pronte come testo (``AtsAnswers.extra``): non
    # hanno una chiave logica fissa, quindi finiscono nel piano con il nome
    # letterale della domanda. L'euristica le trova cercando quel testo come
    # se fosse una label.
    valori.update(candidate.ats_answers.extra)

    avvisi = list(candidate.warnings())
    if not job.company.strip():  # pragma: no cover - la colonna e' NOT NULL, difensivo
        avvisi.append("l'annuncio non ha un nome azienda")

    return FieldPlan(values=valori, booleans=booleani, resume_path=resume_path, warnings=avvisi)
