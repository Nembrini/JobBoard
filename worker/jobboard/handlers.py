"""I gestori dei task accodati dalla dashboard.

Uno per tipo, registrati con ``@handler``. Importare questo modulo li iscrive:
lo fa :func:`jobboard.queue.serve` all'avvio, non l'import di ``queue``, cosi'
importare la coda per leggere un battito non tira dentro fastembed e il client
LLM.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from .db import session_scope
from .models.enums import TaskType
from .queue import Contesto, TaskError, handler
from .store import load_profile, save_profile
from .store.objects import download

log = logging.getLogger(__name__)


@handler(TaskType.REPARSE_PROFILE)
def reparse_profile(ctx: Contesto) -> dict[str, Any]:
    """Rilegge un CV caricato dalla dashboard e ne rifa' il profilo.

    E' la meta' locale del bottone "Sostituisci": la dashboard mette il file su
    Supabase e accoda: estrarre il testo da un PDF, farlo strutturare a un LLM e
    calcolare l'embedding sono le tre cose che su una funzione serverless non ci
    stanno, ne' come dipendenze ne' come tempo.

    **Il profilo esce ``reviewed=False``.** Un'estrazione automatica non e' una
    revisione, e il matching si rifiuta di girare su un profilo non rivisto: e'
    il guardrail della Fase 1.3, e vale anche quando a innescare l'estrazione e'
    stato un click invece di un comando. La revisione ora pero' si fa dalla
    pagina CV invece che su un file JSON.
    """
    percorso = str(ctx.payload.get("storage_path") or "")
    nome = str(ctx.payload.get("file_name") or "").strip() or "cv"
    if not percorso:
        raise TaskError("payload senza storage_path")

    # Import ritardati: fastembed carica un modello ONNX da 120 MB e il client
    # LLM legge la configurazione. Nessuna delle due cose serve a un worker che
    # sta solo scrivendo il battito.
    from .ai.embeddings import get_embedder
    from .cv import extract, structure

    suffisso = Path(nome).suffix.lower() or ".pdf"

    with tempfile.TemporaryDirectory(prefix="jobboard-cv-") as cartella:
        locale = Path(cartella) / f"cv{suffisso}"

        ctx.avanza(10, "scarico il file")
        download(percorso, locale)

        ctx.avanza(25, "estraggo il testo")
        documento = extract(locale)
        if documento.char_count < 200:
            # Un PDF fatto di immagini scansionate estrae quattro caratteri di
            # metadati. Fermarsi qui e dirlo e' molto meglio che far strutturare
            # il nulla a un LLM e salvare un profilo vuoto sopra quello buono.
            raise TaskError(
                f"dal file sono usciti solo {documento.char_count} caratteri: "
                "e' una scansione senza testo selezionabile? Serve un PDF con testo vero."
            )

        ctx.avanza(45, f"{documento.char_count} caratteri estratti, struttura in corso")
        profilo, avvisi = structure(documento)

        ctx.avanza(80, "calcolo il vettore del profilo")
        embedder = get_embedder()
        embedding = embedder.embed_profile(profilo.to_embedding_text())

        ctx.avanza(95, "salvo")
        with session_scope() as session:
            precedente = load_profile(session)
            save_profile(
                session,
                profile=profilo,
                embedding=embedding,
                embedding_model=embedder.model_name,
                reviewed=False,
                raw_text=documento.text,
                # Il nome vero del file caricato, non quello del temporaneo.
                source_file_name=nome[:255],
                source_storage_path=percorso[:512],
            )

    log.info("profilo rigenerato da %s (%d avvisi)", nome, len(avvisi))
    return {
        "file_name": nome,
        "characters": documento.char_count,
        "experiences": len(profilo.experiences),
        "bullets": sum(len(e.bullets) for e in profilo.experiences),
        "warnings": avvisi,
        "replaced": precedente is not None,
        # Detto qui perche' finisce in `task.result` e la dashboard lo mostra:
        # il matching resta fermo finche' il profilo non e' confermato.
        "next": "Rivedi il profilo nella pagina CV: il matching riparte quando e' confermato.",
    }
