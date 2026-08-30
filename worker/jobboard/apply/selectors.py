"""Selettori noti per i quattro ATS del Tier A (Fase 7.2).

**Non verificati su un form vero.** Vengono dalla struttura pubblica e
documentata delle pagine di apply di Greenhouse, Lever, Ashby e Workable — la
stessa che usano da anni gli strumenti di compilazione automatica — ma nessuno
di questi selettori e' stato provato contro un annuncio reale, perche' farlo
richiede un annuncio vero e Playwright in modalita' headful, cioe' un browser
con schermo. Restano "resta aperto" come il resto della Fase 7: verificati fino
a qui, non oltre. Ogni campo elenca piu' selettori in ordine di preferenza
apposta — un ATS che rinomina un `id` non deve far perdere anche gli altri
campi, e ``browser.py`` prova il prossimo della lista prima di arrendersi.

Un selettore che non trova nulla non e' un errore: quel campo lo prende
l'euristica di ``heuristics.py``, che scansiona quello che resta della pagina.
Il Tier A quindi non sostituisce il Tier B sulle domande fuori standard — le
usa entrambe, dedicate prima e generiche dopo.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.enums import AtsType
from .heuristics import FieldKind


@dataclass(frozen=True)
class KnownField:
    logical_key: str
    kind: FieldKind
    #: In ordine di preferenza: il primo selettore che risponde vince.
    css: tuple[str, ...]


#: Markup dell'embed pubblico (``boards.greenhouse.io/embed/job_app``): i campi
#: standard hanno id stabili da anni, perche' li usano anche i CSS dei siti
#: aziendali che personalizzano l'aspetto del form senza toccarne il JS.
GREENHOUSE: tuple[KnownField, ...] = (
    KnownField("first_name", "text", ("#first_name", "input[name='job_application[first_name]']")),
    KnownField("last_name", "text", ("#last_name", "input[name='job_application[last_name]']")),
    KnownField("email", "email", ("#email", "input[name='job_application[email]']")),
    KnownField("phone", "tel", ("#phone", "input[name='job_application[phone]']")),
    KnownField("resume", "file", ("#resume", "input[name='job_application[resume]']")),
    KnownField(
        "cover_letter", "file", ("#cover_letter", "input[name='job_application[cover_letter]']")
    ),
    KnownField("linkedin_url", "text", ("input[name*='LinkedIn' i]", "input[name*='linkedin' i]")),
    KnownField("github_url", "text", ("input[name*='GitHub' i]", "input[name*='github' i]")),
)

#: Form ospitato di Lever (``jobs.lever.co/<org>/<id>/apply``): i campi
#: standard usano ``name`` in stile HTML classico, i link social finiscono in
#: ``urls[Label]`` con la label che l'azienda ha scelto per quel campo — per
#: questo qui non c'e' un selettore fisso per LinkedIn/GitHub, e li trova
#: l'euristica.
LEVER: tuple[KnownField, ...] = (
    KnownField("full_name", "text", ("input[name='name']",)),
    KnownField("email", "email", ("input[name='email']",)),
    KnownField("phone", "tel", ("input[name='phone']",)),
    KnownField("resume", "file", ("input[name='resume']",)),
)

#: Il form embed di Ashby e' un componente React che genera markup diverso da
#: board a board: qui non ci sono selettori stabili da citare, solo il fatto
#: che il curriculum e' quasi sempre l'unico ``input[type=file]`` della
#: pagina. Tutto il resto passa dall'euristica — l'elenco esiste comunque per
#: coerenza con gli altri tre e perche' ``browser.py`` non deve distinguere
#: "nessuna voce" da "non ancora scritta".
ASHBY: tuple[KnownField, ...] = (KnownField("resume", "file", ("input[type='file']",)),)

#: Form ospitato di Workable (``apply.workable.com/<account>/j/<shortcode>``):
#: i campi standard sono sotto il prefisso ``candidate[...]``.
WORKABLE: tuple[KnownField, ...] = (
    KnownField("first_name", "text", ("input[name='candidate[firstname]']",)),
    KnownField("last_name", "text", ("input[name='candidate[lastname]']",)),
    KnownField("email", "email", ("input[name='candidate[email]']",)),
    KnownField("phone", "tel", ("input[name='candidate[phone]']",)),
    KnownField("resume", "file", ("input[name='candidate[resume]']",)),
)

BY_ATS: dict[AtsType, tuple[KnownField, ...]] = {
    AtsType.GREENHOUSE: GREENHOUSE,
    AtsType.LEVER: LEVER,
    AtsType.ASHBY: ASHBY,
    AtsType.WORKABLE: WORKABLE,
}


def known_fields(ats_type: AtsType) -> tuple[KnownField, ...]:
    """I selettori dedicati per un ATS, vuoto per tutto cio' che non e' Tier A."""
    return BY_ATS.get(ats_type, ())
