import "server-only";

import { count, desc, eq, inArray, sql } from "drizzle-orm";

import { getDb } from "@/db";
import {
  application,
  applicationEvent,
  job,
  jobSourceLink,
  match,
  source,
  type ApplicationStatus,
  type ApplicationTier,
} from "@/db/schema";
import { requireApiSession } from "@/lib/dal";
import { APPLICATION_TIER_LABEL, scoreBand } from "@/lib/format";

/**
 * Tracking post-candidatura (Fase 9): la vista degli stati e le metriche di
 * risposta. Legge quello che il worker scrive in `check_email`
 * (`jobboard.handlers.run_email_check`) — questo file non calcola niente,
 * mostra e permette la correzione a mano.
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
 * Gli stati che questa pagina mostra e permette di correggere a mano.
 *
 * `draft`, `cv_ready`, `approved` e `needs_human` restano nella pagina
 * dell'annuncio: lì si decide se e come spedire una candidatura non ancora
 * partita, qui si segue cosa è successo dopo che è partita davvero.
 */
export const STATI_TRACCIATI: ApplicationStatus[] = [
  "submitted",
  "acknowledged",
  "interview",
  "rejected",
  "offer",
  "withdrawn",
];

export type CandidaturaRow = {
  applicationId: number;
  matchId: number;
  jobId: number;
  title: string;
  company: string;
  status: ApplicationStatus;
  tier: ApplicationTier;
  score: number | null;
  submittedAt: Date | null;
  followUpDueAt: Date | null;
  updatedAt: Date;
};

export type CandidaturaPage = {
  righe: CandidaturaRow[];
  totale: number;
  page: number;
  perPage: number;
  pageCount: number;
};

const PER_PAGE = 15;

export async function getCandidature(page = 1): Promise<CandidaturaPage> {
  await guard();
  const db = getDb();

  const [{ totale }] = await db
    .select({ totale: count() })
    .from(application)
    .where(inArray(application.status, STATI_TRACCIATI));
  const totaleNum = Number(totale) || 0;
  const pageCount = Math.max(1, Math.ceil(totaleNum / PER_PAGE));
  const paginaValida = Math.min(Math.max(1, page), pageCount);

  const righe = await db
    .select({
      applicationId: application.id,
      matchId: application.matchId,
      jobId: job.id,
      title: job.title,
      company: job.company,
      status: application.status,
      tier: application.tier,
      score: match.score,
      submittedAt: application.submittedAt,
      followUpDueAt: application.followUpDueAt,
      updatedAt: application.updatedAt,
    })
    .from(application)
    .innerJoin(match, eq(match.id, application.matchId))
    .innerJoin(job, eq(job.id, match.jobId))
    .where(inArray(application.status, STATI_TRACCIATI))
    // Le più aggiornate per prime: sono quelle su cui è appena successo
    // qualcosa — una mail classificata, o una correzione a mano — e sono
    // quelle che vale la pena vedere senza sfogliare.
    .orderBy(desc(application.updatedAt))
    .limit(PER_PAGE)
    .offset((paginaValida - 1) * PER_PAGE);

  return { righe, totale: totaleNum, page: paginaValida, perPage: PER_PAGE, pageCount };
}

/**
 * Corregge lo stato a mano dalla pagina Candidature (Fase 9.1).
 *
 * Scrive anche l'evento in timeline, con lo stesso `event_type` che usa il
 * classificatore del worker (`status_changed`): la cronologia di una
 * candidatura non deve distinguere "chi" ha deciso per poter essere letta,
 * solo il payload dice `manual: true`.
 *
 * Ritorna `null` se la candidatura non esiste — non solleva, perché un id
 * sparito fra il caricamento della pagina e il click non è un errore del
 * chiamante.
 */
export async function updateApplicationStatusManually(
  applicationId: number,
  nuovoStato: ApplicationStatus,
): Promise<ApplicationStatus | null> {
  await guard();

  if (!STATI_TRACCIATI.includes(nuovoStato)) {
    throw new Error(`stato non modificabile a mano: ${nuovoStato}`);
  }

  return getDb().transaction(async (tx) => {
    const righe = await tx
      .select({ status: application.status })
      .from(application)
      .where(eq(application.id, applicationId))
      .limit(1);
    const precedente = righe[0]?.status;
    if (!precedente) return null;

    const adesso = new Date();
    await tx
      .update(application)
      .set({ status: nuovoStato, updatedAt: adesso })
      .where(eq(application.id, applicationId));

    if (precedente !== nuovoStato) {
      await tx.insert(applicationEvent).values({
        applicationId,
        eventType: "status_changed",
        occurredAt: adesso,
        note: `${precedente} → ${nuovoStato}, modificato a mano dalla dashboard`,
        payload: { from: precedente, to: nuovoStato, manual: true },
      });
    }

    return nuovoStato;
  });
}

// --- metriche di risposta (Fase 9.5) ------------------------------------------------

export type MetricaRisposta = {
  etichetta: string;
  totale: number;
  risposte: number;
  /** Percentuale arrotondata, 0-100. */
  tasso: number;
};

export type MetricheRisposta = {
  perFonte: MetricaRisposta[];
  perFascia: MetricaRisposta[];
  perTier: MetricaRisposta[];
};

/**
 * Una candidatura ha "risposto" quando è uscita dal semplice "inviata": ack,
 * colloquio, rifiuto o offerta sono tutte risposte vere. `submitted` non lo
 * è ancora — è il denominatore che aspetta — e `withdrawn` non entra nel
 * calcolo affatto: un ritiro nostro non misura la reattività di un'azienda,
 * la falserebbe in entrambe le direzioni a seconda di quando è arrivato.
 */
const STATI_CON_RISPOSTA = new Set<ApplicationStatus>(["acknowledged", "interview", "rejected", "offer"]);
const STATI_PER_METRICHE: ApplicationStatus[] = ["submitted", "acknowledged", "interview", "rejected", "offer"];

type _RigaMetrica = { status: ApplicationStatus; tier: ApplicationTier; score: number | null; fonte: string };

export async function getResponseMetrics(): Promise<MetricheRisposta> {
  await guard();
  const db = getDb();

  // Lo stesso calcolo di `queries.ts::sourcesAgg` (publisher se c'è, altrimenti
  // l'adapter), ma un valore solo: qui la fonte è un'etichetta di raggruppamento,
  // non un elenco da mostrare in una cella.
  const fonteExpr = sql<string>`coalesce(
    (select coalesce(nullif(btrim(${jobSourceLink.publisher}), ''), ${source.adapter})
       from ${jobSourceLink}
       join ${source} on ${source.id} = ${jobSourceLink.sourceId}
      where ${jobSourceLink.jobId} = ${job.id}
      order by ${jobSourceLink.fetchedAt} asc
      limit 1),
    'n.d.'
  )`;

  // Il numero di candidature è piccolo — al più qualche decina al mese, con
  // il tetto giornaliero della Fase 7.5 — quindi si aggrega qui invece che con
  // tre `GROUP BY` su Postgres: una query sola, leggibile, senza il problema
  // di raggruppare per una sotto-query correlata come `fonteExpr`.
  const righe: _RigaMetrica[] = await db
    .select({ status: application.status, tier: application.tier, score: match.score, fonte: fonteExpr })
    .from(application)
    .innerJoin(match, eq(match.id, application.matchId))
    .innerJoin(job, eq(job.id, match.jobId))
    .where(inArray(application.status, STATI_PER_METRICHE));

  return {
    perFonte: aggrega(righe, (r) => r.fonte),
    perFascia: aggrega(righe, (r) => FASCIA_LABEL[scoreBand(r.score)]),
    perTier: aggrega(righe, (r) => APPLICATION_TIER_LABEL[r.tier] ?? r.tier),
  };
}

const FASCIA_LABEL: Record<string, string> = {
  alto: "Punteggio alto (≥60)",
  medio: "Punteggio medio (≥45)",
  basso: "Punteggio basso",
  assente: "n.d.",
};

function aggrega(righe: _RigaMetrica[], chiave: (r: _RigaMetrica) => string): MetricaRisposta[] {
  const gruppi = new Map<string, { totale: number; risposte: number }>();
  for (const riga of righe) {
    const k = chiave(riga);
    const g = gruppi.get(k) ?? { totale: 0, risposte: 0 };
    g.totale += 1;
    if (STATI_CON_RISPOSTA.has(riga.status)) g.risposte += 1;
    gruppi.set(k, g);
  }
  return [...gruppi.entries()]
    .map(([etichetta, g]) => ({
      etichetta,
      totale: g.totale,
      risposte: g.risposte,
      tasso: Math.round((g.risposte / g.totale) * 100),
    }))
    .sort((a, b) => b.totale - a.totale);
}
