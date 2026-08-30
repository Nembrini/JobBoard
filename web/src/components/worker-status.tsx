import { formatAgo } from "@/lib/format";
import { getWorkerStatus } from "@/lib/queries";

/**
 * Indicatore online/offline del worker.
 *
 * È l'elemento che rende comprensibile tutta l'architettura split: la dashboard
 * è sempre raggiungibile, ma generare un CV o inviare una candidatura richiede
 * il PC di casa acceso. Senza questo pallino, premere "Candidati" a PC spento
 * darebbe un silenzio indistinguibile da un errore — e la reazione naturale
 * sarebbe premere di nuovo.
 */
export async function WorkerStatus() {
  const stato = await getWorkerStatus();

  const testo = stato.online
    ? "worker online"
    : stato.lastSeen
      ? `worker offline · ultimo contatto ${formatAgo(stato.minutesAgo)}`
      : "worker mai visto";

  return (
    <span
      className="text-muted-foreground inline-flex items-center gap-2 text-sm whitespace-nowrap"
      title={
        stato.online
          ? "Il worker è attivo: CV e candidature partono subito."
          : "Il worker non risulta attivo (nessun battito recente): i comandi restano in coda finché non riparte."
      }
    >
      <span
        aria-hidden
        className={`size-2 rounded-full ${
          stato.online ? "bg-emerald-500" : "bg-muted-foreground/40"
        }`}
      />
      {testo}
    </span>
  );
}
