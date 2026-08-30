"use server";

import { revalidatePath } from "next/cache";

import { approveApplication, getApplicationStatus } from "@/lib/applications";
import { requireApiSession } from "@/lib/dal";
import { enqueueTask } from "@/lib/tasks";

/**
 * Le due azioni della sezione CV di un annuncio: **Rigenera** e **Approva**.
 *
 * Come in `profile-actions.ts`, ogni azione verifica la sessione prima di
 * scrivere: una Server Action è un endpoint pubblico, e il bottone dietro il
 * login non la protegge.
 */

export type EsitoCv =
  | { ok: true; taskId: number; giaInCoda: boolean }
  | { ok: false; errore: string };

/**
 * Accoda la generazione del CV per un annuncio.
 *
 * La deduplica di `enqueueTask` conta anche il payload, quindi due click sullo
 * stesso annuncio danno un task solo, mentre due annunci diversi restano due
 * lavori distinti. È il caso che rende utile quella regola: qui il payload non
 * è vuoto.
 */
export async function generaCv(matchId: number): Promise<EsitoCv> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };
  if (!Number.isInteger(matchId) || matchId <= 0) {
    return { ok: false, errore: "annuncio non valido" };
  }

  try {
    const { id, giaInCoda } = await enqueueTask("generate_cv", { match_id: matchId });
    revalidatePath(`/annuncio/${matchId}`);
    return { ok: true, taskId: id, giaInCoda };
  } catch (errore) {
    return {
      ok: false,
      errore: errore instanceof Error ? errore.message : "accodamento fallito",
    };
  }
}

export type EsitoApprovazione = { ok: true } | { ok: false; errore: string };

/**
 * Approva il CV generato: la candidatura entra in coda per l'invio.
 *
 * **Approvare non invia niente.** L'invio è la Fase 7, con i suoi guardrail —
 * dry-run globale, cap giornaliero, conferma alla prima candidatura verso ogni
 * azienda nuova. Qui si registra solo che il documento è stato letto e va bene,
 * che è la decisione che solo una persona può prendere.
 */
export async function approvaCandidatura(matchId: number): Promise<EsitoApprovazione> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  try {
    const stato = await getApplicationStatus(matchId);
    if (stato === null) return { ok: false, errore: "non c'è ancora un CV da approvare" };
    if (stato !== "cv_ready") {
      // Rifiutare invece di riscrivere: se la candidatura è già stata inviata o
      // rifiutata, riportarla ad "approvata" nasconderebbe cos'è successo.
      return { ok: false, errore: `la candidatura è in stato "${stato}": non si approva da qui` };
    }

    await approveApplication(matchId);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "approvazione fallita" };
  }

  revalidatePath(`/annuncio/${matchId}`);
  revalidatePath("/");
  return { ok: true };
}
