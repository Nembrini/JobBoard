"""Router di tier (Fase 7.1): quale motore prepara la candidatura.

La decisione guarda solo l'annuncio, non l'esito passato di altre candidature:
e' il posto giusto perche' e' l'unico dato disponibile *prima* di aprire un
browser, ed e' quello che determina se aprirlo ha senso.
"""

from __future__ import annotations

from ..models import Job
from ..models.enums import TIER_A_ATS, ApplicationTier


def decide_tier(job: Job) -> ApplicationTier:
    """Tier A per un ATS noto, B per un form diretto ma sconosciuto, C altrimenti.

    ``apply_url`` e' la condizione che conta, non ``ats_type`` da solo: un
    annuncio Greenhouse senza link diretto (solo l'URL dell'aggregatore che
    l'ha pescato) non ha un form da aprire, quindi resta Tier C anche se
    l'ATS e' uno dei quattro noti. E' lo stesso criterio gia' scritto nel
    commento su ``Job.apply_url``: vince sempre il link diretto, ed e' l'unico
    che abilita la precompilazione.
    """
    if not job.apply_url:
        return ApplicationTier.C_MANUAL
    if job.ats_type in TIER_A_ATS:
        return ApplicationTier.A_AUTO
    return ApplicationTier.B_ASSISTED
