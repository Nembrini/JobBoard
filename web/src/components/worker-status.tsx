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
          ? "Il PC di casa è acceso: CV e candidature partono subito."
          : "Il PC di casa è spento: i comandi restano in coda e partono al riavvio."
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

function formatAgo(minuti: number | null): string {
  if (minuti === null) return "mai";
  if (minuti < 60) return `${minuti} min fa`;
  const ore = Math.floor(minuti / 60);
  if (ore < 24) return `${ore} h fa`;
  return `${Math.floor(ore / 24)} g fa`;
}
