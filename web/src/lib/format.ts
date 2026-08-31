import type { WorkMode } from "@/db/schema";

/** Formattazione condivisa fra tabella, card e drawer. Nessun `server-only`:
 *  serve da entrambi i lati del confine. */

/**
 * La retribuzione, **solo se l'annuncio la dichiara**.
 *
 * È la promessa fatta nel piano e vale in tutta l'applicazione: quando
 * `salaryIsStated` è falso si scrive "n.d." e basta. Il database contiene anche
 * `salary_eur_year_*`, che serve a ordinare e confrontare, e alcune fonti
 * offrono una stima algoritmica: nessuna delle due cose finisce mai in questa
 * colonna. Una cifra stimata mostrata come se fosse dichiarata rende inservibile
 * l'unico dato per cui si guarda quella colonna.
 */
export function formatSalary(row: {
  salaryIsStated: boolean;
  salaryMin: number | null;
  salaryMax: number | null;
  salaryCurrency: string | null;
  salaryPeriod: string | null;
}): string {
  if (!row.salaryIsStated) return "n.d.";

  const valuta = SYMBOL[row.salaryCurrency ?? ""] ?? row.salaryCurrency ?? "";
  const periodo = PERIOD[row.salaryPeriod ?? "yearly"] ?? "";
  const min = row.salaryMin;
  const max = row.salaryMax;

  if (min && max && min !== max) return `${num(min)}–${num(max)} ${valuta}${periodo}`;
  const solo = min ?? max;
  return solo ? `${num(solo)} ${valuta}${periodo}` : "n.d.";
}

const SYMBOL: Record<string, string> = { EUR: "€", GBP: "£", USD: "$", CHF: "CHF", PLN: "zł" };
const PERIOD: Record<string, string> = {
  hourly: "/h",
  daily: "/g",
  monthly: "/mese",
  yearly: "",
};

function num(value: number): string {
  return new Intl.NumberFormat("it-IT", { maximumFractionDigits: 0 }).format(value);
}

export function formatLocation(row: { city: string | null; country: string | null }): string {
  return [row.city, row.country].filter(Boolean).join(", ") || "—";
}

export const WORK_MODE_LABEL: Record<WorkMode, string> = {
  remote: "Remoto",
  hybrid: "Ibrido",
  on_site: "In sede",
  unknown: "n.d.",
};

export const CONTRACT_LABEL: Record<string, string> = {
  permanent: "Indeterminato",
  fixed_term: "Determinato",
  contract: "P. IVA",
  internship: "Stage",
  apprenticeship: "Apprendistato",
  part_time: "Part time",
  unknown: "n.d.",
};

export const SENIORITY_LABEL: Record<string, string> = {
  intern: "Stage",
  junior: "Junior",
  mid: "Mid",
  senior: "Senior",
  lead: "Lead",
  principal: "Principal",
  unknown: "n.d.",
};

/**
 * Gli stati della candidatura mostrati in `/candidature` (Fase 9.1).
 *
 * Solo i sei che la pagina rende modificabili a mano — `draft`, `cv_ready`,
 * `approved` e `needs_human` vivono nella pagina dell'annuncio, dove si decide
 * se e come spedire, non qui, dove si segue cosa è successo dopo.
 */
export const APPLICATION_STATUS_LABEL: Record<string, string> = {
  submitted: "Inviata",
  acknowledged: "In attesa",
  interview: "Colloquio",
  rejected: "Rifiutata",
  offer: "Offerta",
  withdrawn: "Ritirata",
};

export const APPLICATION_TIER_LABEL: Record<string, string> = {
  a_auto: "Selettori dedicati",
  b_assisted: "Euristica",
  c_manual: "Manuale",
};

export const RUBRIC_LABEL: Record<string, string> = {
  must_have_coverage: "Requisiti obbligatori",
  nice_to_have_coverage: "Requisiti graditi",
  seniority_fit: "Livello",
  domain_fit: "Settore",
  location_fit: "Luogo e modalità",
  salary_fit: "Retribuzione",
};

/** I pesi della rubrica, ricopiati da `worker/jobboard/ai/rubric.py`.
 *  Servono solo a mostrarli accanto ai sotto-punteggi: il calcolo del totale
 *  resta di là, dove sta anche la calibrazione. */
export const RUBRIC_WEIGHTS: Record<string, number> = {
  must_have_coverage: 0.4,
  nice_to_have_coverage: 0.1,
  seniority_fit: 0.15,
  domain_fit: 0.1,
  location_fit: 0.15,
  salary_fit: 0.1,
};

/**
 * Fascia di compatibilità.
 *
 * Le soglie sono basse di proposito rispetto a un'intuizione da "voto in
 * decimi": con vari criteri della rubrica a 50 — il valore che significa "non
 * ci sono elementi per giudicare" — un annuncio davvero buono si ferma sotto
 * 70. Colorare di rosso tutto ciò che sta sotto l'80 vorrebbe dire colorare di
 * rosso l'intera tabella.
 */
export function scoreBand(score: number | null): "alto" | "medio" | "basso" | "assente" {
  if (score === null) return "assente";
  if (score >= 60) return "alto";
  if (score >= 45) return "medio";
  return "basso";
}

/**
 * Da quanto tempo, in scala grossolana.
 *
 * Serve al battito del worker e all'ora dell'ultima raccolta: due dati che si
 * leggono per decidere se premere un bottone, non per fare i conti. "3 h fa" è
 * quello che serve sapere; il minuto esatto è precisione che non cambia nessuna
 * decisione.
 */
export function formatAgo(minuti: number | null): string {
  if (minuti === null) return "mai";
  if (minuti < 1) return "adesso";
  if (minuti < 60) return `${minuti} min fa`;
  const ore = Math.floor(minuti / 60);
  if (ore < 24) return `${ore} h fa`;
  const giorni = Math.floor(ore / 24);
  return giorni === 1 ? "ieri" : `${giorni} g fa`;
}

export function formatDate(value: Date | string | null): string {
  if (!value) return "—";
  const data = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(data.getTime())) return "—";

  const giorni = Math.floor((Date.now() - data.getTime()) / 86_400_000);
  if (giorni <= 0) return "oggi";
  if (giorni === 1) return "ieri";
  if (giorni < 30) return `${giorni} giorni fa`;
  return new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "short" }).format(data);
}

/**
 * Il nome di una fonte, come va scritto in tabella.
 *
 * Arriva o come slug di un adapter (`greenhouse`) o come publisher dichiarato
 * da un aggregatore, che è testo libero: lo stesso portale può presentarsi come
 * `LinkedIn`, `linkedin.com` o `www.linkedin.com` a seconda di chi lo riporta.
 * Tre pastiglie diverse per lo stesso sito farebbero sembrare tre fonti quello
 * che è uno. Qui si uniformano i portali riconosciuti; tutti gli altri passano
 * come sono, perché inventare una maiuscola su un dominio sconosciuto è un modo
 * silenzioso di alterare un dato.
 */
const SOURCE_LABEL: Record<string, string> = {
  linkedin: "LinkedIn",
  indeed: "Indeed",
  glassdoor: "Glassdoor",
  monster: "Monster",
  ziprecruiter: "ZipRecruiter",
  infojobs: "InfoJobs",
  stepstone: "StepStone",
  welcometothejungle: "Welcome to the Jungle",
  adzuna: "Adzuna",
  jooble: "Jooble",
  jsearch: "Google Jobs",
  arbeitnow: "Arbeitnow",
  remotive: "Remotive",
  remoteok: "RemoteOK",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
};

export function formatSource(value: string): string {
  const chiave = value
    .trim()
    .toLowerCase()
    .replace(/^www\./, "")
    .replace(/\.(com|it|de|nl|es|fr|co\.uk|org|io|jobs|careers)$/, "")
    .replace(/[^a-z0-9]/g, "");
  return SOURCE_LABEL[chiave] ?? value.trim();
}

/** Gli ATS su cui il worker precompila il form con selettori dedicati (Tier A).
 *  L'invio resta comunque sempre un click nel browser, mai automatico — nessuno
 *  dei quattro lo permette a un candidato esterno, vedi ARCHITECTURE.md §10. */
const TIER_A = new Set(["greenhouse", "lever", "ashby", "workable"]);

export function isAutoApplicable(atsType: string): boolean {
  return TIER_A.has(atsType);
}
