import "server-only";

import { eq, gte } from "drizzle-orm";

import { getDb } from "@/db";
import { llmUsageLog, settings, type LlmUsagePurpose } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * La dashboard dei costi (Fase 10.2): sola lettura di ``llm_usage_log``, la
 * tabella che il worker riempie ad ogni run di matching, generazione CV,
 * lettura profilo e classificazione email — vedi
 * ``worker/jobboard/store/llm_usage.py``.
 *
 * **Il prezzo, quando c'è, arriva dalla riga ``settings`` `"llm_pricing"`**,
 * la stessa che `jb costs price set` scrive dal worker: qui si legge soltanto,
 * non si scrive — impostarlo resta un comando CLI, letto dalla console del
 * provider (vedi ``worker/jobboard/ai/pricing.py``). Un modello senza prezzo
 * resta a costo **"n.d.", mai una stima**: stessa regola della RAL non
 * dichiarata in ``lib/format.ts``.
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

const PRICING_SETTING_KEY = "llm_pricing";

type ModelPrice = { inputPerMillion: number; outputPerMillion: number; currency: string };

export type UsageRow = {
  purpose: LlmUsagePurpose;
  model: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  cost: { value: number; currency: string } | null;
};

export type CostSummary = {
  days: number;
  rows: UsageRow[];
  totalsByCurrency: Record<string, number>;
  /** Almeno un modello usato non ha un prezzo configurato: la UI lo spiega una volta sola. */
  hasUnknownCost: boolean;
};

export const USAGE_PURPOSE_LABEL: Record<LlmUsagePurpose, string> = {
  match_scoring: "Punteggi annunci",
  cv_structure: "Lettura CV",
  cv_tailor: "CV su misura",
  email_classify: "Classificazione risposte",
};

/**
 * Un valore scritto a mano male in ``settings`` lascia quel modello senza
 * prezzo, invece di far esplodere l'intera pagina — stesso principio di
 * ``jobboard.ai.pricing.load_pricing`` lato worker.
 */
function parsePricing(value: unknown): Record<string, ModelPrice> {
  if (!value || typeof value !== "object") return {};
  const out: Record<string, ModelPrice> = {};
  for (const [modello, dati] of Object.entries(value as Record<string, unknown>)) {
    if (!dati || typeof dati !== "object") continue;
    const d = dati as Record<string, unknown>;
    const input = Number(d.input_per_million);
    const output = Number(d.output_per_million);
    if (!Number.isFinite(input) || !Number.isFinite(output)) continue;
    out[modello] = {
      inputPerMillion: input,
      outputPerMillion: output,
      currency: typeof d.currency === "string" ? d.currency : "USD",
    };
  }
  return out;
}

export async function getCostSummary(days = 30): Promise<CostSummary> {
  await guard();
  const db = getDb();

  const da = new Date(Date.now() - days * 86_400_000);
  const [righe, prezziRiga] = await Promise.all([
    db.select().from(llmUsageLog).where(gte(llmUsageLog.occurredAt, da)),
    db.select().from(settings).where(eq(settings.key, PRICING_SETTING_KEY)).limit(1),
  ]);
  const prezzi = parsePricing(prezziRiga[0]?.value);

  const aggregati = new Map<string, UsageRow>();
  for (const riga of righe) {
    const chiave = `${riga.purpose}::${riga.model}`;
    const voce = aggregati.get(chiave) ?? {
      purpose: riga.purpose,
      model: riga.model,
      calls: 0,
      inputTokens: 0,
      outputTokens: 0,
      cost: null,
    };
    voce.calls += riga.calls;
    voce.inputTokens += riga.inputTokens;
    voce.outputTokens += riga.outputTokens;
    aggregati.set(chiave, voce);
  }

  const totalsByCurrency: Record<string, number> = {};
  let hasUnknownCost = false;
  for (const riga of aggregati.values()) {
    const prezzo = prezzi[riga.model];
    if (!prezzo) {
      hasUnknownCost = true;
      continue;
    }
    const valore =
      (riga.inputTokens / 1_000_000) * prezzo.inputPerMillion +
      (riga.outputTokens / 1_000_000) * prezzo.outputPerMillion;
    riga.cost = { value: valore, currency: prezzo.currency };
    totalsByCurrency[prezzo.currency] = (totalsByCurrency[prezzo.currency] ?? 0) + valore;
  }

  const rows = [...aggregati.values()].sort((a, b) =>
    a.purpose === b.purpose ? a.model.localeCompare(b.model) : a.purpose.localeCompare(b.purpose),
  );

  return { days, rows, totalsByCurrency, hasUnknownCost };
}
