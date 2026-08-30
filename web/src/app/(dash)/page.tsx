import { FilterBar } from "@/components/filter-bar";
import { MatchTable } from "@/components/match-table";
import { Pagination } from "@/components/pagination";
import { RefreshBar } from "@/components/refresh-bar";
import { SiteHeader } from "@/components/site-header";
import { requireSession } from "@/lib/dal";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { formatAgo } from "@/lib/format";
import { getCounters, getFilterOptions, getWorkerStatus, listMatches } from "@/lib/queries";
import { getLatestTask } from "@/lib/tasks";

export const metadata = { title: { absolute: "Job Board" } };

/**
 * La dashboard.
 *
 * Server component: legge dal database direttamente, senza far fare a Next.js
 * una richiesta HTTP verso la propria API. La rotta `/api/matches` esiste
 * comunque, per il digest email della Fase 8, ma il primo caricamento non ci
 * passa — sarebbe un giro in piu' su una connessione mobile.
 *
 * Il dettaglio di un annuncio non e' qui: e' `/annuncio/<id>`, intercettata
 * dallo slot `@drawer` del layout. Aprire un annuncio non rifa' quindi le tre
 * query di questa pagina.
 */
export default async function Dashboard(props: PageProps<"/">) {
  await requireSession();

  const params = await props.searchParams;
  const filters = parseFilters(params);
  const [pagina, opzioni, contatori, worker, raccolta] = await Promise.all([
    listMatches(filters),
    getFilterOptions(),
    getCounters(),
    getWorkerStatus(),
    getLatestTask("run_pipeline"),
  ]);

  return (
    <>
      <SiteHeader
        current="annunci"
        subtitle={
          <>
            <span className="num text-foreground">{contatori.nuovi}</span> nuovi ·{" "}
            <span className="num text-foreground">{contatori.shortlist}</span> in shortlist ·{" "}
            <span className="num text-foreground">{contatori.totale}</span> valutati
          </>
        }
      />

      <main className="mx-auto w-full max-w-7xl space-y-5 px-4 py-6 sm:px-6 lg:px-8">
        <RefreshBar
          taskIniziale={raccolta}
          workerOnline={worker.online}
          ultimaRun={
            worker.minutesSinceRun === null ? null : formatAgo(worker.minutesSinceRun)
          }
        />
        <FilterBar filters={filters} options={opzioni} total={pagina.total} />
        <MatchTable items={pagina.items} />
        <Pagination
          page={pagina.page}
          pageCount={pagina.pageCount}
          total={pagina.total}
          searchParams={toSearchParams(filters)}
        />
      </main>
    </>
  );
}
