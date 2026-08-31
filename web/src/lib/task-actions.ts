"use server";

import { revalidatePath } from "next/cache";

import { requireApiSession } from "@/lib/dal";
import { enqueueTask } from "@/lib/tasks";

/**
 * Le azioni che chiedono un lavoro al worker.
 *
 * Come in `profile-actions.ts`: **una Server Action è un endpoint pubblico**, e
 * il fatto che il bottone che la invoca stia dietro il login non la protegge.
 * Sessione verificata prima di ogni scrittura.
 */

export type EsitoAvvio =
  | { ok: true; id: number; giaInCoda: boolean }
  | { ok: false; errore: string };

/**
 * Accoda una run completa: raccolta dalle fonti e poi valutazione.
 *
 * Non aspetta niente e non promette niente sui tempi. A worker acceso il task
 * parte entro mezzo minuto; a worker spento resta in coda e parte alla
 * riaccensione — che è il comportamento voluto dell'architettura split, non un
 * ripiego: l'alternativa sarebbe un bottone che a PC spento dà un errore per
 * una richiesta perfettamente valida.
 */
export async function avviaRaccolta(): Promise<EsitoAvvio> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  try {
    const { id, giaInCoda } = await enqueueTask("run_pipeline");
    // La pagina rilegge lo stato del task nel server component: senza questo,
    // il primo render dopo l'accodamento mostrerebbe ancora "nessuna run".
    revalidatePath("/");
    return { ok: true, id, giaInCoda };
  } catch (errore) {
    return {
      ok: false,
      errore: errore instanceof Error ? errore.message : "accodamento fallito",
    };
  }
}

/**
 * Accoda una run completa **con rivalutazione**: raccolta, poi matching che
 * ripassa dalla rubrica LLM anche gli annunci già arrivati allo Stadio 2, non
 * solo i nuovi.
 *
 * È il bottone "Rivaluta tutto": senza, un cambio di filtri o di profilo non
 * si vede sugli annunci già valutati finché non sono di nuovo raccolti da
 * zero, perché `run_matching` salta di default chi ha già `reached_stage >= 2`
 * (vedi `pipeline/filters.candidates` lato worker). Costa più della raccolta
 * normale — una chiamata LLM per ogni annuncio già valutato, non solo per i
 * nuovi — quindi resta un'azione a parte invece che il comportamento di
 * default di "Aggiorna adesso".
 */
export async function avviaRivalutazione(): Promise<EsitoAvvio> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  try {
    const { id, giaInCoda } = await enqueueTask("run_pipeline", { rescore: true });
    revalidatePath("/");
    return { ok: true, id, giaInCoda };
  } catch (errore) {
    return {
      ok: false,
      errore: errore instanceof Error ? errore.message : "accodamento fallito",
    };
  }
}

/**
 * Accoda un controllo della posta (Fase 9): stesso `check_email` che gira da
 * solo una volta al giorno dentro `run_pipeline`, qui su richiesta — per non
 * aspettare la run notturna dopo aver acceso il tracciamento, o per ricontrollare
 * subito dopo aver corretto uno stato a mano.
 */
export async function avviaControlloEmail(): Promise<EsitoAvvio> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  try {
    const { id, giaInCoda } = await enqueueTask("check_email");
    revalidatePath("/candidature");
    return { ok: true, id, giaInCoda };
  } catch (errore) {
    return {
      ok: false,
      errore: errore instanceof Error ? errore.message : "accodamento fallito",
    };
  }
}
