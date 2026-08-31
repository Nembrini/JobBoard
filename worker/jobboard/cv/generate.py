"""Da un annuncio a un PDF: l'orchestrazione della Fase 6.

    genera  →  valida  →  (correggi e rigenera)  →  impagina in una pagina  →  carica

Un solo punto di ingresso, usato sia dal comando ``jb cv generate`` sia dal task
``generate_cv`` accodato dalla dashboard: le due strade devono produrre lo stesso
documento, e l'unico modo di esserne certi e' che eseguano lo stesso codice.

**Il validatore ha l'ultima parola.** Se dopo i tentativi previsti il CV contiene
ancora affermazioni che il profilo non sostiene, non esce nessun PDF. E' la
scelta che rende utile tutta la fase: un documento che arriva in dashboard e'
un documento che si puo' spedire, e senza questo blocco ogni CV andrebbe riletto
contro l'originale — cioe' il lavoro che il sistema doveva togliere.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..ai.client import LLMProvider, LLMUsage
from ..ai.tailor import TailoredCV, language_for, tailor
from ..ai.validator import Violazione, feedback, validate
from ..config import Settings, get_settings
from ..models import Job
from ..schemas import ApplicantInfoBank, MasterProfile
from .fit import FitReport, fit_to_one_page

log = logging.getLogger(__name__)

#: Quante volte si rigenera dopo una bocciatura del validatore. Ogni tentativo
#: riceve l'elenco degli errori precedenti, quindi il secondo e il terzo non
#: sono ripetizioni: se il modello sbaglia tre volte lo stesso punto sapendo cosa
#: ha sbagliato, il problema non e' il tentativo.
MAX_TENTATIVI = 3


class GenerationError(RuntimeError):
    """Il CV non e' stato prodotto. Il messaggio dice cosa non tornava."""


@dataclass
class GeneratedCV:
    """Il risultato completo, con quello che e' costato."""

    cv: TailoredCV
    pdf: Path
    lingua: str
    pagine: int
    #: Quante generazioni sono servite: 1 se il modello ha fatto bene al primo colpo.
    tentativi: int
    fit: FitReport
    usi: list[LLMUsage] = field(default_factory=list)
    storage_path: str | None = None
    #: Le violazioni superate lungo la strada, per capire su cosa sbaglia il
    #: modello senza dover rileggere i log.
    violazioni_corrette: list[list[Violazione]] = field(default_factory=list)

    @property
    def llm_calls(self) -> int:
        return len(self.usi)

    @property
    def input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.usi)

    @property
    def output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.usi)


def file_name(profile: MasterProfile) -> str:
    """``Filippo_Nembrini_Resume.pdf``.

    Il nome esce dal profilo invece di essere una costante: e' il nome che il
    selezionatore vede nella cartella dei candidati, e scriverlo a mano nel
    codice significa che il giorno in cui il sistema serve a un'altra persona
    manda in giro CV intestati a qualcun altro.
    """
    pezzi = re.sub(r"[^A-Za-z0-9]+", " ", _senza_accenti(profile.contact.full_name)).split()
    return f"{'_'.join(pezzi) or 'Curriculum'}_Resume.pdf"


def storage_path_for(job_id: int, profile: MasterProfile) -> str:
    """``{job_id}/Filippo_Nembrini_Resume.pdf`` dentro il bucket ``resumes``.

    Una cartella per annuncio, e dentro sempre lo stesso nome: cosi' il file che
    arriva all'azienda si chiama come deve, e due candidature non si
    sovrascrivono a vicenda.
    """
    return f"{job_id}/{file_name(profile)}"


def _senza_accenti(testo: str) -> str:
    import unicodedata

    scomposto = unicodedata.normalize("NFKD", testo)
    return "".join(c for c in scomposto if not unicodedata.combining(c))


def generate(
    provider: LLMProvider,
    profile: MasterProfile,
    job: Job,
    destinazione: Path,
    *,
    gaps: list[str] | None = None,
    lingua: str | None = None,
    applicant_info: ApplicantInfoBank | None = None,
    settings: Settings | None = None,
    max_tentativi: int = MAX_TENTATIVI,
    avanza: object = None,
) -> GeneratedCV:
    """Genera il CV su misura e lo impagina. Non carica: quello lo fa chi chiama.

    ``avanza`` e' l'eventuale callback di progresso della coda
    (``Contesto.avanza``), accettata come ``object`` per non far dipendere questo
    modulo dal modulo della coda; si usa solo se e' chiamabile.
    """
    settings = settings or get_settings()
    lingua = lingua or language_for(job)
    modello = settings.model_cv
    riporta = avanza if callable(avanza) else None

    usi: list[LLMUsage] = []
    corrette: list[list[Violazione]] = []
    correzioni: str | None = None
    cv: TailoredCV | None = None
    ultime: list[Violazione] = []

    for tentativo in range(1, max_tentativi + 1):
        if riporta:
            riporta(
                20 + (tentativo - 1) * 10,
                f"scrivo il CV in {lingua} (tentativo {tentativo})",
            )
        risultato = tailor(
            provider,
            profile,
            job,
            lingua=lingua,
            gaps=gaps,
            applicant_info=applicant_info,
            model=modello,
            correzioni=correzioni,
        )
        usi.append(risultato.usage)
        cv = risultato.value

        ultime = validate(cv, profile, applicant_info)
        if not ultime:
            log.info(
                "CV generato al tentativo %d: %d bullet, %d parole",
                tentativo,
                cv.bullet_count(),
                cv.word_count(),
            )
            break

        corrette.append(ultime)
        correzioni = feedback(ultime)
        log.warning("tentativo %d respinto: %s", tentativo, "; ".join(str(v) for v in ultime[:3]))

    if cv is None or ultime:  # pragma: no branch - cv e' sempre valorizzato qui
        dettaglio = "; ".join(str(v) for v in ultime[:5]) or "nessun output dal modello"
        raise GenerationError(
            f"il CV contiene ancora affermazioni non sostenute dal profilo dopo "
            f"{max_tentativi} tentativi: {dettaglio}"
        )

    if riporta:
        riporta(60, "impagino e verifico che stia in una pagina")

    fit = fit_to_one_page(
        provider,
        cv,
        profile,
        job,
        destinazione,
        lingua=lingua,
        applicant_info=applicant_info,
        model=modello,
    )
    usi.extend(fit.usi)

    return GeneratedCV(
        cv=fit.cv,
        pdf=fit.pdf,
        lingua=lingua,
        pagine=fit.pagine,
        tentativi=len(corrette) + 1,
        fit=fit,
        usi=usi,
        violazioni_corrette=corrette,
    )
