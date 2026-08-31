import "server-only";

import { desc, eq, inArray, max, sql } from "drizzle-orm";

import { getDb } from "@/db";
import { run, source, type RunStatus } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * La cronologia delle run (Fase 8.5): sola lettura, una riga per fonte
 * raggruppata per ``batch_id`` — la stessa chiave con cui il worker lega le
 * righe di una singola esecuzione (``pipeline.ingest``).
 *
 * Si pagina per **batch**, non per riga: una run con nove fonti e una con una
 * sola devono restare due pagine leggibili allo stesso modo, non un conteggio
 * di righe che varia con quante fonti erano attive quel giorno.
 */

export class NotAuthorized extends Error {
  constructor() {
    super("non autorizzato");
  }
}

async function guard() {
  const session = await requireApiSession();
  if (!session) throw new NotAuthorized();
}

export type RunHistoryRow = {
  id: number;
  sourceAdapter: string | null;
  sourceDisplayName: string | null;
  status: RunStatus;
  startedAt: Date;
  finishedAt: Date | null;
  jobsFetched: number;
  jobsNew: number;
  jobsDuplicate: number;
  apiCalls: number;
  error: string | null;
};

export type RunBatch = {
  batchId: string;
  //  `null` solo in teoria: un batch che finisce in questo elenco ha sempre
  // almeno una riga, quindi `max(started_at)` su quel gruppo non può essere
  // vuoto. Resta nel tipo perché è quello che l'aggregato di drizzle dichiara
  // — vedi la nota sopra `maxStartedAt` in `getRunHistory`.
  startedAt: Date | null;
  rows: RunHistoryRow[];
};

export type RunHistoryPage = {
  batches: RunBatch[];
  totalBatches: number;
  page: number;
  perPage: number;
  pageCount: number;
};

const PER_PAGE = 15;

export async function getRunHistory(page = 1): Promise<RunHistoryPage> {
  await guard();
  const db = getDb();

  const [{ totale }] = await db
    .select({ totale: sql<number>`count(distinct ${run.batchId})` })
    .from(run);
  const totalBatches = Number(totale) || 0;
  const pageCount = Math.max(1, Math.ceil(totalBatches / PER_PAGE));
  const paginaValida = Math.min(Math.max(1, page), pageCount);

  // `max(run.startedAt)` invece di un `sql<Date>` grezzo: il secondo è solo
  // un'annotazione TypeScript — non passa dal decoder della colonna, quindi a
  // runtime il driver può restituire il valore com'è arrivato dal database
  // invece che come `Date`, ed `Intl.DateTimeFormat` in `dataOra` esplode con
  // "Invalid time value". L'aggregato tipizzato di drizzle segue lo stesso
  // percorso di decodifica della colonna vera.
  const maxStartedAt = max(run.startedAt);
  const batchStarts = await db
    .select({
      batchId: run.batchId,
      startedAt: maxStartedAt.as("started_at"),
    })
    .from(run)
    .groupBy(run.batchId)
    .orderBy(desc(maxStartedAt))
    .limit(PER_PAGE)
    .offset((paginaValida - 1) * PER_PAGE);

  if (batchStarts.length === 0) {
    return { batches: [], totalBatches, page: paginaValida, perPage: PER_PAGE, pageCount };
  }

  const batchIds = batchStarts.map((b) => b.batchId);
  const rows = await db
    .select({
      id: run.id,
      batchId: run.batchId,
      sourceAdapter: source.adapter,
      sourceDisplayName: source.displayName,
      status: run.status,
      startedAt: run.startedAt,
      finishedAt: run.finishedAt,
      jobsFetched: run.jobsFetched,
      jobsNew: run.jobsNew,
      jobsDuplicate: run.jobsDuplicate,
      apiCalls: run.apiCalls,
      error: run.error,
    })
    .from(run)
    .leftJoin(source, eq(source.id, run.sourceId))
    .where(inArray(run.batchId, batchIds))
    .orderBy(source.displayName);

  const perBatch = new Map<string, RunHistoryRow[]>();
  for (const { batchId, ...riga } of rows) {
    const elenco = perBatch.get(batchId) ?? [];
    elenco.push(riga);
    perBatch.set(batchId, elenco);
  }

  const batches: RunBatch[] = batchStarts.map((b) => ({
    batchId: b.batchId,
    startedAt: b.startedAt,
    rows: perBatch.get(b.batchId) ?? [],
  }));

  return { batches, totalBatches, page: paginaValida, perPage: PER_PAGE, pageCount };
}
