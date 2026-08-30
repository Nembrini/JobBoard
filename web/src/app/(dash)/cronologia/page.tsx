import Link from "next/link";

import { RunHistoryTable } from "@/components/run-history-table";
import { SiteHeader } from "@/components/site-header";
import { requireSession } from "@/lib/dal";
import { getRunHistory } from "@/lib/run-history";

export const metadata = { title: "Cronologia" };

/**
 * Run History (Fase 8.5): esiti, conteggi ed errori per fonte, una run alla
 * volta. Risponde alla domanda che il riepilogo di fine task non copre più
 * dopo trenta minuti — "cos'è successo ieri sera?" — perché quel riepilogo
 * sparisce dalla UI (`lib/tasks.ts`), questa tabella no: legge direttamente
 * la tabella `run`, popolata da ogni esecuzione, manuale o automatica.
 */
export default async function CronologiaPage(props: PageProps<"/cronologia">) {
  await requireSession();
  const { page: pageParam } = await props.searchParams;
  const page = Math.max(1, Number(pageParam) || 1);
  const storia = await getRunHistory(page);

  return (
    <>
      <SiteHeader current="cronologia" />

      <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Cronologia</h1>
          <p className="text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
            Ogni raccolta, fonte per fonte — manuale con &quot;Aggiorna adesso&quot; o automatica
            da Task Scheduler.
          </p>
        </div>

        <RunHistoryTable batches={storia.batches} />

        {storia.pageCount > 1 ? (
          <nav className="flex items-center justify-between gap-4 pt-2" aria-label="Paginazione">
            <p className="text-muted-foreground text-sm">
              Pagina <span className="num">{storia.page}</span> di{" "}
              <span className="num">{storia.pageCount}</span> ·{" "}
              <span className="num">{storia.totalBatches}</span> run
            </p>
            <div className="flex gap-2">
              {storia.page > 1 ? (
                <Link
                  href={`/cronologia?page=${storia.page - 1}`}
                  className="border-input hover:bg-accent inline-flex h-10 items-center rounded-lg border px-4 text-sm font-medium"
                >
                  Precedente
                </Link>
              ) : null}
              {storia.page < storia.pageCount ? (
                <Link
                  href={`/cronologia?page=${storia.page + 1}`}
                  className="border-input hover:bg-accent inline-flex h-10 items-center rounded-lg border px-4 text-sm font-medium"
                >
                  Successiva
                </Link>
              ) : null}
            </div>
          </nav>
        ) : null}
      </main>
    </>
  );
}
