"""Apre il form vero, lo precompila, si ferma (Fase 7.2/7.3).

L'unico modulo della Fase 7 che parla con Playwright. Tutto quello che si
poteva testare senza un browser sta altrove — ``fields.py``,
``heuristics.py``, ``selectors.py`` — apposta perche' questo file non lo si
puo' provare in questo repository: serve uno schermo vero e un annuncio vero,
e nessuno dei due c'e' in CI. **Resta aperto**, come il resto della Fase 7 che
tocca il mondo fuori dal database: verificato a leggerlo, non a eseguirlo.

**Il browser non si chiude da solo.** Il punto di tutta la Fase 7 e' che
nessuna candidatura parte senza che tu l'abbia vista: la funzione compila,
fotografa, e lascia la finestra aperta sullo schermo per il tuo click. Se
``jb work`` gira come demone (``jb work`` senza ``--once``, il modo in cui lo
lancia Task Scheduler) il processo resta vivo e la finestra con lui; con
``--once`` il processo termina alla fine del task, e se questo si porti dietro
la finestra dipende dal sistema operativo — e' la prima cosa da verificare
quando questo modulo gira per la prima volta su una macchina vera.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .fields import FieldPlan
from .heuristics import DetectedField, FieldKind, find_resume_field, match_fields
from .selectors import KnownField

if TYPE_CHECKING:
    from playwright.sync_api import Page

log = logging.getLogger(__name__)

#: Tag HTML che possono ospitare un campo compilabile, con il tipo logico che
#: rappresentano quando non hanno un attributo ``type`` esplicito.
_INPUT_TYPE_TO_KIND: dict[str, FieldKind] = {
    "email": "email",
    "tel": "tel",
    "file": "file",
    "checkbox": "checkbox",
    "radio": "radio",
    "text": "text",
    "": "text",
}


class PrepareError(RuntimeError):
    """Il form non e' stato aperto o compilato: pagina irraggiungibile, timeout."""


@dataclass(frozen=True)
class PrepareResult:
    filled: list[str] = field(default_factory=list)
    #: Chiavi del piano che avevano un valore ma non hanno trovato un campo
    #: nel form: non e' un errore, e' quello che resta da compilare a mano.
    unmatched: list[str] = field(default_factory=list)
    resume_uploaded: bool = False
    screenshot_path: Path | None = None
    fields_on_page: int = 0


def _scan_fields(page: Page) -> list[DetectedField]:
    """Elenca i campi compilabili della pagina, con la label che li descrive.

    Gira nel browser stesso via ``page.evaluate``: risalire da un elemento
    alla sua label (``<label for>``, un ``<label>`` che lo contiene,
    ``aria-label``, ``aria-labelledby``, ``placeholder``) e' una traversata
    del DOM che ha senso fare in JavaScript, non elemento per elemento da
    Python — su un form con settanta campi la differenza si sente.
    """
    grezzi = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('input, textarea, select'))
          .map((el, i) => {
            const type = (el.getAttribute('type') || '').toLowerCase();
            if (['hidden', 'submit', 'button', 'reset'].includes(type)) return null;
            const label = el.labels && el.labels.length
              ? Array.from(el.labels).map(l => l.textContent).join(' ')
              : (el.getAttribute('aria-label')
                 || el.getAttribute('placeholder')
                 || '');
            return {
              tag: el.tagName.toLowerCase(),
              type,
              label: label.trim(),
              name: el.getAttribute('name') || '',
              id: el.id || '',
              order: i,
            };
          })
          .filter(Boolean)
        """
    )
    campi = []
    for grezzo in grezzi:
        if grezzo["tag"] == "textarea":
            kind: FieldKind = "textarea"
        elif grezzo["tag"] == "select":
            kind = "select"
        else:
            kind = _INPUT_TYPE_TO_KIND.get(grezzo["type"], "text")
        campi.append(
            DetectedField(
                kind=kind,
                label=grezzo["label"],
                name=grezzo["name"],
                element_id=grezzo["id"],
                order=grezzo["order"],
            )
        )
    return campi


def _fill(page: Page, campo: DetectedField, valore: str) -> bool:
    """Scrive un valore nel campo individuato. ``False`` se non ci e' riuscita.

    Un solo punto di fallimento non deve far cadere l'intera preparazione: un
    campo select con opzioni impreviste resta vuoto, gli altri si compilano
    lo stesso.
    """
    selettore = f"#{campo.element_id}" if campo.element_id else f"[name='{campo.name}']"
    try:
        if campo.kind in ("checkbox", "radio"):
            if valore == "true":
                page.check(selettore, timeout=3000)
            else:
                page.uncheck(selettore, timeout=3000)
        elif campo.kind == "select":
            page.select_option(selettore, label=valore, timeout=3000)
        else:
            page.fill(selettore, valore, timeout=3000)
        return True
    except Exception:
        log.warning("campo %s (%s) non compilato", selettore, campo.kind, exc_info=True)
        return False


def _fill_known(page: Page, known: tuple[KnownField, ...], plan: FieldPlan) -> set[str]:
    """Selettori dedicati del Tier A. Ritorna le chiavi logiche gia' scritte."""
    scritte: set[str] = set()
    for voce in known:
        if voce.logical_key == "resume":
            continue  # caricato a parte, serve un percorso di file non un valore
        valore = plan.values.get(voce.logical_key)
        if not valore:
            continue
        for selettore in voce.css:
            elemento = page.query_selector(selettore)
            if elemento is None:
                continue
            try:
                if voce.kind == "select":
                    page.select_option(selettore, label=valore, timeout=3000)
                else:
                    page.fill(selettore, valore, timeout=3000)
                scritte.add(voce.logical_key)
            except Exception:
                log.warning("selettore noto %s non compilabile", selettore, exc_info=True)
            break
    return scritte


def _upload_resume(page: Page, known: tuple[KnownField, ...], plan: FieldPlan) -> bool:
    if plan.resume_path is None:
        return False

    for voce in known:
        if voce.logical_key != "resume":
            continue
        for selettore in voce.css:
            elemento = page.query_selector(selettore)
            if elemento is None:
                continue
            try:
                page.set_input_files(selettore, str(plan.resume_path), timeout=5000)
                return True
            except Exception:
                log.warning("upload CV su %s fallito", selettore, exc_info=True)

    # Nessun selettore noto ha funzionato (o l'ATS non ne ha, Tier B): cerca
    # per euristica fra i campi file rimasti.
    campo = find_resume_field(_scan_fields(page))
    if campo is None:
        return False
    selettore = f"#{campo.element_id}" if campo.element_id else f"[name='{campo.name}']"
    try:
        page.set_input_files(selettore, str(plan.resume_path), timeout=5000)
        return True
    except Exception:
        log.warning("upload CV su %s (euristico) fallito", selettore, exc_info=True)
        return False


def prepare_application(
    apply_url: str,
    plan: FieldPlan,
    known: tuple[KnownField, ...],
    screenshot_path: Path,
    *,
    headless: bool = False,
) -> PrepareResult:
    """Apre ``apply_url``, compila quello che sa, fotografa, **non invia**.

    ``headless`` esiste solo per un giorno in cui questo modulo avra' un test
    che lancia davvero Playwright: nell'uso vero resta sempre ``False``, la
    finestra deve essere visibile perche' e' li' che avviene la revisione.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dipendenza dichiarata
        raise PrepareError("playwright non installato: pip install -e worker[dev]") from exc

    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        controller = sync_playwright().start()
        browser = controller.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(apply_url, wait_until="load", timeout=30000)
    except Exception as exc:
        raise PrepareError(f"apertura di {apply_url} fallita: {exc}") from exc

    try:
        scritte_note = _fill_known(page, known, plan)
        curriculum_caricato = _upload_resume(page, known, plan)

        residuo = FieldPlan(
            values={k: v for k, v in plan.values.items() if k not in scritte_note},
            booleans=plan.booleans,
        )
        rilevati = _scan_fields(page)
        azioni = match_fields(rilevati, residuo)
        scritte_euristica = {a.logical_key for a in azioni if _fill(page, a.field, a.value)}

        page.screenshot(path=str(screenshot_path), full_page=True)

        compilate = scritte_note | scritte_euristica
        mancanti = [k for k in plan.values if k not in compilate]
        risultato = PrepareResult(
            filled=sorted(compilate),
            unmatched=sorted(mancanti),
            resume_uploaded=curriculum_caricato,
            screenshot_path=screenshot_path,
            fields_on_page=len(rilevati),
        )
    except Exception as exc:
        # A differenza dell'apertura, un errore qui non chiude il browser: la
        # pagina e' comunque visibile, e vedere a che punto si e' fermata
        # aiuta piu' di una finestra chiusa e un messaggio d'errore.
        log.exception("preparazione del form fallita a meta'")
        raise PrepareError(f"compilazione fallita: {exc}") from exc

    # Nessun `browser.close()` ne' `controller.stop()`: la finestra resta
    # aperta per la revisione, vedi il docstring del modulo.
    return risultato
