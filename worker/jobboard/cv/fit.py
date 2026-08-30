"""Il loop che fa stare il CV in una pagina.

Una pagina non e' un capriccio estetico: per un profilo con meno di dieci anni di
esperienza e' la convenzione che il selezionatore si aspetta, e la seconda pagina
di un CV giovane viene letta come incapacita' di scegliere.

**L'ordine dei rimedi e' il punto.** Prima si toglie contenuto, poi si stringe
l'impaginazione — mai il contrario. Stringere e' gratis e istantaneo, ed e'
esattamente per questo che e' la tentazione sbagliata: un CV a 8pt con margini da
un centimetro sta in una pagina e non lo legge nessuno. Il contenuto di troppo va
tolto perche' e' di troppo, e la densita' e' la riserva per l'ultimo centimetro.

**Ogni compressione torna dal validatore.** Una riscrittura e' una generazione, e
una generazione puo' inventare: il CV che esce dalla terza compressione non ha
piu' nulla in comune con quello approvato alla prima. Se una compressione
introduce una violazione, si tiene la versione precedente e si passa alla
densita' — meglio un CV vero un po' stretto che uno arioso con un numero falso.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..ai.client import LLMProvider, LLMUsage
from ..ai.tailor import TailoredCV, compress
from ..ai.validator import Violazione, validate
from ..models import Job
from ..schemas import MasterProfile
from .render import DENSITA, Densita, build_html, content_pages, page_count, render_pdf

log = logging.getLogger(__name__)

#: Quante volte si chiede al modello di accorciare prima di passare alla
#: densita'. Tre e' il numero della ROADMAP, ed e' anche il punto oltre il quale
#: le compressioni smettono di convergere: se dopo tre giri il documento sfora
#: ancora, non e' lungo, e' *troppo* lungo per una pagina sola.
MAX_COMPRESSIONI = 3

#: Sotto questa soglia di sforamento non si chiama il modello: si stringe e
#: basta. Un documento che sfora del 2% perde tre righe alzando la densita' di un
#: gradino, e spendere una chiamata LLM per tre righe e' spesa senza risultato.
SFORAMENTO_TRASCURABILE = 0.06


@dataclass
class FitReport:
    """Come si e' arrivati a una pagina — o perche' non ci si e' arrivati."""

    cv: TailoredCV
    pdf: Path
    pagine: int
    #: Contenuto misurato in pagine, con la frazione: 1.05 sfora di poco.
    contenuto: float
    densita: Densita
    compressioni: int = 0
    usi: list[LLMUsage] = field(default_factory=list)
    #: Violazioni che hanno fatto scartare una compressione. Non bloccano il
    #: documento: si e' tenuta la versione buona precedente.
    compressioni_scartate: list[list[Violazione]] = field(default_factory=list)

    @property
    def riuscito(self) -> bool:
        return self.pagine <= 1

    @property
    def llm_calls(self) -> int:
        return len(self.usi)


def _stampa(
    cv: TailoredCV,
    profile: MasterProfile,
    lingua: str,
    densita: Densita,
    destinazione: Path,
) -> tuple[int, float]:
    html = build_html(cv, profile, lingua=lingua, densita=densita)
    render_pdf(html, destinazione)
    # Due misure diverse della stessa cosa, e servono entrambe: `page_count` dice
    # se il documento va bene, `content_pages` di quanto sfora — che e' cio' che
    # decide quante parole chiedere di togliere.
    pagine = page_count(destinazione)
    contenuto = content_pages(destinazione)
    log.debug("densita' %spt: %d pagine (%.2f di contenuto)", densita.punto, pagine, contenuto)
    return pagine, contenuto


def fit_to_one_page(
    provider: LLMProvider,
    cv: TailoredCV,
    profile: MasterProfile,
    job: Job,
    destinazione: Path,
    *,
    lingua: str,
    model: str | None = None,
    max_compressioni: int = MAX_COMPRESSIONI,
) -> FitReport:
    """Rende il CV e lo riduce finche' non sta in una pagina.

    Torna sempre un ``FitReport`` con un PDF sul disco, anche quando la pagina
    resta piu' di una: un CV su due pagine e' un risultato scadente ma
    utilizzabile, mentre un'eccezione a questo punto butterebbe via tutte le
    chiamate gia' spese per generarlo e validarlo.
    """
    densita = DENSITA[0]
    pagine, contenuto = _stampa(cv, profile, lingua, densita, destinazione)
    report = FitReport(cv=cv, pdf=destinazione, pagine=pagine, contenuto=contenuto, densita=densita)
    if pagine <= 1:
        return report

    # --- primo rimedio: togliere contenuto ---
    while report.compressioni < max_compressioni and report.pagine > 1:
        eccesso = (report.contenuto - 1) / report.contenuto if report.contenuto > 1 else 0.0
        if eccesso < SFORAMENTO_TRASCURABILE:
            log.info(
                "sforamento del %.0f%%: passo alla densita' senza chiamare il modello",
                eccesso * 100,
            )
            break

        risultato = compress(
            provider, report.cv, profile, job, eccesso=eccesso, lingua=lingua, model=model
        )
        report.usi.append(risultato.usage)
        report.compressioni += 1

        if violazioni := validate(risultato.value, profile):
            # La compressione ha inventato qualcosa: si scarta *lei*, non il
            # documento. Insistere con un'altra compressione partirebbe da un
            # testo gia' sporco.
            log.warning(
                "compressione %d scartata: %d violazioni (%s)",
                report.compressioni,
                len(violazioni),
                violazioni[0],
            )
            report.compressioni_scartate.append(violazioni)
            break

        pagine, contenuto = _stampa(risultato.value, profile, lingua, densita, destinazione)
        report.cv, report.pagine, report.contenuto = risultato.value, pagine, contenuto
        log.info(
            "compressione %d: %d parole, %d pagine",
            report.compressioni,
            risultato.value.word_count(),
            pagine,
        )

    # --- ultimo rimedio: stringere ---
    for gradino in DENSITA[1:]:
        if report.pagine <= 1:
            break
        pagine, contenuto = _stampa(report.cv, profile, lingua, gradino, destinazione)
        report.densita, report.pagine, report.contenuto = gradino, pagine, contenuto
        log.info("densita' ridotta a %spt: %d pagine", gradino.punto, pagine)

    if report.pagine > 1:
        # Non e' un errore: e' un CV lungo, e il PDF esiste comunque. Chi lo
        # guarda in dashboard vede quante pagine sono e decide se rigenerare.
        log.warning(
            "il CV resta su %d pagine dopo %d compressioni e densita' minima",
            report.pagine,
            report.compressioni,
        )
    else:
        # Se e' stata la densita' a salvare la situazione vale la pena saperlo:
        # se succede spesso, il MasterProfile ha piu' contenuto di quanto una
        # pagina ne regga, e la soluzione sta li' e non nel loop.
        if report.densita is not DENSITA[0]:
            log.info("una pagina raggiunta stringendo a %spt", report.densita.punto)

    return report
