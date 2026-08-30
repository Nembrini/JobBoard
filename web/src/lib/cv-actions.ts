"use server";

import { revalidatePath } from "next/cache";

import {
  approveApplication,
  getApplicationStatus,
  getStatoInvio,
  markApplicationSubmitted,
} from "@/lib/applications";
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

export type EsitoInvio =
  | { ok: true; taskId: number; giaInCoda: boolean }
  | { ok: false; errore: string; richiedeConfermaAzienda?: boolean };

/**
 * Accoda la preparazione della candidatura (Fase 7): il worker apre il
 * browser, compila il form, si ferma. **Non spedisce niente da sola** — vedi
 * il docstring di `apply_to_job` nel worker.
 *
 * `confermaNuovaAzienda` arriva dal dialogo che la UI mostra solo quando
 * `getStatoInvio` dice che questa sarebbe la prima candidatura verso
 * l'azienda dell'annuncio: senza quella conferma il worker si ferma da solo
 * e il messaggio d'errore lo dice, cosi' il chiamante sa quando riproporre il
 * dialogo invece di limitarsi a mostrare un errore generico.
 */
export async function inviaCandidatura(
  matchId: number,
  confermaNuovaAzienda = false,
): Promise<EsitoInvio> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };
  if (!Number.isInteger(matchId) || matchId <= 0) {
    return { ok: false, errore: "annuncio non valido" };
  }

  const stato = await getStatoInvio(matchId);
  if (stato === null) return { ok: false, errore: "non c'è ancora un CV approvato da inviare" };
  if (stato.status !== "approved" && stato.status !== "needs_human") {
    return { ok: false, errore: `la candidatura è in stato "${stato.status}": non si prepara da qui` };
  }
  if (stato.primaVoltaPerQuestaAzienda && !confermaNuovaAzienda) {
    return {
      ok: false,
      errore: "prima candidatura verso questa azienda: conferma per procedere",
      richiedeConfermaAzienda: true,
    };
  }

  try {
    const { id, giaInCoda } = await enqueueTask("apply", {
      match_id: matchId,
      confirmed_new_company: stato.primaVoltaPerQuestaAzienda && confermaNuovaAzienda,
    });
    revalidatePath(`/annuncio/${matchId}`);
    return { ok: true, taskId: id, giaInCoda };
  } catch (errore) {
    return {
      ok: false,
      errore: errore instanceof Error ? errore.message : "accodamento fallito",
    };
  }
}

export type EsitoConferma = { ok: true } | { ok: false; errore: string };

/**
 * Segna la candidatura come spedita, **dopo** che l'hai spedita tu premendo
 * invia nel browser che il worker ha aperto. Un click esplicito, mai un
 * effetto collaterale: vedi il docstring di `markApplicationSubmitted`.
 */
export async function segnaCandidaturaInviata(matchId: number): Promise<EsitoConferma> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  try {
    const esito = await markApplicationSubmitted(matchId);
    if (esito === null) {
      return { ok: false, errore: "la candidatura non è pronta per essere segnata come inviata" };
    }
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "operazione fallita" };
  }

  revalidatePath(`/annuncio/${matchId}`);
  revalidatePath("/");
  return { ok: true };
}
