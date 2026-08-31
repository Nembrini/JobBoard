"use server";

import { revalidatePath } from "next/cache";

import type { ApplicationStatus } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";
import { STATI_TRACCIATI, updateApplicationStatusManually } from "@/lib/candidature";

/**
 * L'unica azione della pagina Candidature: correggere uno stato a mano.
 *
 * Come in `cv-actions.ts`: sessione verificata di nuovo qui, perché una
 * Server Action è un endpoint pubblico anche quando il bottone che la invoca
 * sta dietro il login.
 */

export type EsitoStato = { ok: true; status: ApplicationStatus } | { ok: false; errore: string };

export async function cambiaStatoCandidatura(
  applicationId: number,
  nuovoStato: string,
): Promise<EsitoStato> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };
  if (!Number.isInteger(applicationId) || applicationId <= 0) {
    return { ok: false, errore: "candidatura non valida" };
  }
  if (!STATI_TRACCIATI.includes(nuovoStato as ApplicationStatus)) {
    return { ok: false, errore: "stato non valido" };
  }

  try {
    const esito = await updateApplicationStatusManually(
      applicationId,
      nuovoStato as ApplicationStatus,
    );
    if (esito === null) return { ok: false, errore: "candidatura non trovata" };
    revalidatePath("/candidature");
    return { ok: true, status: esito };
  } catch (errore) {
    return {
      ok: false,
      errore: errore instanceof Error ? errore.message : "salvataggio fallito",
    };
  }
}
