import { USAGE_PURPOSE_LABEL, type CostSummary } from "@/lib/costs";

/**
 * Consumo token e costo stimato per scopo e modello (Fase 10.2).
 *
 * Sola lettura, come la Cronologia: qui non si cambia niente, si capisce
 * quanto sta costando la pipeline. Il costo è **"n.d." finché nessun prezzo è
 * stato impostato** con `jb costs price set` (worker) — mai una stima al
 * posto di un dato mancante, come la RAL non dichiarata in tabella.
 */
export function CostsTable({ summary }: { summary: CostSummary }) {
  if (summary.rows.length === 0) {
    return (
      <p className="text-muted-foreground rounded-xl border border-dashed p-8 text-center text-sm">
        Nessun consumo registrato negli ultimi {summary.days} giorni. Compare qui dopo la prima
        run di matching o la prima generazione di un CV.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground border-b text-left text-xs">
              <th className="px-4 py-2 font-medium">Scopo</th>
              <th className="px-4 py-2 font-medium">Modello</th>
              <th className="num px-4 py-2 text-right font-medium">Chiamate</th>
              <th className="num px-4 py-2 text-right font-medium">Token in</th>
              <th className="num px-4 py-2 text-right font-medium">Token out</th>
              <th className="num px-4 py-2 text-right font-medium">Costo stimato</th>
            </tr>
          </thead>
          <tbody>
            {summary.rows.map((riga) => (
              <tr key={`${riga.purpose}::${riga.model}`} className="border-b last:border-0">
                <td className="px-4 py-2.5">{USAGE_PURPOSE_LABEL[riga.purpose] ?? riga.purpose}</td>
                <td className="text-muted-foreground px-4 py-2.5">{riga.model}</td>
                <td className="num px-4 py-2.5 text-right">{riga.calls}</td>
                <td className="num px-4 py-2.5 text-right">{riga.inputTokens.toLocaleString("it-IT")}</td>
                <td className="num px-4 py-2.5 text-right">{riga.outputTokens.toLocaleString("it-IT")}</td>
                <td className="num px-4 py-2.5 text-right">
                  {riga.cost ? (
                    `${riga.cost.value.toFixed(4)} ${riga.cost.currency}`
                  ) : (
                    <span className="text-muted-foreground">n.d.</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {Object.keys(summary.totalsByCurrency).length > 0 ? (
        <p className="text-sm">
          Totale stimato:{" "}
          {Object.entries(summary.totalsByCurrency).map(([valuta, valore], i) => (
            <span key={valuta}>
              {i > 0 ? " · " : ""}
              <span className="num font-medium">{valore.toFixed(4)}</span> {valuta}
            </span>
          ))}
        </p>
      ) : null}

      {summary.hasUnknownCost ? (
        <p className="text-muted-foreground text-xs">
          &quot;n.d.&quot; per i modelli senza un prezzo impostato — si registra dal worker con{" "}
          <code className="rounded bg-muted px-1 py-0.5">jb costs price set</code>, letto dalla
          console del provider attivo. Come la RAL non dichiarata: mai una stima al posto di un
          dato mancante.
        </p>
      ) : null}
    </div>
  );
}
