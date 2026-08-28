"""Pipeline di raccolta e normalizzazione degli annunci.

L'ordine dei moduli è anche l'ordine del flusso: ``normalize`` traduce quello che
arriva dagli adapter, ``dedup`` riconosce le ripetizioni, ``ingest`` orchestra e
scrive. ``text`` e ``salary`` sono utilità usate dai primi due.

**Le funzioni ``normalize()`` e ``ingest()`` non vengono riesportate qui**, anche
se sarebbe comodo: hanno lo stesso nome dei loro moduli, e
``from jobboard.pipeline import normalize`` restituirebbe la funzione a chi si
aspetta il modulo. È già costato due bug — un ``AttributeError`` in un comando
della CLI e un'intera suite di test rossa. Si importano dal loro modulo::

    from jobboard.pipeline.normalize import normalize
    from jobboard.pipeline.ingest import ingest
"""

from .dedup import JobGroup, group, merge
from .ingest import IngestReport, SourceOutcome, sync_sources
from .normalize import NormalizedJob
from .salary import Salary

__all__ = [
    "IngestReport",
    "JobGroup",
    "NormalizedJob",
    "Salary",
    "SourceOutcome",
    "group",
    "merge",
    "sync_sources",
]
