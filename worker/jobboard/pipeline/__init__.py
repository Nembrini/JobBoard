"""Pipeline di raccolta, normalizzazione e matching degli annunci.

L'ordine dei moduli è anche l'ordine del flusso. Prima la raccolta:
``normalize`` traduce quello che arriva dagli adapter, ``dedup`` riconosce le
ripetizioni, ``ingest`` orchestra e scrive; ``text`` e ``salary`` sono utilità
usate dai primi due. Poi il matching: ``criteria`` decide cosa è proponibile,
``filters`` lo applica, ``bm25`` e ``rank`` ordinano a costo zero, ``match``
orchestra i tre stadi e salva i punteggi.

**Le funzioni che si chiamano come il loro modulo non vengono riesportate qui**,
anche se sarebbe comodo: ``from jobboard.pipeline import normalize``
restituirebbe la funzione a chi si aspetta il modulo. È già costato due bug — un
``AttributeError`` in un comando della CLI e un'intera suite di test rossa. Vale
per ``normalize()``, ``ingest()`` e ``rank()``, che si importano dal loro
modulo::

    from jobboard.pipeline.normalize import normalize
    from jobboard.pipeline.ingest import ingest
    from jobboard.pipeline.rank import rank
"""

from .bm25 import Bm25
from .criteria import MatchCriteria, load_criteria
from .dedup import JobGroup, group, merge
from .filters import FilterResult, Rejection, apply_filters, candidates
from .ingest import IngestReport, SourceOutcome, sync_sources
from .match import MatchingError, MatchReport, Scored, run_matching
from .normalize import NormalizedJob
from .rank import Ranked, ensure_embeddings
from .salary import Salary

__all__ = [
    "Bm25",
    "FilterResult",
    "IngestReport",
    "JobGroup",
    "MatchCriteria",
    "MatchReport",
    "MatchingError",
    "NormalizedJob",
    "Ranked",
    "Rejection",
    "Salary",
    "Scored",
    "SourceOutcome",
    "apply_filters",
    "candidates",
    "ensure_embeddings",
    "group",
    "load_criteria",
    "merge",
    "run_matching",
    "sync_sources",
]
