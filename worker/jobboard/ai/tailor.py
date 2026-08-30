"""Fase 6: il CV riscritto su misura per un annuncio.

**Dal modello passa solo la prosa.** Nomi delle aziende, date, titoli di studio,
recapiti, lingue e certificazioni non entrano nemmeno nella richiesta: li mette
il template leggendoli dal ``MasterProfile``. Il modello riceve i fatti e
restituisce soltanto le parti che vanno riscritte — le cinque keyword, il
summary, i bullet, le competenze — e tutto il resto del documento e' una copia,
non una generazione.

E' la decisione che rende governabile il resto della fase. Un modello che puo'
sbagliare una data e' un modello che va riletto per intero ogni volta; un modello
che le date non le tocca proprio ha una superficie di invenzione ristretta a
quello che :mod:`jobboard.ai.validator` sa verificare.

**L'ordine dei campi e' parte del prompt**, come nella rubrica: il modello li
genera nell'ordine in cui li dichiariamo. ``top_keywords`` sta per prima perche'
e' la scaletta di tutto il resto — summary e bullet vanno scritti *avendo gia'
deciso* su cosa puntare, non viceversa.

**L'ordine delle esperienze non lo decide il modello.** Il modello sceglie quali
tenere; a metterle in fila e' il template, in ordine cronologico inverso, che e'
quello che si aspettano un parser ATS e un lettore umano. Riordinare una carriera
non e' una scelta editoriale.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from ..models import Job
from ..schemas import MasterProfile
from .client import LLMProvider, LLMResult
from .prompts import load

log = logging.getLogger(__name__)

#: Lingue in cui il CV puo' essere scritto. Vincolate perche' ognuna ha i suoi
#: heading canonici nel template: una lingua senza heading produrrebbe un
#: documento meta' tradotto, che e' peggio di uno in inglese.
LINGUE = ("it", "en", "de", "es", "fr")

#: Quando l'annuncio non dichiara la lingua o ne dichiara una che non sappiamo
#: impaginare. L'inglese e' la scelta meno rischiosa: e' la lingua che ogni ATS
#: europeo processa, e un recruiter che si aspettava il tedesco legge comunque un
#: CV inglese, mentre non e' vero il contrario.
LINGUA_PREDEFINITA = "en"

_NOMI_LINGUA = {
    "it": "italiano",
    "en": "inglese",
    "de": "tedesco",
    "es": "spagnolo",
    "fr": "francese",
}

#: Oltre questa lunghezza la job description viene tagliata: come nella rubrica,
#: la coda degli annunci e' informativa privacy e pari opportunita', che non
#: cambiano una riga del CV.
_MAX_DESCRIPTION_CHARS = 12_000


class _Response(BaseModel):
    """Base per l'output del modello.

    ``extra="ignore"``, al contrario del resto del progetto: questo e' output di
    un modello, non un file scritto da noi. Un campo in piu' inventato non deve
    far fallire la generazione — a fallire, semmai, sara' il validatore, che
    guarda i campi che contano.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class TailoredBullet(_Response):
    source_id: str = Field(
        description=(
            "L'id ESATTO del bullet del profilo da cui questa frase deriva. "
            "Non inventarlo e non fonderne due: e' la fonte che verra' verificata."
        )
    )
    text: str = Field(description="Il bullet riscritto in Action-Context-Result. Una o due righe.")


class TailoredExperience(_Response):
    id: str = Field(description="L'id ESATTO dell'esperienza nel profilo.")
    bullets: list[TailoredBullet] = Field(default_factory=list)


class TailoredSkill(_Response):
    """Una competenza, con la sua provenienza.

    Due campi e non una stringa perche' **come si scrive** e **da dove viene**
    sono due cose diverse, e servono entrambe. Un ATS confronta la parola
    dell'annuncio, quindi ``text`` dice "Postgres" se l'annuncio dice "Postgres";
    ma quello che rende vera l'affermazione e' il "PostgreSQL" scritto nel
    profilo, e quello e' ``source``.

    E' anche l'unico modo di far convivere questa regola con la Fase 6.7: un CV
    in inglese scrive "Teamwork" dove il profilo italiano dice "Lavoro in team".
    Senza la provenienza dichiarata, tradurre correttamente sarebbe
    indistinguibile dall'inventare.
    """

    text: str = Field(description="Come va scritta nel CV, nella lingua del documento.")
    source: str = Field(
        description=(
            "La competenza del profilo da cui viene, copiata ESATTAMENTE come e' "
            "scritta li'. Se nessuna competenza del profilo la sostiene, non "
            "aggiungere la voce."
        )
    )


class TailoredSkills(_Response):
    hard: list[TailoredSkill] = Field(
        default_factory=list,
        description=(
            "Tecnologie, linguaggi, strumenti, con davanti quelli richiesti dall'annuncio."
        ),
    )
    soft: list[TailoredSkill] = Field(default_factory=list, description="Trasversali, poche.")


class TailoredCV(_Response):
    """Le sole parti del CV che il modello scrive."""

    top_keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Le 5 espressioni dell'annuncio che pesano di piu' nello screening e che "
            "il candidato puo' sostenere. Esattamente 5, o meno se non ce ne sono 5 di vere."
        ),
    )
    summary: str = Field(description="45-60 parole, calibrate su questo annuncio.")
    experience: list[TailoredExperience] = Field(default_factory=list)
    skills: TailoredSkills = Field(default_factory=TailoredSkills)

    def bullet_count(self) -> int:
        return sum(len(e.bullets) for e in self.experience)

    def word_count(self) -> int:
        """Parole della sola prosa: e' la grandezza che il loop di fit riduce."""
        parole = len(self.summary.split())
        for esperienza in self.experience:
            parole += sum(len(b.text.split()) for b in esperienza.bullets)
        return parole


def language_for(job: Job) -> str:
    """La lingua del CV, dedotta da quella dell'annuncio (6.7).

    Si guarda ``job.lang``, che la Fase 2 ricava dal testo dell'annuncio e non
    dal paese: le offerte di aziende internazionali a Milano sono scritte in
    inglese, e rispondere in italiano a un annuncio inglese fa arrivare il CV a
    un recruiter che non lo legge.
    """
    codice = (job.lang or "").strip().lower()[:2]
    return codice if codice in LINGUE else LINGUA_PREDEFINITA


def system_prompt(lingua: str) -> str:
    """Il prompt invariante piu' la sola istruzione che cambia per annuncio.

    La lingua sta qui e non nel file del prompt perche' e' l'unica parte che
    dipende dall'annuncio: tenerla fuori lascia il `.md` sostituibile per intero
    senza doverci reinfilare una direttiva.
    """
    nome = _NOMI_LINGUA.get(lingua, _NOMI_LINGUA[LINGUA_PREDEFINITA])
    return (
        f"{load('cv_writer')}\n\n"
        f"## Lingua\n\n"
        f"Scrivi summary, bullet e competenze in **{nome}**, "
        f"qualunque sia la lingua del profilo di partenza. "
        f"I nomi propri di tecnologie, aziende e prodotti non si traducono."
    )


def build_prompt(profile: MasterProfile, job: Job, gaps: list[str] | None = None) -> str:
    """Prima il materiale disponibile, poi l'annuncio a cui va adattato."""
    blocchi = [_profile_block(profile), "=" * 60, _job_block(job)]
    if gaps:
        # I gap li ha gia' calcolati lo Stadio 2 e sono salvati sul match. Darli
        # al generatore serve a una cosa sola: che non provi a colmarli. Senza,
        # il modo piu' naturale di "adattare il CV all'annuncio" e' esattamente
        # scrivere che si sa fare la cosa che manca.
        elenco = "\n".join(f"- {g}" for g in gaps)
        blocchi += [
            "=" * 60,
            "## GAP GIA' RILEVATI\n\n"
            "Requisiti dell'annuncio che il candidato NON copre. Non colmarli, non "
            "alluderci, non metterli fra le keyword: sono la parte onesta di questa "
            f"candidatura.\n\n{elenco}",
        ]
    return "\n\n".join(blocchi)


def _profile_block(profile: MasterProfile) -> str:
    """Il materiale grezzo, con gli id ben visibili.

    Gli id sono l'unica cosa che il modello deve ricopiare alla lettera: sono
    scritti in testa a ogni voce e ripetuti nell'istruzione, perche' un
    ``source_id`` sbagliato manda in errore il validatore e costa una
    rigenerazione.
    """
    righe = ["## PROFILO DEL CANDIDATO", ""]
    if profile.headline:
        righe.append(f"Ruolo attuale: {profile.headline}")
    if profile.summary:
        righe.append(f"Presentazione originale: {profile.summary}")

    righe.append("\n### Esperienze")
    for esperienza in profile.experiences:
        fine = esperienza.end or "in corso"
        righe.append(
            f"\n[id: {esperienza.id}] **{esperienza.role}** — {esperienza.company} "
            f"({esperienza.start} → {fine})"
        )
        for bullet in esperienza.bullets:
            righe.append(f"  [id: {bullet.id}] {bullet.text}")
            if bullet.result:
                # Ripetuto perche' e' la parte piu' facile da perdere e la piu'
                # pericolosa da reinventare: un risultato misurabile che sparisce
                # viene rimpiazzato da uno inventato al tentativo dopo.
                righe.append(f"      risultato dichiarato: {bullet.result}")
        if esperienza.tech:
            righe.append(f"      stack: {', '.join(esperienza.tech)}")

    if profile.projects:
        righe.append("\n### Progetti")
        for progetto in profile.projects:
            tech = f" [{', '.join(progetto.tech)}]" if progetto.tech else ""
            righe.append(f"- [id: {progetto.id}] {progetto.name}: {progetto.description}{tech}")

    if profile.skills.hard:
        righe.append(f"\n### Competenze tecniche dichiarate\n{', '.join(profile.skills.hard)}")
    if profile.skills.soft:
        righe.append(f"\n### Competenze trasversali dichiarate\n{', '.join(profile.skills.soft)}")

    return "\n".join(righe)


def _job_block(job: Job) -> str:
    righe = ["## ANNUNCIO", "", f"Titolo: {job.title}", f"Azienda: {job.company}"]
    if luogo := ", ".join(p for p in (job.city, job.region, job.country) if p):
        righe.append(f"Luogo: {luogo}")
    righe.append(f"\n### Descrizione\n{(job.description_clean or '')[:_MAX_DESCRIPTION_CHARS]}")
    return "\n".join(righe)


def tailor(
    provider: LLMProvider,
    profile: MasterProfile,
    job: Job,
    *,
    lingua: str | None = None,
    gaps: list[str] | None = None,
    model: str | None = None,
    correzioni: str | None = None,
) -> LLMResult[TailoredCV]:
    """Genera il CV su misura. Una chiamata.

    ``correzioni`` e' il testo prodotto da :func:`jobboard.ai.validator.feedback`
    dopo un tentativo respinto: si rigenera dicendo *cosa* era sbagliato invece
    di risperare in un esito diverso a parita' di richiesta.

    La temperatura non e' zero. E' l'unico punto del progetto in cui serve:
    a temperatura zero un tentativo respinto dal validatore verrebbe rigenerato
    quasi identico, e il ciclo di correzione girerebbe a vuoto fino a esaurire i
    tentativi.
    """
    lingua = lingua or language_for(job)
    prompt = build_prompt(profile, job, gaps)
    if correzioni:
        prompt = f"{prompt}\n\n{'=' * 60}\n\n{correzioni}"

    return provider.generate_structured(
        prompt,
        TailoredCV,
        system=system_prompt(lingua),
        model=model,
        temperature=0.3,
    )


def compress(
    provider: LLMProvider,
    cv: TailoredCV,
    profile: MasterProfile,
    job: Job,
    *,
    eccesso: float,
    lingua: str | None = None,
    model: str | None = None,
) -> LLMResult[TailoredCV]:
    """Riscrive il CV piu' corto, perche' non sta in una pagina.

    ``eccesso`` e' quanto sfora, come frazione (0.4 = una pagina e mezza circa).
    Serve a chiedere un taglio proporzionato: chiedere "accorcia" a un documento
    che sfora di tre righe produce un CV dimezzato, e un CV dimezzato non e' piu'
    quello che il validatore aveva approvato.

    **Si taglia, non si riscrive.** Le frasi che restano devono restare com'erano:
    ogni riformulazione e' un'altra occasione di inventare, e questa passata
    serve a fare spazio, non a migliorare il testo.
    """
    lingua = lingua or language_for(job)
    da_togliere = max(10, round(cv.word_count() * min(eccesso, 0.5)))

    istruzioni = (
        "## DA ACCORCIARE\n\n"
        f"Il CV qui sotto occupa piu' di una pagina: va ridotto di circa "
        f"{da_togliere} parole su {cv.word_count()}.\n\n"
        "Come:\n"
        "1. Elimina per intero i bullet meno rilevanti per questo annuncio. "
        "Un bullet in meno vale piu' di cinque bullet limati.\n"
        "2. Se non basta, accorcia il summary restando sopra le 45 parole.\n"
        "3. Togli dalle competenze quelle che l'annuncio non chiede.\n\n"
        "Cosa NON fare: riscrivere le frasi che restano, cambiare un `source_id`, "
        "aggiungere qualcosa che prima non c'era. Le frasi tenute vanno tenute "
        "identiche.\n\n"
        f"### CV attuale\n\n{cv.model_dump_json(indent=2)}"
    )

    return provider.generate_structured(
        f"{build_prompt(profile, job)}\n\n{'=' * 60}\n\n{istruzioni}",
        TailoredCV,
        system=system_prompt(lingua),
        model=model,
        # Zero, al contrario di `tailor`: qui non si vuole varieta', si vuole che
        # le frasi sopravvissute tornino indietro uguali.
        temperature=0.0,
    )
