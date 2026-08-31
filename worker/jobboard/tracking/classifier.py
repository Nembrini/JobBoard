"""Classificazione delle risposte dei recruiter (Fase 9.3).

Una mail che :func:`imap_reader.looks_related` ha già giudicato correlata a
una candidatura arriva qui per una domanda diversa: non più "riguarda questa
candidatura?" ma "che tipo di risposta è?". Le cinque classi sono quelle del
piano originale (:class:`~jobboard.models.enums.EmailClass`), non un elenco
scelto in questo modulo.

**La regola che sposta lo stato è nel codice, non nel modello.** Stesso
principio della media pesata della rubrica (``ai/rubric.py``): al modello si
chiede un giudizio — la classe — non una decisione sullo stato. Con la
mappatura in :data:`STATUS_BY_CLASS` e l'ordine di avanzamento in
:func:`next_status` fuori dal prompt, ritararla non richiede di rifare una
sola chiamata.

**Perché "Haiku" del piano è diventato Gemini.** Vedi il commento su
``model_classify`` in ``config.py``: il provider attivo è quello scelto per
tutta la pipeline, non uno diverso per questo stadio.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from ..ai.client import LLMProvider, LLMResult
from ..models.enums import TERMINAL_APPLICATION_STATUSES, ApplicationStatus, EmailClass

log = logging.getLogger(__name__)

#: Oltre questa lunghezza il corpo viene tagliato. Una risposta di recruiter
#: non è una job description: qualche paragrafo, mai dodicimila caratteri, e
#: il resto è quasi sempre firma e informativa privacy ripetuta.
_MAX_BODY_CHARS = 4_000

SYSTEM_PROMPT = """Sei un assistente che legge le risposte che i recruiter mandano
dopo una candidatura e le smista in una di cinque classi, sempre le stesse:

- interview: propone o fissa un colloquio, uno screening telefonico, un test tecnico.
- rejection: comunica che la candidatura non prosegue.
- ack: conferma solo la ricezione della candidatura, senza dire cosa succede dopo.
- request_info: chiede un'informazione o un documento in più prima di decidere
  (disponibilità, RAL attesa, un allegato mancante).
- other: qualunque altra cosa — newsletter, notifica automatica non legata a un
  esito, messaggio di un'altra persona nello stesso thread.

Classifica solo in base al contenuto, non al mittente: quello è già stato deciso
altrove. Se il testo è ambiguo fra due classi, scegli quella con conseguenze
minori per il candidato — "other" piuttosto che "rejection" su un testo che non
la dichiara esplicitamente, perché un rifiuto segnato per errore chiude un
follow-up che sarebbe stato ancora dovuto."""


class EmailClassification(BaseModel):
    """Output del modello: un solo giudizio, non un'estrazione libera.

    ``extra="ignore"``, come le risposte della rubrica: è output di un
    modello, un campo in più inventato non deve far fallire la lettura.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    classification: EmailClass
    summary: str = Field(
        description="Una frase sola, in italiano, di cosa dice la mail — per la timeline"
    )


def build_prompt(*, company: str, job_title: str, subject: str, body: str) -> str:
    corpo = (body or "").strip()[:_MAX_BODY_CHARS]
    return (
        f"Candidatura per: {job_title} presso {company}\n\n"
        f"Oggetto della mail: {subject}\n\n"
        f"Testo:\n{corpo or '(vuoto)'}"
    )


def classify(
    provider: LLMProvider,
    *,
    company: str,
    job_title: str,
    subject: str,
    body: str,
    model: str | None = None,
) -> LLMResult[EmailClassification]:
    """Una chiamata, un giudizio. Il chiamante decide cosa farne dello stato."""
    prompt = build_prompt(company=company, job_title=job_title, subject=subject, body=body)
    return provider.generate_structured(
        prompt, EmailClassification, system=SYSTEM_PROMPT, model=model
    )


#: La regola deterministica che decide se e come una classificazione sposta
#: ``application.status``. ``None`` significa "non decide da sola": la mail
#: genera comunque un evento in timeline, ma lo stato resta quello che era.
STATUS_BY_CLASS: dict[EmailClass, ApplicationStatus | None] = {
    EmailClass.INTERVIEW: ApplicationStatus.INTERVIEW,
    EmailClass.REJECTION: ApplicationStatus.REJECTED,
    EmailClass.ACK: ApplicationStatus.ACKNOWLEDGED,
    EmailClass.REQUEST_INFO: None,
    EmailClass.OTHER: None,
}

#: Ordine di avanzamento: una risposta non fa mai *retrocedere* lo stato.
#: Un "ack" arrivato dopo che il colloquio era già stato fissato (un
#: accodamento in ritardo del mittente, capita) non deve riportare la
#: candidatura indietro. Gli stati terminali non compaiono qui: li ferma
#: prima ``next_status``, non un confronto fra numeri.
_RANK: dict[ApplicationStatus, int] = {
    ApplicationStatus.SUBMITTED: 0,
    ApplicationStatus.ACKNOWLEDGED: 1,
    ApplicationStatus.INTERVIEW: 2,
    ApplicationStatus.REJECTED: 3,
    ApplicationStatus.OFFER: 3,
}


def next_status(current: ApplicationStatus, classification: EmailClass) -> ApplicationStatus:
    """Il nuovo stato dopo una classificazione, o quello attuale se non cambia nulla.

    Da uno stato terminale (``rejected``, ``offer``, ``withdrawn``, ``failed``)
    non si muove mai automaticamente: un esito già chiuso a mano o da una
    classificazione precedente non lo riapre una mail successiva, che sia un
    fuori tema o un errore del mittente. Riaprirlo, se serve davvero, resta
    un'azione a mano dalla pagina Candidature.
    """
    if current in TERMINAL_APPLICATION_STATUSES:
        return current

    nuovo = STATUS_BY_CLASS.get(classification)
    if nuovo is None:
        return current

    rango_attuale = _RANK.get(current, -1)
    rango_nuovo = _RANK.get(nuovo, -1)
    return nuovo if rango_nuovo >= rango_attuale else current


def is_new_message(message_id: str, known_message_ids: frozenset[str]) -> bool:
    """Se il ``Message-ID`` non è già stato classificato per questa candidatura.

    Senza un ``Message-ID`` (capita, anche se raro) si considera comunque
    nuovo: scartarlo perché non identificabile perderebbe una risposta vera,
    e riclassificare due volte la stessa mail senza ID costerebbe una chiamata
    in più, non un errore.
    """
    return not message_id or message_id not in known_message_ids
