import { formatSource } from "@/lib/format";
import type { RunBatch } from "@/lib/run-history";

/**
 * La cronologia delle run (Fase 8.5): un blocco per batch, una riga per fonte.
 *
 * Sola lettura — niente da cambiare qui, solo da capire perché una raccolta
 * ha portato meno annunci del solito o perché una fonte è ferma da giorni.
 */
export function RunHistoryTable({ batches }: { batches: RunBatch[] }) {
  if (batches.length === 0) {
    return (
      <p className="text-muted-foreground rounded-xl border border-dashed p-8 text-center text-sm">
        Nessuna run ancora registrata. Compare qui dopo la prima raccolta, manuale o
        automatica.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {batches.map((batch) => (
        <BatchCard key={batch.batchId} batch={batch} />
      ))}
    </div>
  );
}

function BatchCard({ batch }: { batch: RunBatch }) {
  const totali = batch.rows.reduce(
    (acc, r) => ({
      fetched: acc.fetched + r.jobsFetched,
      new: acc.new + r.jobsNew,
      calls: acc.calls + r.apiCalls,
    }),
    { fetched: 0, new: 0, calls: 0 },
  );
  const cadute = batch.rows.filter((r) => r.status === "failed").length;

  return (
    <div className="rounded-xl border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <div>
          <p className="font-medium">{dataOra(batch.startedAt)}</p>
          <p className="text-muted-foreground text-xs">
            <span className="num">{batch.rows.length}</span> fonti ·{" "}
            <span className="num">{totali.fetched}</span> annunci raccolti ·{" "}
            <span className="num">{totali.new}</span> nuovi ·{" "}
            <span className="num">{totali.calls}</span> chiamate API
          </p>
        </div>
        {cadute > 0 ? (
          <span className="bg-destructive/10 text-destructive rounded-full px-2.5 py-1 text-xs font-medium">
            {cadute} {cadute === 1 ? "fonte caduta" : "fonti cadute"}
          </span>
        ) : (
          <span className="rounded-full bg-emerald-500/12 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            Tutte le fonti ok
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b text-left text-xs">
              <th className="px-4 py-2 font-medium">Fonte</th>
              <th className="px-4 py-2 font-medium">Esito</th>
              <th className="num px-4 py-2 text-right font-medium">Raccolti</th>
              <th className="num px-4 py-2 text-right font-medium">Nuovi</th>
              <th className="num px-4 py-2 text-right font-medium">Duplicati</th>
              <th className="num px-4 py-2 text-right font-medium">Chiamate</th>
              <th className="px-4 py-2 font-medium">Errore</th>
            </tr>
          </thead>
          <tbody>
            {batch.rows.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                <td className="px-4 py-2.5">
                  {r.sourceDisplayName ?? (r.sourceAdapter ? formatSource(r.sourceAdapter) : "—")}
                </td>
                <td className="px-4 py-2.5">
                  <StatusPill status={r.status} />
                </td>
                <td className="num px-4 py-2.5 text-right">{r.jobsFetched}</td>
                <td className="num px-4 py-2.5 text-right">{r.jobsNew}</td>
                <td className="num px-4 py-2.5 text-right">{r.jobsDuplicate}</td>
                <td className="num px-4 py-2.5 text-right">{r.apiCalls}</td>
                <td className="text-muted-foreground max-w-xs truncate px-4 py-2.5" title={r.error ?? undefined}>
                  {r.error ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  ok: "OK",
  partial: "Parziale",
  failed: "Fallita",
  running: "In corso",
};

const STATUS_STYLE: Record<string, string> = {
  ok: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-400",
  partial: "bg-amber-500/12 text-amber-700 dark:text-amber-500",
  failed: "bg-destructive/10 text-destructive",
  running: "bg-sky-500/12 text-sky-700 dark:text-sky-400",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex h-6 items-center rounded-full px-2.5 text-xs font-medium ${STATUS_STYLE[status] ?? "bg-muted text-muted-foreground"}`}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/**
 * `value` può arrivare `null` o, in teoria, un valore che il driver non è
 * riuscito a decodificare come data: un formato che va in errore su un dato
 * imprevisto non deve far cadere un'intera pagina di sola lettura — meglio
 * un trattino di una schermata di errore.
 */
function dataOra(value: Date | null): string {
  if (!value || Number.isNaN(value.getTime())) return "—";
  return new Intl.DateTimeFormat("it-IT", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}
