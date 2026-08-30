import "server-only";

import { and, desc, eq, gt, inArray, or, sql } from "drizzle-orm";

import { getDb } from "@/db";
import { task, type TaskStatus, type TaskType } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * La coda vista dal lato dashboard: leggere a che punto è un lavoro, e
 * accodarne uno.
 *
 * È l'unico punto in cui la dashboard scrive in `task`, e vale la pena tenerlo
 * uno solo: la regola che impedisce di accodare due volte lo stesso lavoro non
 * è una comodità della UI — è quello che evita che due tasti premuti in fretta
 * diventino due raccolte complete, cioè il doppio delle chiamate JSearch su un
 * budget mensile di circa duecento.
 *
 * Come in `queries.ts`, la sessione si verifica **prima** di toccare i dati.
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

/**
 * Lo stato di un task come lo consuma la UI.
 *
 * Le date sono stringhe ISO e non `Date`: questa stessa forma arriva al
 * componente per due strade — dal server al primo render e da `/api/tasks` a
 * ogni giro di polling — e la seconda passa per JSON. Una forma sola per
 * entrambe, invece di due tipi che divergono al primo campo aggiunto.
 */
export type StatoTask = {
  id: number;
  tipo: TaskType;
  status: TaskStatus;
  progress: number;
  progressMessage: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
  createdAt: string;
  finishedAt: string | null;
  attempts: number;
  maxAttempts: number;
};

/**
 * Per quanto tempo un task concluso resta visibile in dashboard.
 *
 * Un "fatto" ritrovato il giorno dopo non è un'informazione, è rumore: chi apre
 * la pagina la mattina vuole gli annunci, non l'eco della run di ieri sera. Un
 * errore invece va visto — è chi lo legge a decidere se riprovare — e chi apre
 * la dashboard il giorno dopo è esattamente la persona che non l'ha letto.
 */
const MINUTI_VISIBILE: Partial<Record<TaskStatus, number>> = {
  done: 30,
  failed: 24 * 60,
  cancelled: 30,
};

const MINUTI_MASSIMI = Math.max(...Object.values(MINUTI_VISIBILE));

const APERTI: TaskStatus[] = ["pending", "running"];

/**
 * L'ultimo task di un tipo, se c'è qualcosa da dire su di lui.
 *
 * "Qualcosa da dire" è: sta aspettando, sta girando, o si è concluso da poco.
 * Negli altri casi torna `null` e la UI non mostra niente, che è la cosa giusta
 * da mostrare quando non sta succedendo niente.
 *
 * `payload` restringe a un lavoro preciso, e per alcuni tipi è indispensabile:
 * `run_pipeline` è uno solo, ma di `generate_cv` ce n'è uno per annuncio, e
 * senza filtro la pagina di un annuncio mostrerebbe l'avanzamento del CV di un
 * altro.
 */
export async function getLatestTask(
  tipo: TaskType,
  payload?: Record<string, unknown>,
): Promise<StatoTask | null> {
  await guard();

  const righe = await getDb()
    .select()
    .from(task)
    .where(
      and(
        eq(task.taskType, tipo),
        payload ? sql`${task.payload} = ${JSON.stringify(payload)}::jsonb` : undefined,
        or(
          inArray(task.status, APERTI),
          // `finished_at` e non `updated_at`: il worker tocca la riga a ogni
          // scatto della barra, e `updated_at` terrebbe quindi visibile
          // l'ultimo aggiornamento di progresso invece della fine del lavoro.
          gt(task.finishedAt, scadenza(MINUTI_MASSIMI)),
        ),
      ),
    )
    .orderBy(desc(task.createdAt))
    .limit(1);

  const riga = righe[0];
  if (!riga) return null;

  // La finestra larga sta in SQL, quella per stato qui: una sola query, e la
  // regola "un errore si vede più a lungo di un successo" resta leggibile
  // accanto alla tabella che la definisce.
  const minuti = MINUTI_VISIBILE[riga.status];
  if (minuti !== undefined && (!riga.finishedAt || riga.finishedAt < scadenza(minuti))) {
    return null;
  }

  return serializza(riga);
}

/** Lo stato di un task preciso: è quello che interroga il polling. */
export async function getTask(id: number): Promise<StatoTask | null> {
  await guard();

  const righe = await getDb().select().from(task).where(eq(task.id, id)).limit(1);
  return righe[0] ? serializza(righe[0]) : null;
}

export type EsitoAccodamento = { id: number; giaInCoda: boolean };

/**
 * Accoda un lavoro, **a meno che uno identico non stia già aspettando**.
 *
 * La deduplica sta in SQL e non in React di proposito. Il caso da coprire non è
 * il doppio click distratto — quello lo ferma già un bottone disabilitato — ma
 * i due telefoni, la scheda riaperta, il tasto premuto di nuovo perché a worker
 * spento sembra non essere successo niente. In tutti e tre i casi il browser
 * non sa cosa hanno fatto gli altri, e il database sì.
 *
 * **Identico vuol dire anche stesso payload.** Due `run_pipeline` chiedono la
 * stessa identica cosa e la seconda è sprecata; due `reparse_profile` nominano
 * due file diversi, e scartare la seconda vorrebbe dire ignorare in silenzio il
 * CV appena caricato. La regola distingue i due casi da sola, senza che chi
 * chiama debba ricordarsi di dirlo.
 */
export async function enqueueTask(
  tipo: TaskType,
  payload: Record<string, unknown> = {},
): Promise<EsitoAccodamento> {
  await guard();

  const aperti = await getDb()
    .select({ id: task.id })
    .from(task)
    .where(
      and(
        eq(task.taskType, tipo),
        inArray(task.status, APERTI),
        // Confronto fra jsonb, non fra testo: Postgres normalizza ordine delle
        // chiavi e spazi, quindi `{"a":1}` e `{ "a": 1 }` sono lo stesso payload.
        sql`${task.payload} = ${JSON.stringify(payload)}::jsonb`,
      ),
    )
    .orderBy(desc(task.createdAt))
    .limit(1);

  if (aperti[0]) return { id: aperti[0].id, giaInCoda: true };

  const create = await getDb()
    .insert(task)
    .values({ taskType: tipo, status: "pending", payload })
    .returning({ id: task.id });

  const id = create[0]?.id;
  if (id === undefined) throw new Error("il database non ha restituito il task accodato");
  return { id, giaInCoda: false };
}

function scadenza(minuti: number): Date {
  return new Date(Date.now() - minuti * 60_000);
}

function serializza(riga: typeof task.$inferSelect): StatoTask {
  return {
    id: riga.id,
    tipo: riga.taskType,
    status: riga.status,
    progress: riga.progress,
    progressMessage: riga.progressMessage,
    error: riga.error,
    // JSONB: il database non ne conosce la forma, quindi non la conosce
    // nemmeno il tipo. Chi lo legge sceglie una chiave alla volta.
    result: (riga.result as Record<string, unknown> | null) ?? null,
    createdAt: riga.createdAt.toISOString(),
    finishedAt: riga.finishedAt?.toISOString() ?? null,
    attempts: riga.attempts,
    maxAttempts: riga.maxAttempts,
  };
}
