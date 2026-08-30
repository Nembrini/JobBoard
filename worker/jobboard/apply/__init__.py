"""Candidatura (Fase 7): router di tier, precompilazione del form, guardrail.

**Il piano cambia rispetto a quanto scritto in origine in ``ROADMAP.md``.** Il
Tier A doveva inviare la candidatura con una chiamata diretta all'API pubblica
di Greenhouse/Lever/Ashby/Workable. Verificato durante l'esecuzione: nessuna
delle quattro lo permette a un candidato esterno — Greenhouse protegge il form
pubblico con reCAPTCHA Enterprise e un fingerprint minato lato client, Lever e
Workable richiedono una chiave API che solo il datore di lavoro puo' generare.
Il motivo per esteso e' in ``docs/ARCHITECTURE.md``.

Tier A e Tier B condividono quindi lo stesso motore — Playwright headful sul PC
di Filippo — e **si fermano entrambi prima del submit**. Cambia solo come si
compila il form: selettori dedicati per i quattro ATS noti (Tier A), euristica
su label e attributi per tutto il resto (Tier B). Il Tier C resta l'apertura
manuale dell'URL, per gli annunci senza un ``apply_url`` diretto.
"""

from __future__ import annotations

from .fields import FieldPlan, build_plan
from .router import decide_tier

__all__ = ["FieldPlan", "build_plan", "decide_tier"]
