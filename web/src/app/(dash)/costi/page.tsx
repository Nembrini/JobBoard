import { CostsTable } from "@/components/costs-table";
import { SiteHeader } from "@/components/site-header";
import { getCostSummary } from "@/lib/costs";
import { requireSession } from "@/lib/dal";

export const metadata = { title: "Costi" };

const DEFAULT_DAYS = 30;

/**
 * Consumo token e costo stimato dei modelli LLM (Fase 10.2).
 *
 * Legge ``llm_usage_log``, che il worker riempie ad ogni run di matching,
 * generazione CV, lettura profilo e classificazione email — non un calcolo
 * nuovo, solo la lettura di quello che i gestori hanno già registrato. Il
 * prezzo per modello si imposta dal worker (`jb costs price set`), mai da
 * qui: senza un prezzo il costo resta "n.d.", come la RAL non dichiarata.
 */
export default async function CostiPage() {
  await requireSession();
  const riepilogo = await getCostSummary(DEFAULT_DAYS);

  return (
    <>
      <SiteHeader current="costi" />

      <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Costi</h1>
          <p className="text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
            Token e costo stimato dei modelli LLM, ultimi {riepilogo.days} giorni — per scopo
            (punteggi, CV, classificazione risposte) e per modello.
          </p>
        </div>

        <CostsTable summary={riepilogo} />
      </main>
    </>
  );
}
