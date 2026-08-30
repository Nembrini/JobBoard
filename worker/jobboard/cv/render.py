"""Da ``TailoredCV`` a PDF: composizione HTML e stampa con Playwright.

Il documento finale nasce da **due sorgenti diverse**, ed e' voluto: la prosa
viene dal modello (:mod:`jobboard.ai.tailor`), tutto il resto — nomi, date,
titoli di studio, recapiti — viene copiato dal ``MasterProfile``. Il template le
ricuce, unendo per id i bullet riscritti alle esperienze vere.

**L'ordine cronologico lo impone questo modulo**, non il modello. Le esperienze
escono dalla piu' recente alla piu' vecchia qualunque ordine abbia scelto il
modello: e' quello che si aspettano un parser ATS e chiunque legga un CV, e non
e' una decisione da lasciare a chi ha scritto la prosa.

Perche' Playwright e non una libreria HTML→PDF: e' gia' una dipendenza del
progetto (Fase 7, Tier B), produce **testo selezionabile** e non un'immagine, e
soprattutto impagina con lo stesso motore che si puo' aprire per guardare cosa
sta succedendo quando una pagina non torna.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..ai.tailor import LINGUA_PREDEFINITA, TailoredCV
from ..schemas import MasterProfile
from ..schemas.profile import Experience

if TYPE_CHECKING:
    from jinja2 import Environment

log = logging.getLogger(__name__)


class RenderError(RuntimeError):
    """Il PDF non e' stato prodotto: Playwright assente o browser non installato."""


@dataclass(frozen=True)
class Densita:
    """Quanto stretto e' impaginato il documento.

    Il loop di fit la stringe **solo dopo** aver provato a tagliare contenuto:
    un CV illeggibile che sta in una pagina ha risolto il problema sbagliato.
    L'ultimo gradino resta sopra le soglie oltre le quali un CV smette di essere
    comodo da leggere — 9.5pt e margini da 12mm sono stretti, non microscopici.
    """

    punto: float
    interlinea: float
    margine_mm: float


#: I gradini, dal piu' arioso al piu' stretto ammesso.
DENSITA: tuple[Densita, ...] = (
    Densita(punto=10.5, interlinea=1.40, margine_mm=18),
    Densita(punto=10.0, interlinea=1.28, margine_mm=15),
    Densita(punto=9.5, interlinea=1.18, margine_mm=12),
)

#: Heading canonici per lingua. Sono le etichette che i parser ATS cercano per
#: capire dove finisce una sezione e comincia l'altra: tradurle liberamente
#: ("Il mio percorso") vuol dire consegnare un documento che il parser legge come
#: un unico blocco di testo.
HEADINGS: dict[str, dict[str, str]] = {
    "it": {
        "titolo_documento": "Curriculum Vitae",
        "summary": "Profilo",
        "esperienza": "Esperienza professionale",
        "competenze": "Competenze",
        "formazione": "Formazione",
        "certificazioni": "Certificazioni",
        "lingue": "Lingue",
        "in_corso": "Presente",
    },
    "en": {
        "titolo_documento": "Resume",
        "summary": "Professional Summary",
        "esperienza": "Experience",
        "competenze": "Skills",
        "formazione": "Education",
        "certificazioni": "Certifications",
        "lingue": "Languages",
        "in_corso": "Present",
    },
    "de": {
        "titolo_documento": "Lebenslauf",
        "summary": "Profil",
        "esperienza": "Berufserfahrung",
        "competenze": "Kenntnisse",
        "formazione": "Ausbildung",
        "certificazioni": "Zertifikate",
        "lingue": "Sprachen",
        "in_corso": "Heute",
    },
    "es": {
        "titolo_documento": "Currículum",
        "summary": "Perfil",
        "esperienza": "Experiencia",
        "competenze": "Competencias",
        "formazione": "Formación",
        "certificazioni": "Certificaciones",
        "lingue": "Idiomas",
        "in_corso": "Actualidad",
    },
    "fr": {
        "titolo_documento": "CV",
        "summary": "Profil",
        "esperienza": "Expérience professionnelle",
        "competenze": "Compétences",
        "formazione": "Formation",
        "certificazioni": "Certifications",
        "lingue": "Langues",
        "in_corso": "Aujourd'hui",
    },
}

#: Come si scrive il livello di una lingua accanto al codice ISO.
_NOME_LINGUA = {
    "it": {"it": "Italiano", "en": "Inglese", "de": "Tedesco", "es": "Spagnolo", "fr": "Francese"},
    "en": {"it": "Italian", "en": "English", "de": "German", "es": "Spanish", "fr": "French"},
    "de": {
        "it": "Italienisch",
        "en": "Englisch",
        "de": "Deutsch",
        "es": "Spanisch",
        "fr": "Französisch",
    },
    "es": {"it": "Italiano", "en": "Inglés", "de": "Alemán", "es": "Español", "fr": "Francés"},
    "fr": {"it": "Italien", "en": "Anglais", "de": "Allemand", "es": "Espagnol", "fr": "Français"},
}

_MADRELINGUA = {
    "it": "madrelingua",
    "en": "native",
    "de": "Muttersprache",
    "es": "nativo",
    "fr": "langue maternelle",
}


def periodo_breve(anno_mese: str) -> str:
    """``2022-01`` diventa ``01/2022``.

    Numerico e non "Gen 2022": il mese scritto a lettere va tradotto, e un mese
    tradotto male ("Mai" in un CV francese) e' una data che il parser scarta. Il
    formato numerico non ha lingua.
    """
    if len(anno_mese) == 7 and anno_mese[4] == "-":
        return f"{anno_mese[5:]}/{anno_mese[:4]}"
    return anno_mese


def _environment() -> Environment:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        # Autoescape acceso: nel CV finiscono testi che vengono da un LLM, che a
        # sua volta ha letto una job description scaricata da internet. Un "&" in
        # un nome d'azienda non deve poter rompere il documento, e un tag non
        # deve poter arrivare fin dentro l'HTML.
        autoescape=select_autoescape(default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["periodo_breve"] = periodo_breve
    return env


@dataclass(frozen=True)
class VoceEsperienza:
    """Un'esperienza pronta da stampare: i fatti dal profilo, la prosa dal modello."""

    fonte: Experience
    periodo: str
    luogo: str | None
    bullets: list[Any]


def _esperienze(
    cv: TailoredCV, profile: MasterProfile, headings: dict[str, str]
) -> list[VoceEsperienza]:
    per_id = {e.id: e for e in profile.experiences}
    scelte = [(e, per_id[e.id]) for e in cv.experience if e.id in per_id]

    # Cronologico inverso, con "in corso" davanti a tutto: chi legge vuole sapere
    # cosa fa adesso, e l'ordine di generazione del modello non e' un'informazione.
    scelte.sort(key=lambda coppia: (coppia[1].end or "9999-99", coppia[1].start), reverse=True)

    voci = []
    for tailored, fonte in scelte:
        fine = periodo_breve(fonte.end) if fonte.end else headings["in_corso"]
        voci.append(
            VoceEsperienza(
                fonte=fonte,
                # Trattino lungo fra le date: e' la convenzione tipografica di un
                # CV, non un trattino sbagliato.
                periodo=f"{periodo_breve(fonte.start)} \u2013 {fine}",
                luogo=fonte.location,
                bullets=list(tailored.bullets),
            )
        )
    return voci


def _contatti(profile: MasterProfile) -> list[str]:
    """La riga dei recapiti, come testo puro.

    Niente icone: un pittogramma di busta non e' un indirizzo email per chi legge
    il testo estratto, ed e' quello che legge l'ATS.
    """
    contatto = profile.contact
    luogo = ", ".join(p for p in (contatto.city, contatto.country) if p)
    pezzi = [
        luogo,
        contatto.email,
        contatto.phone,
        contatto.linkedin_url,
        contatto.github_url,
        contatto.portfolio_url,
    ]
    return [p for p in pezzi if p]


def _lingue(profile: MasterProfile, lingua: str) -> list[str]:
    nomi = _NOME_LINGUA.get(lingua, _NOME_LINGUA[LINGUA_PREDEFINITA])
    fuori = _MADRELINGUA.get(lingua, _MADRELINGUA[LINGUA_PREDEFINITA])
    voci = []
    for parlata in profile.languages:
        nome = nomi.get(parlata.code.lower(), parlata.code.upper())
        livello = fuori if parlata.level == "native" else parlata.level
        voci.append(f"{nome} ({livello})")
    return voci


def build_html(
    cv: TailoredCV,
    profile: MasterProfile,
    *,
    lingua: str = LINGUA_PREDEFINITA,
    densita: Densita | None = None,
) -> str:
    """L'HTML del CV. Deterministico: stessi dati, stesso documento."""
    headings = HEADINGS.get(lingua, HEADINGS[LINGUA_PREDEFINITA])
    template = _environment().get_template("resume.html.j2")
    return template.render(
        cv=cv,
        profilo=profile,
        lingua=lingua,
        headings=headings,
        densita=densita or DENSITA[0],
        contatti=_contatti(profile),
        esperienze=_esperienze(cv, profile, headings),
        lingue=_lingue(profile, lingua),
    )


def render_pdf(html: str, destinazione: Path) -> Path:
    """Stampa l'HTML in PDF A4 con testo selezionabile."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dipendenza dichiarata
        raise RenderError("playwright non installato: pip install -e worker[dev]") from exc

    destinazione.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                pagina = browser.new_page()
                pagina.set_content(html, wait_until="load")
                pagina.pdf(
                    path=str(destinazione),
                    format="A4",
                    # I margini stanno in @page dentro il CSS, cosi' il loop di
                    # fit li cambia insieme al resto della densita' invece di
                    # doverli passare da due parti che possono divergere.
                    prefer_css_page_size=True,
                    print_background=False,
                )
            finally:
                browser.close()
    except Exception as exc:
        if isinstance(exc, RenderError):
            raise
        raise RenderError(
            f"stampa fallita: {exc}. Se dice che manca il browser: playwright install chromium"
        ) from exc

    log.info("PDF scritto in %s (%d byte)", destinazione, destinazione.stat().st_size)
    return destinazione


def page_count(pdf: Path) -> int:
    """Quante pagine ha il PDF.

    Con ``pypdfium2``, che il progetto usa gia' per leggere i CV in ingresso: una
    dipendenza in meno da giustificare, e la stessa libreria su entrambi i versi
    del percorso.
    """
    import pypdfium2 as pdfium

    documento = pdfium.PdfDocument(str(pdf))
    try:
        return len(documento)
    finally:
        documento.close()


def content_pages(pdf: Path) -> float:
    """Quanto contenuto c'e', misurato in pagine, con la frazione finale.

    Il conteggio delle pagine dice "due" sia per un CV che sfora di tre righe sia
    per uno che sfora di mezza pagina, e i due casi vogliono tagli molto diversi:
    chiedere a un modello di togliere il 50% delle parole a un documento che ne
    ha 30 di troppo restituisce un CV dimezzato, che non e' piu' quello che il
    validatore aveva approvato.

    Si misura quanto e' occupata **l'ultima** pagina, guardando dove arriva
    l'ultima riga di testo. Due pagine con l'ultima piena al 5% valgono 1.05.
    """
    import pypdfium2 as pdfium

    documento = pdfium.PdfDocument(str(pdf))
    try:
        pagine = len(documento)
        if pagine == 0:
            return 0.0

        ultima = documento[pagine - 1]
        altezza = float(ultima.get_height())
        testo = ultima.get_textpage()
        rettangoli = testo.count_rects()
        if not rettangoli or altezza <= 0:
            # Ultima pagina senza testo: il contenuto finisce con quella prima.
            return float(pagine - 1) or float(pagine)

        # L'origine del PDF e' in basso a sinistra: il testo piu' in basso ha la
        # `bottom` minima, e quanto e' occupata la pagina si misura da li' in su.
        piu_in_basso = float(min(testo.get_rect(i)[1] for i in range(rettangoli)))
        occupata = max(0.0, min(1.0, (altezza - piu_in_basso) / altezza))
        return (pagine - 1) + occupata
    finally:
        documento.close()


def extract_text(pdf: Path) -> str:
    """Il testo estraibile dal PDF, cioe' quello che vede un parser ATS.

    Serve alla verifica di fine fase: un PDF che *sembra* giusto ma da cui non
    esce testo e' un'immagine, e per un ATS e' un foglio bianco.
    """
    import pypdfium2 as pdfium

    documento = pdfium.PdfDocument(str(pdf))
    try:
        return "\n".join(
            documento[indice].get_textpage().get_text_range() for indice in range(len(documento))
        )
    finally:
        documento.close()
