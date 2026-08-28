import type { MatchStatus, WorkMode } from "@/db/schema";

/**
 * Lettura e scrittura dei filtri, che vivono nella query string e non in uno
 * stato React.
 *
 * È una scelta, non una scorciatoia: così un elenco filtrato è un URL che si
 * può mandare al telefono, mettere fra i preferiti o ricaricare senza perdere
 * niente, e il tasto "indietro" fa quello che ci si aspetta. In cambio ogni
 * cambio di filtro è una navigazione, che con i server component costa una
 * richiesta e nessun JavaScript in più.
 *
 * I valori arrivano dalla barra degli indirizzi, quindi sono **input non
 * fidato**: qui dentro non si dà per buono niente.
 */

export const WORK_MODES = ["remote", "hybrid", "on_site", "unknown"] as const;
export const SORTS = ["score", "recent", "salary"] as const;

export type Sort = (typeof SORTS)[number];

export type MatchFilters = {
  minScore: number;
  workModes: WorkMode[];
  countries: string[];
  sources: string[];
  /** Solo quelli mai aperti. */
  onlyNew: boolean;
  /** Nasconde quelli già guardati, tenendo shortlist e candidature. */
  hideSeen: boolean;
  /** Solo la shortlist. */
  onlyShortlist: boolean;
  sort: Sort;
  page: number;
  perPage: number;
};

export const DEFAULT_FILTERS: MatchFilters = {
  minScore: 0,
  workModes: [],
  countries: [],
  sources: [],
  onlyNew: false,
  hideSeen: false,
  onlyShortlist: false,
  sort: "score",
  page: 1,
  perPage: 25,
};

/** Quanto può chiedere una singola richiesta. Un `perPage=100000` in barra
 *  indirizzi non deve poter scaricare l'intera tabella in un colpo. */
const MAX_PER_PAGE = 100;

type RawParams = Record<string, string | string[] | undefined>;

export function parseFilters(params: RawParams): MatchFilters {
  return {
    minScore: clamp(int(params.min, DEFAULT_FILTERS.minScore), 0, 100),
    workModes: pickMany(params.mode, WORK_MODES) as WorkMode[],
    // I codici paese arrivano dalla query string: si accettano solo due lettere,
    // il resto va a finire dentro una `IN (...)` e non ha motivo di esistere.
    countries: list(params.country)
      .map((c) => c.toUpperCase())
      .filter((c) => /^[A-Z]{2}$/.test(c))
      .slice(0, 20),
    sources: list(params.source)
      .filter((s) => /^[a-z0-9_-]{1,64}$/.test(s))
      .slice(0, 20),
    onlyNew: params.new === "1",
    hideSeen: params.unseen === "1",
    onlyShortlist: params.shortlist === "1",
    sort: pickOne(params.sort, SORTS, DEFAULT_FILTERS.sort),
    page: Math.max(1, int(params.page, 1)),
    perPage: clamp(int(params.per, DEFAULT_FILTERS.perPage), 5, MAX_PER_PAGE),
  };
}

/** Filtri -> query string, omettendo tutto ciò che è al valore predefinito.
 *  Un URL corto è un URL che si riesce a leggere e a condividere. */
export function toSearchParams(filters: Partial<MatchFilters>): URLSearchParams {
  const out = new URLSearchParams();
  const f = { ...DEFAULT_FILTERS, ...filters };

  if (f.minScore !== DEFAULT_FILTERS.minScore) out.set("min", String(f.minScore));
  for (const mode of f.workModes) out.append("mode", mode);
  for (const country of f.countries) out.append("country", country);
  for (const source of f.sources) out.append("source", source);
  if (f.onlyNew) out.set("new", "1");
  if (f.hideSeen) out.set("unseen", "1");
  if (f.onlyShortlist) out.set("shortlist", "1");
  if (f.sort !== DEFAULT_FILTERS.sort) out.set("sort", f.sort);
  if (f.page > 1) out.set("page", String(f.page));
  if (f.perPage !== DEFAULT_FILTERS.perPage) out.set("per", String(f.perPage));

  return out;
}

/** Quanti filtri sono attivi: serve al pallino sul bottone "Filtri" su mobile,
 *  dove il pannello è chiuso e altrimenti non si vedrebbe che sono accesi. */
export function activeFilterCount(f: MatchFilters): number {
  return (
    (f.minScore > 0 ? 1 : 0) +
    f.workModes.length +
    f.countries.length +
    f.sources.length +
    (f.onlyNew ? 1 : 0) +
    (f.hideSeen ? 1 : 0) +
    (f.onlyShortlist ? 1 : 0)
  );
}

/** Gli stati che il filtro "nascondi già visti" lascia comunque passare. */
export const KEPT_WHEN_HIDING_SEEN: MatchStatus[] = ["new", "shortlist", "applied"];

// --- utilità di lettura difensiva ------------------------------------------

function list(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) return value;
  return value ? [value] : [];
}

function int(value: string | string[] | undefined, fallback: number): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const parsed = Number.parseInt(raw ?? "", 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function pickOne<T extends string>(
  value: string | string[] | undefined,
  allowed: readonly T[],
  fallback: T,
): T {
  const raw = Array.isArray(value) ? value[0] : value;
  return allowed.includes(raw as T) ? (raw as T) : fallback;
}

function pickMany<T extends string>(
  value: string | string[] | undefined,
  allowed: readonly T[],
): T[] {
  return [...new Set(list(value).filter((v): v is T => allowed.includes(v as T)))];
}
