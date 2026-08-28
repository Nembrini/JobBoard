import type { NextRequest } from "next/server";

import { unauthorized } from "@/lib/dal";
import { parseFilters } from "@/lib/filters";
import { listMatches, NotAuthorized } from "@/lib/queries";

/**
 * `GET /api/matches` — l'elenco filtrato, ordinato e paginato.
 *
 * La dashboard non la usa per il primo caricamento: quello lo fa un server
 * component, che legge dal database senza far fare a Next.js una richiesta HTTP
 * verso sé stesso. Questa rotta serve al drawer, al digest email della Fase 8 e
 * a qualunque client verrà dopo.
 */
export async function GET(request: NextRequest) {
  try {
    const filters = parseFilters(toRecord(request.nextUrl.searchParams));
    return Response.json(await listMatches(filters));
  } catch (error) {
    if (error instanceof NotAuthorized) return unauthorized();
    throw error;
  }
}

/**
 * `URLSearchParams` -> l'oggetto che `parseFilters` si aspetta.
 *
 * Serve `getAll`, non `entries`: quest'ultimo collassa i parametri ripetuti
 * sull'ultimo valore, e `?mode=remote&mode=hybrid` diventerebbe silenziosamente
 * "solo ibrido" — un filtro che restringe più di quanto l'utente ha chiesto,
 * senza dirlo.
 */
function toRecord(params: URLSearchParams): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const chiave of new Set(params.keys())) {
    const valori = params.getAll(chiave);
    out[chiave] = valori.length > 1 ? valori : valori[0];
  }
  return out;
}
