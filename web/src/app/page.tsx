import { Suspense } from "react";

import { signOut } from "@/auth";
import { DrawerShell } from "@/components/drawer-shell";
import { FilterBar } from "@/components/filter-bar";
import { MatchDetail } from "@/components/match-detail";
import { MatchTable } from "@/components/match-table";
import { Pagination } from "@/components/pagination";
import { WorkerStatus } from "@/components/worker-status";
import { requireSession } from "@/lib/dal";
import { parseFilters, toSearchParams } from "@/lib/filters";
import { getCounters, getFilterOptions, listMatches } from "@/lib/queries";

export const metadata = { title: { absolute: "Job Board" } };

/**
 * La dashboard.
 *
 * Server component: legge dal database direttamente, senza far fare a Next.js
 * una richiesta HTTP verso la propria API. La rotta `/api/matches` esiste
 * comunque, per il drawer e per il digest email della Fase 8, ma il primo
 * caricamento non ci passa — sarebbe un giro in più su una connessione mobile.
 */
export default async function Dashboard(props: PageProps<"/">) {
  await requireSession();

  const params = await props.searchParams;
  const filters = parseFilters(params);
  const [pagina, opzioni, contatori] = await Promise.all([
    listMatches(filters),
    getFilterOptions(),
    getCounters(),
  ]);

  const aperto = Number.parseInt(
    (Array.isArray(params.open) ? params.open[0] : params.open) ?? "",
    10,
  );

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-heading text-xl font-semibold tracking-tight">Job Board</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {contatori.nuovi} nuovi · {contatori.shortlist} in shortlist ·{" "}
            {contatori.totale} valutati
          </p>
        </div>
        <div className="flex items-center gap-4">
          {/* L'heartbeat è una query in più: se è lenta non deve trattenere la
              tabella, che è il motivo per cui si apre la pagina. */}
          <Suspense fallback={<span className="text-muted-foreground text-xs">worker …</span>}>
            <WorkerStatus />
          </Suspense>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <button
              type="submit"
              className="text-muted-foreground hover:text-foreground text-xs underline-offset-4 hover:underline"
            >
              Esci
            </button>
          </form>
        </div>
      </header>

      <div className="space-y-4">
        <FilterBar filters={filters} options={opzioni} total={pagina.total} />
        <MatchTable items={pagina.items} />
        <Pagination
          page={pagina.page}
          pageCount={pagina.pageCount}
          total={pagina.total}
          searchParams={toSearchParams(filters)}
        />
      </div>

      {Number.isFinite(aperto) ? (
        <DrawerShell>
          <Suspense fallback={<div className="text-muted-foreground p-8 text-sm">Carico…</div>}>
            <MatchDetail matchId={aperto} />
          </Suspense>
        </DrawerShell>
      ) : null}
    </div>
  );
}
