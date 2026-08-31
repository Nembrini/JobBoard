"use server";

import { revalidatePath } from "next/cache";

import { applicantInfoBankSchema, primoErroreInfo } from "@/lib/applicant-info";
import { saveApplicantInfo } from "@/lib/applicant-info-store";
import { requireApiSession } from "@/lib/dal";

/**
 * Le azioni della sezione "Informazioni applicante".
 *
 * Stessa premessa di `profile-actions.ts`: una Server Action è un endpoint
 * pubblico, quindi sessione e input si verificano qui dentro a ogni chiamata,
 * non ci si fida del bottone che l'ha invocata.
 */

export type Esito = { ok: true } | { ok: false; errore: string };

export async function salvaInformazioniApplicante(dati: unknown): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  const esito = applicantInfoBankSchema.safeParse(dati);
  if (!esito.success) return { ok: false, errore: primoErroreInfo(esito.error) };

  try {
    await saveApplicantInfo(esito.data);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "salvataggio fallito" };
  }

  // La Fase 6 pesca da questo pool a ogni generazione: niente dipende da una
  // cache qui, ma la pagina CV va riletta perché mostra il pool appena salvato.
  revalidatePath("/cv");
  return { ok: true };
}
