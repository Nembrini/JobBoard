import type { NextRequest } from "next/server";

import type { MatchStatus } from "@/db/schema";
import { unauthorized } from "@/lib/dal";
import { getMatchDetail, NotAuthorized, setMatchStatus } from "@/lib/queries";

/** Gli stati che la dashboard può assegnare.
 *
 *  `applied` non è nell'elenco di proposito: quello lo scrive il worker quando
 *  una candidatura parte davvero (Fase 7). Lasciarlo impostare da qui
 *  permetterebbe a un click di dichiarare inviata una candidatura che non
 *  esiste, e la tabella smetterebbe di dire la verità. */
const ASSEGNABILI: MatchStatus[] = ["new", "seen", "shortlist", "hidden"];

export async function GET(_request: NextRequest, ctx: RouteContext<"/api/matches/[id]">) {
  const { id } = await ctx.params;
  const matchId = Number.parseInt(id, 10);
  if (!Number.isFinite(matchId)) {
    return Response.json({ error: "id non valido" }, { status: 400 });
  }

  try {
    const dettaglio = await getMatchDetail(matchId);
    if (!dettaglio) return Response.json({ error: "match inesistente" }, { status: 404 });
    return Response.json(dettaglio);
  } catch (error) {
    if (error instanceof NotAuthorized) return unauthorized();
    throw error;
  }
}

/** Cambia lo stato: shortlist, nascondi, segna come visto. */
export async function PATCH(request: NextRequest, ctx: RouteContext<"/api/matches/[id]">) {
  const { id } = await ctx.params;
  const matchId = Number.parseInt(id, 10);
  if (!Number.isFinite(matchId)) {
    return Response.json({ error: "id non valido" }, { status: 400 });
  }

  let corpo: unknown;
  try {
    corpo = await request.json();
  } catch {
    return Response.json({ error: "corpo non è JSON" }, { status: 400 });
  }

  const status = (corpo as { status?: unknown })?.status;
  if (typeof status !== "string" || !ASSEGNABILI.includes(status as MatchStatus)) {
    return Response.json(
      { error: `stato non ammesso: ${ASSEGNABILI.join(", ")}` },
      { status: 400 },
    );
  }

  try {
    const aggiornato = await setMatchStatus(matchId, status as MatchStatus);
    if (!aggiornato) return Response.json({ error: "match inesistente" }, { status: 404 });
    return Response.json(aggiornato);
  } catch (error) {
    if (error instanceof NotAuthorized) return unauthorized();
    throw error;
  }
}
