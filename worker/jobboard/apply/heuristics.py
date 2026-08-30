"""Autofill euristico (Fase 7.3): trova il campo giusto guardando label e attributi.

E' il motore del Tier B — un ATS mai visto prima, senza selettori dedicati — ed
e' anche il ripiego del Tier A per tutto quello che i selettori dedicati non
coprono: le domande personalizzate che ogni azienda aggiunge al form
Greenhouse o Lever non hanno un selettore fisso, per definizione.

Separato da ``browser.py`` apposta: qui non c'e' Playwright, solo testo e
punteggi, cosi' si puo' provare senza aprire un browser. La scansione vera che
produce i :class:`DetectedField` sta in ``browser.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .fields import FieldPlan

FieldKind = Literal["text", "email", "tel", "textarea", "select", "checkbox", "radio", "file"]


@dataclass(frozen=True)
class DetectedField:
    """Un campo del form cosi' come lo vede la scansione della pagina.

    ``label`` raccoglie tutto il testo che potrebbe descrivere il campo —
    l'elemento ``<label>`` associato, ``aria-label``, ``placeholder`` — gia'
    unito in una stringa sola: alla ricerca di parole chiave non interessa
    *da dove* viene il testo, solo che ci sia.
    """

    kind: FieldKind
    label: str
    name: str = ""
    element_id: str = ""
    #: Indice progressivo nell'ordine del DOM: a parita' di punteggio vince il
    #: campo che compare prima, perche' e' quasi sempre quello vero — un form
    #: con due caselle "nome" mette la principale in cima e una demografica
    #: (EEO) piu' in basso.
    order: int = 0

    def haystack(self) -> str:
        return " ".join((self.label, self.name, self.element_id)).lower()


@dataclass(frozen=True)
class FillAction:
    """Un'istruzione concreta: scrivi ``value`` nel campo ``field``."""

    field: DetectedField
    logical_key: str
    value: str


#: Parole chiave per campo logico, italiano e inglese insieme: i form ATS che
#: un candidato italiano incontra sono quasi sempre in inglese, ma un'azienda
#: italiana su Workable a volte pubblica il form nella propria lingua.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "first_name": ("first name", "given name", "nome"),
    "last_name": ("last name", "surname", "family name", "cognome"),
    "full_name": ("full name", "your name", "nome e cognome", "nome completo"),
    "email": ("email", "e-mail", "posta elettronica"),
    "phone": ("phone", "mobile", "telefono", "cellulare"),
    "city": ("city", "location", "città", "località"),
    "country": ("country", "paese", "nazione"),
    "linkedin_url": ("linkedin",),
    "github_url": ("github",),
    "portfolio_url": ("portfolio", "website", "personal site", "sito web"),
    "years_of_experience": ("years of experience", "anni di esperienza"),
    "notice_period_days": ("notice period", "preavviso"),
    "available_from": ("available from", "start date", "disponibilità"),
    "salary_expectation": (
        "salary expectation",
        "compensation expectation",
        "expected salary",
        "ral attesa",
        "retribuzione attesa",
    ),
    "how_did_you_hear": ("how did you hear", "referral source", "come ci hai conosciuto"),
    "requires_sponsorship_now": ("require sponsorship", "need sponsorship", "sponsorship", "visto"),
    "requires_sponsorship_future": ("sponsorship in the future", "futura sponsorizzazione"),
    "willing_to_relocate": ("relocate", "relocation", "trasferirti", "trasferimento"),
    "willing_to_travel": ("willing to travel", "disponibilità a viaggiare"),
}

#: Il campo file del curriculum, riconosciuto per parola chiave e non
#: assegnato per posizione: un form ha quasi sempre anche un campo lettera di
#: presentazione, ed e' un secondo ``input[type=file]`` che non va confuso col
#: primo solo perche' e' il primo della pagina.
RESUME_KEYWORDS: tuple[str, ...] = ("resume", "cv", "curriculum")
COVER_LETTER_KEYWORDS: tuple[str, ...] = ("cover letter", "lettera di presentazione", "motivation")


def _score(field: DetectedField, keywords: tuple[str, ...]) -> int:
    """Quanto bene ``field`` corrisponde alle parole chiave. 0 = nessuna corrispondenza.

    Punteggio grezzo apposta: non serve una classifica fine, solo distinguere
    "corrisponde" da "non corrisponde" e rompere i pareggi con la parola piu'
    lunga trovata, che e' quasi sempre la piu' specifica ("last name" batte
    "name" quando entrambe compaiono nell'attributo).
    """
    pagliaio = field.haystack()
    migliore = 0
    for parola in keywords:
        if parola in pagliaio:
            migliore = max(migliore, len(parola))
    return migliore


def match_fields(detected: list[DetectedField], plan: FieldPlan) -> list[FillAction]:
    """Associa ogni campo del piano al campo del form che gli somiglia di piu'.

    Un campo del form usato per una chiave non e' piu' disponibile per le
    altre: senza, "name" finirebbe scritto sia su first_name sia su
    last_name se il form ha un solo campo "Full name" che corrisponde a
    entrambe le liste di parole chiave (capita: "nome" e' contenuto in
    "cognome e nome"). Vince la chiave con il punteggio piu' alto.
    """
    candidati: list[tuple[int, int, str, DetectedField]] = []
    for chiave, valore in plan.values.items():
        if not valore:
            continue
        parole = _KEYWORDS.get(chiave)
        if parole is None:  # domanda fuori elenco: la chiave e' gia' la label letterale
            parole = (chiave.lower(),)
        for campo in detected:
            if campo.kind in ("file",):
                continue
            punteggio = _score(campo, parole)
            if punteggio > 0:
                candidati.append((punteggio, -campo.order, chiave, campo))

    # Punteggio decrescente, poi ordine del DOM crescente (il ``-order``
    # sopra lo fa gia' salire in cima a parita' di punteggio).
    candidati.sort(key=lambda c: (c[0], c[1]), reverse=True)

    usati_campo: set[int] = set()
    usati_chiave: set[str] = set()
    azioni: list[FillAction] = []
    for _punteggio, _ordine, chiave, campo in candidati:
        if chiave in usati_chiave or id(campo) in usati_campo:
            continue
        usati_chiave.add(chiave)
        usati_campo.add(id(campo))
        valore = plan.values[chiave]
        azioni.append(FillAction(field=campo, logical_key=chiave, value=valore))

    for chiave, vero_falso in plan.booleans.items():
        parole = _KEYWORDS.get(chiave, (chiave.lower(),))
        migliore: DetectedField | None = None
        punteggio_migliore = 0
        for campo in detected:
            if campo.kind not in ("checkbox", "radio", "select"):
                continue
            if id(campo) in usati_campo:
                continue
            punteggio = _score(campo, parole)
            if punteggio > punteggio_migliore:
                punteggio_migliore = punteggio
                migliore = campo
        if migliore is not None:
            usati_campo.add(id(migliore))
            valore = "true" if vero_falso else "false"
            azioni.append(FillAction(field=migliore, logical_key=chiave, value=valore))

    return azioni


def find_resume_field(detected: list[DetectedField]) -> DetectedField | None:
    """Il campo file su cui caricare il curriculum, se il form ne ha uno."""
    return _find_file_field(detected, RESUME_KEYWORDS)


def find_cover_letter_field(detected: list[DetectedField]) -> DetectedField | None:
    return _find_file_field(detected, COVER_LETTER_KEYWORDS)


def _find_file_field(
    detected: list[DetectedField], keywords: tuple[str, ...]
) -> DetectedField | None:
    candidati = [c for c in detected if c.kind == "file"]
    if not candidati:
        return None
    con_punteggio = [(c, _score(c, keywords)) for c in candidati]
    con_punteggio.sort(key=lambda coppia: (coppia[1], -coppia[0].order), reverse=True)
    migliore, punteggio = con_punteggio[0]
    if punteggio > 0:
        return migliore
    # Nessuna label riconoscibile: se c'e' un solo campo file nel form e' quasi
    # certamente il curriculum, l'unico allegato che ogni form richiede.
    return candidati[0] if len(candidati) == 1 else None
