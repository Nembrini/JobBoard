import "server-only";

import { and, asc, count, desc, eq, gte, inArray, isNotNull, sql } from "drizzle-orm";

import { getDb } from "@/db";
import {
  job,
  jobRequirements,
  jobSourceLink,
  match,
  source,
  workerHeartbeat,
  type MatchStatus,
  type WorkMode,
} from "@/db/schema";
import { requireApiSession } from "@/lib/dal";
import { KEPT_WHEN_HIDING_SEEN, type MatchFilters } from "@/lib/filters";

/**
 * Le query della dashboard. **Filtri, ordinamento e paginazione girano su
 * Postgres**, non in React: la tabella cresce di un centinaio di righe al
 * giorno e mandarla tutta al browser per filtrarla lì sarebbe uno spreco che
 * peggiora ogni giorno, oltre che una fuga di dati che nessuno ha chiesto.
 *
 * Ogni funzione esportata verifica la sessione prima di leggere. È ridondante
 * rispetto al proxy, ed è voluto: è la difesa che sta accanto ai dati.
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

/** Una riga della tabella. */
export type MatchListItem = {
  matchId: number;
  jobId: number;
  score: number | null;
  status: MatchStatus;
  title: string;
  company: string;
  city: string | null;
  country: string | null;
  workMode: WorkMode;
  contractType: string;
  seniority: string;
  salaryIsStated: boolean;
  salaryMin: number | null;
  salaryMax: number | null;
  salaryCurrency: string | null;
  salaryPeriod: string | null;
  jobFamily: string | null;
  url: string;
  applyUrl: string | null;
  atsType: string;
  postedAt: Date | null;
  gaps: string[];
  sources: string[];
};

export type MatchPage = {
  items: MatchListItem[];
  total: number;
  page: number;
  perPage: number;
  pageCount: number;
};

/**
 * Le fonti di ogni annuncio, come sottoquery aggregata.
 *
 * Un annuncio può arrivare da tre portali: una join normale lo duplicherebbe in
 * tre righe di tabella, che è esattamente il problema che la deduplicazione
 * della Fase 2 ha risolto a monte.
 */
const sourcesAgg = sql<string[]>`coalesce(
  (select array_agg(distinct coalesce(nullif(btrim(${jobSourceLink.publisher}), ''), ${source.adapter}))
     from ${jobSourceLink}
     join ${source} on ${source.id} = ${jobSourceLink.sourceId}
    where ${jobSourceLink.jobId} = ${job.id}),
  '{}'
)`;

/**
 * Perché `publisher` prima di `adapter`.
 *
 * Adzuna, Jooble e JSearch non pubblicano niente: ripubblicano. Scrivere
 * "jsearch" nella colonna Fonte vuol dire mostrare il nome del tubo invece di
 * quello della sorgente, e la sorgente è il dato che si guarda davvero: da
 * LinkedIn ci si candida in un modo, da una board Greenhouse in un altro. Le
 * fonti che pubblicano in proprio non hanno publisher, e lì resta il nome
 * dell'adapter, che è quello giusto.
 */

function whereFor(filters: MatchFilters) {
  const conditions = [
    // Solo gli annunci che hanno superato i filtri duri: quelli fermi allo
    // Stadio 0 restano in tabella per la calibrazione, non per essere mostrati.
    gte(match.reachedStage, 1),
    isNotNull(match.score),
    eq(job.isActive, true),
  ];

  if (filters.minScore > 0) conditions.push(gte(match.score, filters.minScore));
  if (filters.workModes.length) conditions.push(inArray(job.workMode, filters.workModes));
  if (filters.countries.length) conditions.push(inArray(job.country, filters.countries));
  if (filters.onlyNew) conditions.push(eq(match.status, "new"));
  if (filters.onlyShortlist) conditions.push(eq(match.status, "shortlist"));
  if (filters.hideSeen) conditions.push(inArray(match.status, KEPT_WHEN_HIDING_SEEN));

  if (filters.sources.length) {
    conditions.push(sql`exists (
      select 1 from ${jobSourceLink}
        join ${source} on ${source.id} = ${jobSourceLink.sourceId}
       where ${jobSourceLink.jobId} = ${job.id}
         and ${inArray(source.adapter, filters.sources)}
    )`);
  }

  // Filtro per portale, separato da quello per adapter perché risponde a una
  // domanda diversa: "solo LinkedIn" invece di "solo quello che passa da
  // JSearch". Le due cose coincidono finché un solo aggregatore indicizza un
  // portale, e smettono di coincidere appena ne arriva un secondo.
  if (filters.publishers.length) {
    conditions.push(sql`exists (
      select 1 from ${jobSourceLink}
       where ${jobSourceLink.jobId} = ${job.id}
         and ${inArray(jobSourceLink.publisher, filters.publishers)}
    )`);
  }

  return and(...conditions);
}

function orderFor(filters: MatchFilters) {
  switch (filters.sort) {
    case "recent":
      // `posted_at` è nullo su alcune fonti: quelle righe finiscono in fondo
      // invece di infilarsi in cima, dove Postgres le metterebbe di default.
      return [sql`${job.postedAt} desc nulls last`, desc(match.score)];
    case "salary":
      // Solo le RAL **dichiarate** ordinano: una stima non ha titolo di
      // scavalcare un annuncio che la cifra la dice davvero.
      return [sql`${job.salaryEurYearMax} desc nulls last`, desc(match.score)];
    default:
      return [sql`${match.score} desc nulls last`, sql`${job.postedAt} desc nulls last`];
  }
}

export async function listMatches(filters: MatchFilters): Promise<MatchPage> {
  await guard();

  const where = whereFor(filters);
  const offset = (filters.page - 1) * filters.perPage;

  const [rows, totals] = await Promise.all([
    getDb()
      .select({
        matchId: match.id,
        jobId: job.id,
        score: match.score,
        status: match.status,
        title: job.title,
        company: job.company,
        city: job.city,
        country: job.country,
        workMode: job.workMode,
        contractType: job.contractType,
        seniority: job.seniority,
        salaryIsStated: job.salaryIsStated,
        salaryMin: job.salaryMin,
        salaryMax: job.salaryMax,
        salaryCurrency: job.salaryCurrency,
        salaryPeriod: job.salaryPeriod,
        jobFamily: job.jobFamily,
        url: job.url,
        applyUrl: job.applyUrl,
        atsType: job.atsType,
        postedAt: job.postedAt,
        gaps: match.gaps,
        sources: sourcesAgg,
      })
      .from(match)
      .innerJoin(job, eq(job.id, match.jobId))
      .where(where)
      .orderBy(...orderFor(filters))
      .limit(filters.perPage)
      .offset(offset),
    getDb().select({ total: count() }).from(match).innerJoin(job, eq(job.id, match.jobId)).where(where),
  ]);

  const total = totals[0]?.total ?? 0;
  return {
    items: rows as MatchListItem[],
    total,
    page: filters.page,
    perPage: filters.perPage,
    pageCount: Math.max(1, Math.ceil(total / filters.perPage)),
  };
}

/** Il dettaglio completo, per il drawer. */
export async function getMatchDetail(matchId: number) {
  await guard();

  const rows = await getDb()
    .select({
      matchId: match.id,
      jobId: job.id,
      score: match.score,
      subscores: match.subscores,
      rationale: match.rationale,
      gaps: match.gaps,
      status: match.status,
      hybridScore: match.hybridScore,
      scoredAt: match.scoredAt,
      title: job.title,
      company: job.company,
      city: job.city,
      region: job.region,
      country: job.country,
      workMode: job.workMode,
      contractType: job.contractType,
      seniority: job.seniority,
      jobFamily: job.jobFamily,
      salaryIsStated: job.salaryIsStated,
      salaryMin: job.salaryMin,
      salaryMax: job.salaryMax,
      salaryCurrency: job.salaryCurrency,
      salaryPeriod: job.salaryPeriod,
      lang: job.lang,
      description: job.descriptionClean,
      url: job.url,
      applyUrl: job.applyUrl,
      atsType: job.atsType,
      postedAt: job.postedAt,
      mustHave: jobRequirements.mustHave,
      niceToHave: jobRequirements.niceToHave,
      techStack: jobRequirements.techStack,
      minYears: jobRequirements.minYearsExperience,
      languagesRequired: jobRequirements.languagesRequired,
      remotePolicy: jobRequirements.remotePolicy,
      redFlags: jobRequirements.redFlags,
      sources: sourcesAgg,
    })
    .from(match)
    .innerJoin(job, eq(job.id, match.jobId))
    .leftJoin(jobRequirements, eq(jobRequirements.jobId, job.id))
    .where(eq(match.id, matchId))
    .limit(1);

  return rows[0] ?? null;
}

export type MatchDetail = NonNullable<Awaited<ReturnType<typeof getMatchDetail>>>;

/** Cambia lo stato di un match: shortlist, nascosto, visto. */
export async function setMatchStatus(matchId: number, status: MatchStatus) {
  await guard();
  const updated = await getDb()
    .update(match)
    .set({ status, updatedAt: new Date() })
    .where(eq(match.id, matchId))
    .returning({ id: match.id, status: match.status });
  return updated[0] ?? null;
}

/**
 * I valori da mettere nei menu a tendina dei filtri.
 *
 * Ricavati dai dati e non da un elenco fisso: mostrare "Portogallo" quando non
 * c'è mai stato un annuncio portoghese è un filtro che non fa niente, e
 * dimenticare un paese nuovo è un filtro che manca.
 */
export async function getFilterOptions() {
  await guard();

  const [countries, sources, publishers] = await Promise.all([
    getDb()
      .selectDistinct({ country: job.country })
      .from(match)
      .innerJoin(job, eq(job.id, match.jobId))
      .where(and(isNotNull(job.country), isNotNull(match.score)))
      .orderBy(asc(job.country)),
    getDb()
      .selectDistinct({ adapter: source.adapter, displayName: source.displayName })
      .from(source)
      .innerJoin(jobSourceLink, eq(jobSourceLink.sourceId, source.id))
      .orderBy(asc(source.adapter)),
    // I portali più frequenti, non tutti: gli aggregatori ne riportano decine
    // con un annuncio a testa, e una barra di filtri con settanta pastiglie non
    // si legge. Chi ne ha almeno tre è un portale su cui vale la pena filtrare.
    getDb()
      .select({ publisher: jobSourceLink.publisher, n: count() })
      .from(jobSourceLink)
      .where(isNotNull(jobSourceLink.publisher))
      .groupBy(jobSourceLink.publisher)
      .having(sql`count(*) >= 3`)
      .orderBy(desc(count()))
      .limit(12),
  ]);

  return {
    countries: countries.map((r) => r.country!).filter(Boolean),
    sources,
    publishers: publishers.map((r) => r.publisher!).filter(Boolean),
  };
}

/** Conteggi per la testata: quanti nuovi, quanti in shortlist. */
export async function getCounters() {
  await guard();
  const rows = await getDb()
    .select({ status: match.status, n: count() })
    .from(match)
    .where(and(gte(match.reachedStage, 1), isNotNull(match.score)))
    .groupBy(match.status);

  const per = Object.fromEntries(rows.map((r) => [r.status, r.n])) as Record<MatchStatus, number>;
  return {
    nuovi: per.new ?? 0,
    shortlist: per.shortlist ?? 0,
    candidature: per.applied ?? 0,
    totale: rows.reduce((acc, r) => acc + r.n, 0),
  };
}

/**
 * L'ultimo battito del worker.
 *
 * È quello che alimenta l'indicatore online/offline: senza, premere "Candidati"
 * a PC spento darebbe un silenzio indistinguibile da un errore.
 */
export async function getWorkerStatus() {
  await guard();
  const rows = await getDb().select().from(workerHeartbeat).limit(1);
  const riga = rows[0];
  if (!riga) return { online: false, lastSeen: null, minutesAgo: null };

  const minuti = Math.floor((Date.now() - riga.lastSeenAt.getTime()) / 60_000);
  return {
    // Il worker batte ogni 30 secondi: due minuti di silenzio sono un margine
    // che copre un ritardo di rete senza dichiarare online un PC spento.
    online: minuti < 2,
    lastSeen: riga.lastSeenAt,
    minutesAgo: minuti,
    lastRunAt: riga.lastRunAt,
    lastRunStatus: riga.lastRunStatus,
  };
}
