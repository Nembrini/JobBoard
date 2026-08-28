"""Lettura e scrittura delle entita' sul database.

Il resto del codice non compone query: chiede qui. Cosi' i dettagli che si
sbagliano facilmente — il vincolo di singleton sul profilo, la serializzazione
dell'embedding, il flag ``reviewed`` — stanno in un posto solo.
"""

from .profile import (
    StoredCandidate,
    StoredProfile,
    load_candidate,
    load_profile,
    mark_reviewed,
    save_candidate,
    save_profile,
)

__all__ = [
    "StoredCandidate",
    "StoredProfile",
    "load_candidate",
    "load_profile",
    "mark_reviewed",
    "save_candidate",
    "save_profile",
]
