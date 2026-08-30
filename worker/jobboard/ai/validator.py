"""Il validatore anti-invenzione: la Fase 6.2.

Il prompt chiede al modello di non inventare. Questo modulo lo **verifica**, e
una violazione blocca il render invece di produrre un PDF da rileggere. E' la
differenza fra un sistema che genera CV e uno di cui ci si puo' fidare abbastanza
da spedirli: senza, ogni documento andrebbe riletto riga per riga contro
l'originale, che e' esattamente il lavoro che il sistema doveva togliere.

**Tre regole, tutte deterministiche.**

1. *Ogni frase ha una fonte.* Ogni bullet dichiara il ``source_id`` del bullet del
   profilo da cui viene, e quell'id deve esistere e appartenere all'esperienza
   sotto cui e' stato messo. Un bullet giusto sotto il datore di lavoro sbagliato
   e' comunque un'affermazione falsa.
2. *Le cifre non si inventano.* Ogni numero del testo generato deve comparire nel
   testo di partenza. E' la regola che conta di piu': un numero falso su un CV e'
   l'unico errore che in un colloquio non si recupera, e "ridotto del 40%" e'
   esattamente il tipo di frase che un modello scrive quando la fonte dice solo
   "ridotto".
3. *Le competenze si dichiarano solo se dichiarate.* Ogni voce di ``skills`` deve
   risalire al profilo.

**Un id e' un'affermazione, non una prova.** Il modello puo' scrivere qualunque
cosa e attribuirla a ``acme-be-1``: e' per questo che la regola 2 guarda il
contenuto e non si ferma alla provenienza dichiarata.

**Cosa questo modulo non fa.** Non giudica se il CV e' buono, non conta le parole
del summary, non verifica che le keyword siano cinque. Quelle sono questioni di
forma, le sistema il template o il loop di fit; qui si risponde a una domanda
sola — *c'e' dentro qualcosa che non e' vero?* — e ogni regola in piu' che non
risponda a quella domanda e' un'occasione di bloccare un CV corretto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..schemas import MasterProfile
from ..schemas.profile import Bullet
from .tailor import TailoredCV

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Violazione:
    """Una affermazione del CV generato che il profilo non sostiene."""

    regola: str
    #: Dove si trova, in forma leggibile: ``experience[acme-be].bullet[2]``.
    dove: str
    dettaglio: str

    def __str__(self) -> str:
        return f"{self.dove}: {self.dettaglio}"


# --- regola 1: ogni frase ha una fonte ----------------------------------------


def _verifica_provenienza(cv: TailoredCV, profile: MasterProfile) -> list[Violazione]:
    per_esperienza = {e.id: {b.id for b in e.bullets} for e in profile.experiences}
    violazioni: list[Violazione] = []

    for esperienza in cv.experience:
        attesi = per_esperienza.get(esperienza.id)
        if attesi is None:
            violazioni.append(
                Violazione(
                    "esperienza-inesistente",
                    f"experience[{esperienza.id}]",
                    f"nel profilo non esiste un'esperienza con id {esperienza.id!r}",
                )
            )
            continue

        for indice, bullet in enumerate(esperienza.bullets):
            if bullet.source_id in attesi:
                continue
            # Distinguere i due casi non e' pedanteria: "id inesistente" e' un
            # errore di trascrizione del modello, "bullet di un'altra esperienza"
            # e' un'affermazione attribuita al datore di lavoro sbagliato. Il
            # secondo e' molto piu' grave e il messaggio deve dirlo.
            altrove = any(bullet.source_id in ids for ids in per_esperienza.values())
            violazioni.append(
                Violazione(
                    "bullet-di-un-altra-esperienza" if altrove else "bullet-inesistente",
                    f"experience[{esperienza.id}].bullet[{indice}]",
                    (
                        f"il bullet {bullet.source_id!r} appartiene a un'altra esperienza"
                        if altrove
                        else f"nel profilo non esiste un bullet con id {bullet.source_id!r}"
                    ),
                )
            )

    return violazioni


# --- regola 2: le cifre non si inventano --------------------------------------

#: Moltiplicatore che segue immediatamente un numero: ``40k``, ``40 milioni``.
_MOLTIPLICATORI: dict[str, float] = {
    "k": 1_000,
    "mila": 1_000,
    "mil": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mln": 1_000_000,
    "milione": 1_000_000,
    "milioni": 1_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "mn": 1_000_000,
}

_UNITA_IT = {
    "zero": 0,
    "uno": 1,
    "una": 1,
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10,
    "undici": 11,
    "dodici": 12,
    "tredici": 13,
    "quattordici": 14,
    "quindici": 15,
    "sedici": 16,
    "diciassette": 17,
    "diciotto": 18,
    "diciannove": 19,
}
_DECINE_IT = {
    "venti": 20,
    "trenta": 30,
    "quaranta": 40,
    "cinquanta": 50,
    "sessanta": 60,
    "settanta": 70,
    "ottanta": 80,
    "novanta": 90,
}
_UNITA_EN = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_DECINE_EN = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _numeri_a_parole() -> dict[str, float]:
    """Il vocabolario dei numeri scritti a lettere, italiano e inglese.

    Serve perche' i due lati del confronto parlano lingue diverse. Il
    ``MasterProfile`` conserva il CV **come e' scritto**, e i CV italiani
    scrivono "da sei ore a venti minuti", "quaranta milioni di righe", "dal
    quaranta all'ottanta percento". Il CV generato usa le cifre, perche' e'
    quello che si fa in un CV moderno e quello che il prompt chiede.

    Senza questa tabella ogni riscrittura corretta risulterebbe un'invenzione:
    "80%" non compare da nessuna parte in "all'ottanta percento". Sarebbe il modo
    piu' rapido di rendere il validatore inutile — perche' un validatore che
    blocca i CV giusti viene spento.
    """
    vocabolario: dict[str, float] = {}
    vocabolario.update({p: float(v) for p, v in _UNITA_IT.items()})
    vocabolario.update({p: float(v) for p, v in _UNITA_EN.items()})
    vocabolario.update({p: float(v) for p, v in _DECINE_IT.items()})
    vocabolario.update({p: float(v) for p, v in _DECINE_EN.items()})
    vocabolario.update({"cento": 100.0, "hundred": 100.0, "mille": 1000.0})

    # Composti italiani: si scrivono attaccati, e davanti a "uno" e "otto" la
    # decina perde la vocale finale (ventuno, ventotto, trentuno...).
    for parola_decina, decina in _DECINE_IT.items():
        for parola_unita, unita in _UNITA_IT.items():
            if not 1 <= unita <= 9:
                continue
            radice = parola_decina[:-1] if parola_unita[0] in "uo" else parola_decina
            vocabolario[f"{radice}{parola_unita}"] = float(decina + unita)

    # Composti inglesi: separati da trattino o spazio, gestiti in `_estrai`.
    for parola_decina, decina in _DECINE_EN.items():
        for parola_unita, unita in _UNITA_EN.items():
            if 1 <= unita <= 9:
                vocabolario[f"{parola_decina}-{parola_unita}"] = float(decina + unita)

    return vocabolario


_PAROLE_NUMERO = _numeri_a_parole()

#: Parole che sono numeri da sole ma unita' di misura quando precedute da "per":
#: in "dal 40 all'80 per cento" non c'e' nessun cento. Senza questa eccezione una
#: percentuale scritta a parole introduce un 100 che la fonte non ha, e il CV
#: viene bloccato per un'invenzione che non esiste.
_UNITA_DOPO_PER = frozenset({"cento", "mille", "cent"})

_TOKEN = re.compile(r"[a-zA-Zàèéìòù]+(?:-[a-zA-Z]+)?|\d[\d.,]*")


def _valore_cifre(grezzo: str) -> float | None:
    """Interpreta un gruppo di cifre con separatori.

    La regola: un separatore seguito da **esattamente tre** cifre e' migliaia,
    altrimenti e' un decimale. Copre "1.000" e "1,000" come mille, "1,5" e "1.5"
    come uno virgola cinque, "1.234.567" come un milione e rotti. Non copre
    "1,500" inteso come uno virgola cinquecento, che in un CV non si scrive.
    """
    pulito = grezzo.rstrip(".,")
    if not pulito:
        return None
    if pulito.isdigit():
        return float(pulito)

    pezzi = re.split(r"[.,]", pulito)
    if all(len(p) == 3 for p in pezzi[1:]) and pezzi[0]:
        return float("".join(pezzi))

    ultimo = pezzi[-1]
    intero = "".join(pezzi[:-1])
    try:
        return float(f"{intero}.{ultimo}")
    except ValueError:  # pragma: no cover - il regex non produce altre forme
        return None


def numeri(testo: str) -> set[float]:
    """Tutti i valori numerici del testo, in cifre o a lettere.

    Percentuali, valute e unita' di misura non entrano nel confronto: "40%",
    "40 giorni" e "40k" contengono tutti il valore 40, ed e' il valore quello che
    non si puo' inventare. Confrontare anche l'unita' significherebbe bloccare un
    CV che scrive "6 ore" dove il profilo scriveva "sei ore".
    """
    trovati: set[float] = set()
    token = _TOKEN.findall(testo.lower())

    for indice, pezzo in enumerate(token):
        valore: float | None = None
        if pezzo[0].isdigit():
            valore = _valore_cifre(pezzo)
        elif pezzo in _PAROLE_NUMERO:
            if pezzo in _UNITA_DOPO_PER and indice and token[indice - 1] == "per":
                continue
            valore = _PAROLE_NUMERO[pezzo]
        if valore is None:
            continue

        # Un moltiplicatore subito dopo cambia il valore, non lo affianca:
        # "40 milioni" e' 40_000_000, e registrare anche 40 lascerebbe passare un
        # "40%" inventato solo perche' altrove si parlava di quaranta milioni.
        successivo = token[indice + 1] if indice + 1 < len(token) else ""
        if fattore := _MOLTIPLICATORI.get(successivo):
            trovati.add(valore * fattore)
            continue
        # Attaccato al numero: "40k", "3M".
        attaccato = (
            _MOLTIPLICATORI.get(pezzo[-1]) if len(pezzo) > 1 and pezzo[0].isdigit() else None
        )
        if attaccato and (base := _valore_cifre(pezzo[:-1])) is not None:
            trovati.add(base * attaccato)
            continue

        trovati.add(valore)

    return trovati


def _fonte_del_bullet(bullet: Bullet) -> str:
    """Tutto il testo del bullet di partenza, compresi i campi ACR.

    ``result`` sta a parte nello schema ma nel CV originale era una frase sola:
    un numero che vive li' dentro e' dichiarato quanto uno nel testo.
    """
    return " ".join(p for p in (bullet.text, bullet.action, bullet.context, bullet.result) if p)


def _testo_intero(profile: MasterProfile) -> str:
    """Il profilo come un unico blocco, per verificare i numeri del summary.

    Il summary non ha un bullet di riferimento: e' prosa che riassume tutto,
    quindi il confronto e' contro tutto — date comprese, perche' "tre anni di
    esperienza" si sostiene sulle date delle esperienze.
    """
    parti = [profile.summary or "", profile.headline or ""]
    for esperienza in profile.experiences:
        parti += [esperienza.role, esperienza.company, esperienza.start, esperienza.end or ""]
        parti += [_fonte_del_bullet(b) for b in esperienza.bullets]
    for progetto in profile.projects:
        parti.append(progetto.description)
    for titolo in profile.education:
        parti += [titolo.degree, titolo.institution, titolo.end or "", titolo.grade or ""]
    for certificazione in profile.certifications:
        parti += [certificazione.name, certificazione.issued or ""]
    return " ".join(p for p in parti if p)


def _verifica_cifre(cv: TailoredCV, profile: MasterProfile) -> list[Violazione]:
    sorgenti = {b.id: b for e in profile.experiences for b in e.bullets}
    violazioni: list[Violazione] = []

    for esperienza in cv.experience:
        for indice, bullet in enumerate(esperienza.bullets):
            fonte = sorgenti.get(bullet.source_id)
            if fonte is None:
                # Gia' segnalato dalla regola 1: qui si tace invece di contare
                # due volte lo stesso errore.
                continue
            if inventati := numeri(bullet.text) - numeri(_fonte_del_bullet(fonte)):
                violazioni.append(
                    Violazione(
                        "cifra-inventata",
                        f"experience[{esperienza.id}].bullet[{indice}]",
                        f"{_elenca(inventati)} non compare nel bullet {bullet.source_id!r}",
                    )
                )

    if inventati := numeri(cv.summary) - numeri(_testo_intero(profile)):
        violazioni.append(
            Violazione(
                "cifra-inventata",
                "summary",
                f"{_elenca(inventati)} non compare da nessuna parte nel profilo",
            )
        )

    return violazioni


def _elenca(valori: set[float]) -> str:
    ordinati = sorted(valori)
    testo = ", ".join(f"{v:g}" for v in ordinati)
    return f"il valore {testo}" if len(ordinati) == 1 else f"i valori {testo}"


# --- regola 3: le competenze si dichiarano solo se dichiarate -----------------


def _normalizza_skill(skill: str) -> str:
    """Toglie punteggiatura e maiuscole, tiene ``+`` e ``#``.

    ``Node.js`` e ``nodejs`` sono la stessa competenza scritta da due persone
    diverse; ``C++`` e ``C#`` non sono ``c``, ed e' l'unico motivo per cui questi
    due caratteri sopravvivono alla normalizzazione.
    """
    return re.sub(r"[^a-z0-9+#]", "", skill.lower())


def _verifica_competenze(cv: TailoredCV, profile: MasterProfile) -> list[Violazione]:
    """Ogni competenza deve dichiarare da quale voce del profilo viene.

    Il confronto e' **esatto** sulla provenienza dichiarata, non somigliante
    sulla parola stampata. La prima versione faceva il contrario — match per
    prefisso dai quattro caratteri, come il filtro delle fonti — e aveva due
    difetti opposti, entrambi gravi:

    * bloccava un CV corretto: un CV inglese scrive "Teamwork" dove il profilo
      italiano dice "Lavoro in team", e nessuna somiglianza di stringa lega le
      due cose;
    * lasciava passare un CV falso: ``"javascript".startswith("java")``, quindi
      un profilo che dichiara Java giustificava un CV che dichiara JavaScript.

    Con la provenienza dichiarata dal modello i due casi si separano: ``text``
    e' libero di essere tradotto o di usare la grafia dell'annuncio, ``source``
    deve esistere davvero.
    """
    dichiarate = {_normalizza_skill(s) for s in profile.known_skills()}
    dichiarate.discard("")

    violazioni: list[Violazione] = []
    for campo, elenco in (("hard", cv.skills.hard), ("soft", cv.skills.soft)):
        for indice, skill in enumerate(elenco):
            if _normalizza_skill(skill.source) in dichiarate:
                continue
            violazioni.append(
                Violazione(
                    "skill-non-dichiarata",
                    f"skills.{campo}[{indice}]",
                    (
                        f"{skill.text!r} dichiara di venire da {skill.source!r}, "
                        "che nel profilo non c'e'"
                        if skill.source
                        else f"{skill.text!r} non dichiara da quale competenza del profilo viene"
                    ),
                )
            )
    return violazioni


# --- interfaccia --------------------------------------------------------------


def validate(cv: TailoredCV, profile: MasterProfile) -> list[Violazione]:
    """Le affermazioni del CV che il profilo non sostiene. Vuota = si puo' stampare."""
    violazioni = [
        *_verifica_provenienza(cv, profile),
        *_verifica_cifre(cv, profile),
        *_verifica_competenze(cv, profile),
    ]
    if violazioni:
        log.warning("CV respinto: %d violazioni — %s", len(violazioni), violazioni[0])
    return violazioni


def feedback(violazioni: list[Violazione]) -> str:
    """Le violazioni come istruzioni di correzione da rimandare al modello.

    Rigenerare dicendo *cosa* era sbagliato costa una chiamata come rigenerare
    alla cieca, e la spende molto meglio: senza l'elenco, il tentativo successivo
    ripete lo stesso errore, perche' niente nella richiesta e' cambiato.
    """
    righe = [
        "## CORREZIONI OBBLIGATORIE",
        "",
        "Il tentativo precedente conteneva affermazioni che il profilo non sostiene.",
        "Il documento e' stato scartato. Rigeneralo correggendo questi punti:",
        "",
    ]
    righe += [f"- {v.dove} — {v.dettaglio}" for v in violazioni]
    righe += [
        "",
        "Ricorda: se un numero non c'e' nella fonte, la frase va scritta senza numero; "
        "se una competenza non c'e' nel profilo, va tolta e non sostituita con una simile.",
    ]
    return "\n".join(righe)
