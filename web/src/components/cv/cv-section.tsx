import { CvPanel } from "@/components/cv/cv-panel";
import { getGeneratedCv, getStatoInvio } from "@/lib/applications";
import { getWorkerStatus } from "@/lib/queries";
import { signedUrl } from "@/lib/storage";
import { getLatestTask } from "@/lib/tasks";

/**
 * La metà server della sezione CV: legge, e passa al pannello.
 *
 * Sta dentro `<Suspense>` nel dettaglio dell'annuncio perché fa letture
 * multiple — candidatura, stato dell'invio, due task, battito, URL firmato —
 * e l'ultima è una chiamata di rete verso Supabase. Il dettaglio dell'annuncio
 * è la parte per cui si è aperta la pagina: non deve aspettare un URL firmato
 * per comparire.
 */
export async function CvSection({ matchId }: { matchId: number }) {
  const [cv, task, applyTask, statoInvio, worker] = await Promise.all([
    getGeneratedCv(matchId),
    // Filtrato sul payload: di `generate_cv` ce n'è uno per annuncio, e senza
    // filtro questa pagina mostrerebbe l'avanzamento del CV di un altro.
    getLatestTask("generate_cv", { match_id: matchId }),
    getLatestTask("apply", { match_id: matchId }),
    getStatoInvio(matchId),
    getWorkerStatus(),
  ]);

  // Quindici minuti invece dei cinque predefiniti: questo URL non serve a un
  // click ma a tenere aperta un'anteprima che si legge con calma, e uno scaduto
  // mostrerebbe un riquadro vuoto senza spiegare perché.
  const pdfUrl = cv?.storagePath ? await signedUrl(cv.storagePath, 900) : null;

  return (
    <CvPanel
      matchId={matchId}
      cv={cv}
      taskIniziale={task}
      applyTaskIniziale={applyTask}
      statoInvio={statoInvio}
      workerOnline={worker.online}
      pdfUrl={pdfUrl}
    />
  );
}
