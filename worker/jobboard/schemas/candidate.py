"""Le risposte standard ai form di candidatura.

Separato dal :class:`~jobboard.schemas.profile.MasterProfile` perche' risponde a
una domanda diversa. Il MasterProfile dice **chi sei professionalmente** e serve a
calcolare i punteggi e a scrivere i CV; questo dice **cosa mettere nei campi del
form** — telefono, permesso di lavoro, preavviso — e non entra nel matching.

Cambiano anche con ritmi diversi: il primo a ogni aggiornamento del CV, il secondo
quasi mai. Tenerli insieme avrebbe significato rigenerare l'uno per correggere
l'altro.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .profile import CefrLevel, MasterProfile

#: Stato del diritto al lavoro in un paese. Alimenta un hard filter dello
#: Stadio 0: candidarsi dove servirebbe sponsorship e' quasi sempre tempo perso.
WorkAuthorization = Literal[
    "citizen",
    "permanent_resident",
    "eu_eligible",  # cittadino UE in un altro paese UE
    "visa_holder",
    "requires_sponsorship",
    "none",
]

#: Data completa, per la disponibilita' dichiarata nei form.
_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
#: Cifre, spazi e i separatori che i form accettano.
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{6,25}$")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AtsAnswers(_Base):
    """Le domande che ricorrono in quasi ogni form Greenhouse, Lever o Ashby."""

    years_of_experience: int | None = Field(default=None, ge=0, le=60)
    #: Greenhouse le chiede quasi sempre, e separate: il visto puo' servire ora e
    #: non fra tre anni, o viceversa.
    requires_sponsorship_now: bool | None = None
    requires_sponsorship_future: bool | None = None
    willing_to_travel: bool | None = None
    #: ``YYYY-MM-DD``. Se assente, si risponde con il preavviso.
    available_from: str | None = None
    how_did_you_hear: str = "Company website"
    #: Testo libero, per quando il form chiede la RAL attesa in una casella di
    #: testo invece che con un numero.
    salary_note: str | None = Field(default=None, max_length=300)

    #: I form ATS chiedono spesso genere, etnia, stato di veterano e disabilita'
    #: (EEO). Sono categorie protette, e ogni form offre "preferisco non
    #: rispondere": si sceglie sempre quella. Cosi' il sistema non conserva
    #: nessun dato particolare su un database di terzi.
    decline_demographic_questions: bool = True

    #: Domande fuori elenco incontrate strada facendo, come testo gia' pronto.
    extra: dict[str, str] = Field(default_factory=dict)

    @field_validator("available_from")
    @classmethod
    def _valid_date(cls, v: str | None) -> str | None:
        if v and not _DATE_RE.match(v):
            raise ValueError(f"data non valida: {v!r} (atteso YYYY-MM-DD)")
        return v


class CandidateAnswers(_Base):
    """Tutto quello che serve per compilare una candidatura senza chiedertelo."""

    full_name: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=320)
    phone: str | None = Field(default=None, max_length=40)

    city: str | None = Field(default=None, max_length=120)
    #: ISO 3166-1 alpha-2, maiuscolo.
    country: str | None = None

    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None

    #: Paese (ISO alpha-2) -> stato del diritto al lavoro. Va compilato a mano:
    #: dedurlo dalla citta' di residenza sarebbe un'invenzione, ed e' proprio il
    #: campo su cui una risposta sbagliata brucia la candidatura.
    work_authorization: dict[str, WorkAuthorization] = Field(default_factory=dict)

    willing_to_relocate: bool = False
    notice_period_days: int | None = Field(default=None, ge=0, le=365)

    #: RAL lorda annua attesa, nella valuta indicata.
    salary_expectation_min: int | None = Field(default=None, ge=0)
    salary_expectation_max: int | None = Field(default=None, ge=0)
    salary_currency: str = "EUR"

    #: Lingue parlate con livello CEFR. Sono anche un hard filter dello Stadio 0:
    #: senza, il sistema non puo' escludere un annuncio che richiede il tedesco.
    languages: dict[str, CefrLevel] = Field(default_factory=dict)

    ats_answers: AtsAnswers = Field(default_factory=AtsAnswers)

    @field_validator("phone")
    @classmethod
    def _plausible_phone(cls, v: str | None) -> str | None:
        if v and not _PHONE_RE.match(v):
            raise ValueError(f"numero di telefono non plausibile: {v!r}")
        return v

    @field_validator("country")
    @classmethod
    def _alpha2(cls, v: str | None) -> str | None:
        if v is None:
            return None
        code = v.upper()
        if len(code) != 2 or not code.isalpha():
            raise ValueError(f"codice paese non valido: {v!r} (atteso ISO alpha-2, es. IT)")
        return code

    @field_validator("work_authorization")
    @classmethod
    def _alpha2_keys(cls, v: dict[str, str]) -> dict[str, str]:
        out = {}
        for country, status in v.items():
            code = country.upper()
            if len(code) != 2 or not code.isalpha():
                raise ValueError(f"codice paese non valido in work_authorization: {country!r}")
            out[code] = status
        return out

    @field_validator("languages")
    @classmethod
    def _iso639(cls, v: dict[str, str]) -> dict[str, str]:
        out = {}
        for code, level in v.items():
            lowered = code.lower()
            if not 2 <= len(lowered) <= 3 or not lowered.isalpha():
                raise ValueError(f"codice lingua non valido: {code!r} (atteso ISO 639-1, es. it)")
            out[lowered] = level
        return out

    @field_validator("salary_currency")
    @classmethod
    def _iso4217(cls, v: str) -> str:
        code = v.upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(f"valuta non valida: {v!r} (atteso ISO 4217, es. EUR)")
        return code

    @model_validator(mode="after")
    def _salary_range_ordered(self) -> CandidateAnswers:
        lo, hi = self.salary_expectation_min, self.salary_expectation_max
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("la RAL attesa massima e' inferiore alla minima")
        return self

    # -- costruzione e revisione ----------------------------------------------

    @classmethod
    def from_master_profile(cls, profile: MasterProfile) -> CandidateAnswers:
        """Bozza precompilata con i soli dati gia' presenti nel CV.

        Tutto il resto resta vuoto di proposito. In particolare
        ``work_authorization``: vivere a Milano non dimostra la cittadinanza
        italiana, e questo e' il modulo che finisce dentro le candidature vere.
        """
        contact = profile.contact
        if not contact.email:
            raise ValueError(
                "il profilo non ha un'email: e' obbligatoria in ogni form di "
                "candidatura, aggiungila a master_profile.json prima di procedere"
            )
        return cls(
            full_name=contact.full_name,
            email=contact.email,
            phone=contact.phone,
            city=contact.city,
            country=contact.country,
            linkedin_url=contact.linkedin_url,
            github_url=contact.github_url,
            portfolio_url=contact.portfolio_url,
            languages={lang.code: lang.level for lang in profile.languages},
        )

    def warnings(self) -> list[str]:
        """Cosa manca ancora per potersi candidare davvero.

        Non sono errori di validazione: il modulo e' valido anche incompleto, ma
        con questi buchi la candidatura si blocca al primo form.
        """
        out: list[str] = []
        if not self.phone:
            out.append("telefono mancante: quasi nessun form ATS accetta l'invio senza")
        if not self.work_authorization:
            out.append(
                "work_authorization vuoto: e' il filtro che evita di candidarsi dove "
                "servirebbe sponsorship. Valori ammessi: citizen, permanent_resident, "
                "eu_eligible, visa_holder, requires_sponsorship, none"
            )
        if not self.languages:
            out.append(
                "nessuna lingua dichiarata: senza, non si possono escludere gli "
                "annunci che ne richiedono una che non parli"
            )
        if self.salary_expectation_min is None and self.ats_answers.salary_note is None:
            out.append(
                "nessuna RAL attesa: il sotto-punteggio salary_fit (10% della rubrica) "
                "resta neutro e i form che la chiedono vanno compilati a mano"
            )
        if not self.linkedin_url:
            out.append("LinkedIn mancante: e' un campo richiesto in molti form")
        if self.notice_period_days is None:
            out.append("preavviso non indicato: viene chiesto in quasi ogni primo colloquio")
        return out
