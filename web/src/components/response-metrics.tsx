import type { MetricheRisposta } from "@/lib/candidature";

/**
 * Le metriche di risposta (Fase 9.5): tasso di risposta per fonte, fascia di
 * punteggio e tier. Server component, come i badge: sono numeri già
 * aggregati da `getResponseMetrics`, non serve JavaScript per mostrarli.
 */
export function ResponseMetrics({ metriche }: { metriche: MetricheRisposta }) {
  const gruppi: [string, MetricheRisposta[keyof MetricheRisposta]][] = [
    ["Per fonte", metriche.perFonte],
    ["Per fascia di punteggio", metriche.perFascia],
    ["Per tier", metriche.perTier],
  ];

  if (gruppi.every(([, righe]) => righe.length === 0)) {
    return null;
  }

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {gruppi.map(([titolo, righe]) => (
        <div key={titolo} className="space-y-2 rounded-xl border p-4">
          <p className="text-muted-foreground text-xs font-medium uppercase">{titolo}</p>
          {righe.length === 0 ? (
            <p className="text-muted-foreground text-sm">Nessun dato ancora.</p>
          ) : (
            <ul className="space-y-1.5">
              {righe.map((riga) => (
                <li key={riga.etichetta} className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate" title={riga.etichetta}>
                    {riga.etichetta}
                  </span>
                  <span className="num text-muted-foreground shrink-0">
                    {riga.risposte}/{riga.totale} · {riga.tasso}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
