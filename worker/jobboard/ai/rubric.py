"""Stadio 2: requisiti estratti e rubrica pesata, in una sola chiamata.

È l'unico stadio che costa. Ci arrivano una quarantina di annunci al giorno, non
cinquecento, ed è per questo che i due stadi a monte esistono.

**Perché una chiamata sola e non due.** Il piano descrive l'estrazione dei
requisiti e la rubrica come due passi. Farli come due chiamate significherebbe
mandare due volte la stessa job description — che è il 90% dei token — e
accettare che le due risposte si contraddicano: il punteggio direbbe "copre
tutti i must have" mentre la lista dei must have salvata a fianco ne contiene
uno che manca. Una chiamata sola costa metà e non può essere incoerente con sé
stessa.

**L'ordine dei campi nello schema è parte del prompt.** Il modello genera i
campi nell'ordine in cui li dichiariamo: prima estrae i requisiti, poi assegna i
punteggi *avendoli già scritti*. Invertire l'ordine gli farebbe dare un voto
prima di aver guardato cosa sta valutando.

**La media pesata la fa il codice.** Al modello si chiedono sei giudizi, non un
totale: gli LLM fanno aritmetica in modo inaffidabile, e soprattutto un totale
prodotto dal modello non si può ritarare. Con i sotto-punteggi salvati,
``scripts/calibrate.py`` prova pesi diversi sugli stessi dati senza rifare una
sola chiamata.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import Job
from ..schemas import MasterProfile
from .client import LLMProvider, LLMResult

log = logging.getLogger(__name__)

#: Pesi della rubrica. Sommano a 1: la verifica sta nei test, perché un peso
#: cambiato a mano senza aggiustare gli altri produrrebbe punteggi fuori scala
#: senza che nulla protesti.
#:
#: Le chiavi sono anche i nomi dei campi di :class:`JobAssessment` e le chiavi
#: della colonna ``match.subscores``: cambiarne una qui la cambia ovunque, ed è
#: il motivo per cui il punteggio di copertura dei requisiti graditi si chiama
#: ``nice_to_have_coverage`` e non ``nice_to_have`` — quest'ultimo è l'elenco.
RUBRIC_WEIGHTS: dict[str, float] = {
    "must_have_coverage": 0.40,
    "nice_to_have_coverage": 0.10,
    "seniority_fit": 0.15,
    "domain_fit": 0.10,
    "location_fit": 0.15,
    "salary_fit": 0.10,
}

#: Punteggio di un criterio su cui non ci sono elementi per pronunciarsi. Non
#: zero: zero è un giudizio negativo, e un annuncio che non dichiara la RAL non
#: sta offrendo una RAL bassa.
NEUTRAL = 50

#: Oltre questa lunghezza la job description viene tagliata. Il modello
#: reggerebbe molto di più, ma la coda degli annunci è fatta di informativa
#: privacy e dichiarazioni di pari opportunità, che occupano token e non
#: cambiano il giudizio.
_MAX_DESCRIPTION_CHARS = 12_000


class _Response(BaseModel):
    """Base per gli schemi di risposta del modello.

    ``extra="ignore"`` di proposito, al contrario di tutto il resto del progetto:
    questo è output di un modello, non un file che scriviamo noi. Un campo in più
    inventato dal modello non deve far fallire la valutazione dell'annuncio.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class LanguageRequirement(_Response):
    """Una lingua richiesta dall'annuncio.

    Lista di oggetti e non dizionario: l'API accetta un sottoinsieme di JSON
    Schema in cui un oggetto senza proprietà dichiarate non è esprimibile, e un
    dizionario a chiavi libere è esattamente quello.
    """

    code: str = Field(description="ISO 639-1, minuscolo: it, en, de")
    level: str = Field(description="Livello richiesto: A2, B1, B2, C1, C2, madrelingua, non detto")


def _clamp(value: int) -> int:
    return max(0, min(100, value))


class JobAssessment(_Response):
    """Requisiti estratti e giudizio, nell'ordine in cui vanno prodotti."""

    # --- prima si legge ---
    must_have: list[str] = Field(
        default_factory=list,
        description="Requisiti dichiarati come obbligatori. Massimo 8, come li scrive l'annuncio.",
    )
    nice_to_have: list[str] = Field(
        default_factory=list, description="Requisiti graditi ma non obbligatori. Massimo 6."
    )
    tech_stack: list[str] = Field(
        default_factory=list, description="Tecnologie, linguaggi e strumenti citati."
    )
    min_years_experience: int | None = Field(
        default=None, description="Anni minimi richiesti, null se non dichiarati."
    )
    max_years_experience: int | None = None
    languages_required: list[LanguageRequirement] = Field(default_factory=list)
    remote_policy: str | None = Field(
        default=None,
        description=(
            "La politica sulla presenza come la descrive il testo, se contraddice o "
            "precisa il campo strutturato. Esempio: 'remote ma 2 giorni in sede al mese'."
        ),
    )
    requires_work_authorization: bool | None = Field(
        default=None,
        description="True se l'annuncio richiede esplicitamente di poter già lavorare nel paese.",
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Segnali negativi concreti: non retribuito, solo equity, partita IVA "
            "obbligatoria, reperibilità continua. Vuoto se non ce ne sono."
        ),
    )

    # --- poi si giudica ---
    must_have_coverage: int = Field(
        description="0-100. Quanta parte dei requisiti obbligatori il candidato copre davvero."
    )
    nice_to_have_coverage: int = Field(description="0-100. Copertura dei requisiti graditi.")
    seniority_fit: int = Field(
        description="0-100. 100 se il livello richiesto coincide, cala allontanandosi."
    )
    domain_fit: int = Field(description="0-100. Vicinanza del settore e del tipo di prodotto.")
    location_fit: int = Field(
        description=(
            "0-100. Compatibilità fra luogo e modalità dell'annuncio e dove vive il candidato."
        )
    )
    salary_fit: int = Field(
        description=f"0-100. Vale {NEUTRAL} se l'annuncio non dichiara una retribuzione."
    )

    rationale: str = Field(
        description="Due righe in italiano: perché questo punteggio. Concreto, senza convenevoli."
    )
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "I requisiti richiesti che il candidato non copre, in italiano e in breve. "
            "Vuoto se li copre tutti."
        ),
    )

    @field_validator(*RUBRIC_WEIGHTS, mode="before")
    @classmethod
    def _in_range(cls, v: Any) -> Any:
        """Riporta nell'intervallo invece di rifiutare.

        Un modello che risponde 105 intendeva 100: buttare via la valutazione di
        un annuncio — e la chiamata che l'ha prodotta — per un fuori scala
        sarebbe uno spreco senza vantaggi.
        """
        return _clamp(int(v)) if isinstance(v, int | float) else v

    def subscores(self) -> dict[str, int]:
        """I sei giudizi, nell'ordine della rubrica."""
        return {nome: _clamp(int(getattr(self, nome))) for nome in RUBRIC_WEIGHTS}

    def requirement_fields(self) -> dict[str, Any]:
        """I campi che finiscono in ``job_requirements``."""
        return {
            "must_have": self.must_have,
            "nice_to_have": self.nice_to_have,
            "tech_stack": self.tech_stack,
            "min_years_experience": self.min_years_experience,
            "max_years_experience": self.max_years_experience,
            "languages_required": {
                lingua.code.lower(): lingua.level for lingua in self.languages_required
            },
            "remote_policy": self.remote_policy,
            "requires_work_authorization": self.requires_work_authorization,
            "red_flags": self.red_flags,
        }


def weighted_total(subscores: dict[str, int], weights: dict[str, float] | None = None) -> int:
    """La media pesata dei sotto-punteggi, arrotondata a intero 0-100.

    Un criterio assente dai sotto-punteggi vale :data:`NEUTRAL`: succede quando
    si ricalcola un punteggio salvato da una versione precedente della rubrica,
    e trattarlo come zero riscriverebbe la storia al ribasso.
    """
    pesi = weights or RUBRIC_WEIGHTS
    totale = sum(pesi.values())
    if totale <= 0:
        raise ValueError("i pesi della rubrica sommano a zero")
    punteggio = sum(_clamp(subscores.get(nome, NEUTRAL)) * peso for nome, peso in pesi.items())
    return round(punteggio / totale)


SYSTEM_PROMPT = """\
Sei un recruiter tecnico esperto. Valuti la compatibilità fra un candidato e un \
annuncio di lavoro, e il tuo giudizio serve a decidere se vale la pena candidarsi.

Regole:
- Giudichi solo su quello che leggi. Non attribuisci al candidato competenze che \
non sono nel suo profilo, nemmeno se sembrano ovvie per il suo ruolo.
- Un requisito non dichiarato non è un requisito soddisfatto: se l'annuncio chiede \
cinque anni di Kubernetes e il profilo non lo cita, quello è un gap.
- Sei severo sui requisiti obbligatori e indulgente su quelli graditi.
- Quando l'annuncio non dice nulla su un criterio, quel criterio vale 50: non è \
un difetto dell'annuncio né un merito.
- Scrivi rationale e gaps in italiano, asciutti, senza formule di cortesia."""


def build_prompt(profile: MasterProfile, job: Job) -> str:
    """Compone la richiesta: prima chi è il candidato, poi cosa cerca l'annuncio."""
    return f"{_profile_block(profile)}\n\n{'=' * 60}\n\n{_job_block(job)}"


def _profile_block(profile: MasterProfile) -> str:
    righe = ["## CANDIDATO", ""]
    if profile.headline:
        righe.append(f"Ruolo: {profile.headline}")
    contatto = profile.contact
    if luogo := ", ".join(p for p in (contatto.city, contatto.country) if p):
        righe.append(f"Residenza: {luogo}")
    if profile.languages:
        lingue = ", ".join(f"{lang.code} {lang.level}" for lang in profile.languages)
        righe.append(f"Lingue: {lingue}")
    if profile.summary:
        righe.append(f"\n{profile.summary}")

    righe.append("\n### Esperienza")
    for esperienza in profile.experiences:
        fine = esperienza.end or "in corso"
        righe.append(
            f"\n**{esperienza.role}** — {esperienza.company} ({esperienza.start} - {fine})"
        )
        righe.extend(f"- {bullet.text}" for bullet in esperienza.bullets)
        if esperienza.tech:
            righe.append(f"  Stack: {', '.join(esperienza.tech)}")

    if profile.projects:
        righe.append("\n### Progetti")
        for progetto in profile.projects:
            tech = f" [{', '.join(progetto.tech)}]" if progetto.tech else ""
            righe.append(f"- {progetto.name}: {progetto.description}{tech}")

    if profile.education:
        righe.append("\n### Formazione")
        for titolo in profile.education:
            campo = f" in {titolo.field_of_study}" if titolo.field_of_study else ""
            righe.append(f"- {titolo.degree}{campo}, {titolo.institution} ({titolo.end or ''})")

    if profile.skills.hard:
        righe.append(f"\n### Competenze tecniche\n{', '.join(profile.skills.hard)}")

    return "\n".join(righe)


def _job_block(job: Job) -> str:
    righe = ["## ANNUNCIO", "", f"Titolo: {job.title}", f"Azienda: {job.company}"]
    if luogo := ", ".join(p for p in (job.city, job.region, job.country) if p):
        righe.append(f"Luogo: {luogo}")
    righe.append(f"Modalità dichiarata dalla fonte: {job.work_mode.value}")
    righe.append(f"Contratto: {job.contract_type.value}")
    righe.append(f"Livello dedotto dal titolo: {job.seniority.value}")
    righe.append(f"Retribuzione: {_salary_line(job)}")
    righe.append(f"\n### Descrizione\n{(job.description_clean or '')[:_MAX_DESCRIPTION_CHARS]}")
    return "\n".join(righe)


def _salary_line(job: Job) -> str:
    if not job.salary_is_stated:
        return f"non dichiarata (salary_fit deve valere {NEUTRAL})"
    valuta = job.salary_currency or ""
    periodo = job.salary_period.value if job.salary_period else "yearly"
    if job.salary_min and job.salary_max:
        return f"{job.salary_min}-{job.salary_max} {valuta} ({periodo})"
    return f"{job.salary_min or job.salary_max} {valuta} ({periodo})"


def assess(
    provider: LLMProvider,
    profile: MasterProfile,
    job: Job,
    *,
    model: str | None = None,
) -> LLMResult[JobAssessment]:
    """Estrae i requisiti e valuta l'annuncio. Una chiamata, un oggetto.

    Al modello si chiede nel prompt di lasciare neutri i criteri privi di
    elementi, ma :func:`neutralize_unknowable` lo verifica dopo: sono regole
    deterministiche, e le regole deterministiche non si delegano a chi risponde
    in modo probabilistico.
    """
    risultato = provider.generate_structured(
        build_prompt(profile, job), JobAssessment, system=SYSTEM_PROMPT, model=model
    )
    for criterio in neutralize_unknowable(risultato.value, job):
        log.debug("job %s: %s riportato a neutro, mancavano gli elementi", job.id, criterio)
    return risultato


def neutralize_unknowable(assessment: JobAssessment, job: Job) -> list[str]:
    """Riporta a :data:`NEUTRAL` i criteri su cui non c'era niente da giudicare.

    **Assenza di prove non è prova di eccellenza.** Vale per la retribuzione — un
    annuncio che non dichiara la RAL non ne sta offrendo una buona — e vale, in
    modo molto più costoso, per i requisiti.

    Il caso che ha reso necessaria questa funzione, trovato alla prima run vera:
    un annuncio da contabile a Pune, con una descrizione di quattro righe e
    nessun requisito. Il modello ha estratto ``must_have = []`` e ha concluso,
    con impeccabile logica vacua, che il candidato copre il 100% di zero
    requisiti. ``must_have_coverage`` pesa il 40%, quindi quaranta punti nati dal
    nulla hanno portato in cima alla classifica un annuncio che lo stesso modello
    definiva "completamente slegato dal profilo".

    Un elenco di requisiti vuoto significa che l'annuncio non dice cosa serve.
    L'unica risposta onesta è "non lo so", che qui vale 50.

    Ritorna i nomi dei criteri corretti, per poterli registrare.
    """
    corretti: list[str] = []

    def neutralizza(criterio: str) -> None:
        if getattr(assessment, criterio) != NEUTRAL:
            setattr(assessment, criterio, NEUTRAL)
            corretti.append(criterio)

    if not job.salary_is_stated:
        neutralizza("salary_fit")
    if not assessment.must_have:
        neutralizza("must_have_coverage")
    if not assessment.nice_to_have:
        neutralizza("nice_to_have_coverage")

    return corretti


def to_requirements_row(assessment: JobAssessment, job_id: int, model: str) -> dict[str, Any]:
    """I valori per una riga ``job_requirements``."""
    return {
        "job_id": job_id,
        **assessment.requirement_fields(),
        "extracted_with": model,
        "extracted_at": dt.datetime.now(dt.UTC),
    }
