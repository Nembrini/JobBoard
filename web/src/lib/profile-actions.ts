"use server";

import { revalidatePath } from "next/cache";

import { requireApiSession } from "@/lib/dal";
import { masterProfileSchema, primoErrore } from "@/lib/master-profile";
import { confirmProfile, deleteProfile, saveProfile } from "@/lib/profile";
import { removeObject } from "@/lib/storage";

/**
 * Le azioni della pagina CV.
 *
 * **Una Server Action è un endpoint pubblico**, non una funzione locale che
 * capita di chiamare dal browser: il fatto che il bottone che la invoca sia
 * dietro il login non la protegge affatto. Da qui le due righe che aprono ogni
 * azione — sessione verificata, input validato — prima di qualunque scrittura.
 *
 * L'input arriva come `unknown` di proposito: il tipo dichiarato in TypeScript
 * descrive quello che il *nostro* codice manda, non quello che può arrivare.
 */

export type Esito = { ok: true } | { ok: false; errore: string };

export async function salvaProfilo(dati: unknown): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  const esito = masterProfileSchema.safeParse(dati);
  if (!esito.success) return { ok: false, errore: primoErrore(esito.error) };

  try {
    await saveProfile(esito.data);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "salvataggio fallito" };
  }

  // I punteggi in home dipendono da questo profilo: la cache della lista non
  // deve sopravvivere a una modifica del CV.
  revalidatePath("/cv");
  revalidatePath("/");
  return { ok: true };
}

export async function confermaProfilo(): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  try {
    await confirmProfile();
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "conferma fallita" };
  }

  revalidatePath("/cv");
  revalidatePath("/");
  return { ok: true };
}

export async function eliminaProfilo(conferma: string): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  // La conferma digitata non è teatro: cancellare il profilo ferma il matching
  // e butta via la revisione manuale del JSON, che è il passaggio più lungo di
  // tutta la configurazione. Un click solo è troppo poco per una cosa che non
  // si annulla.
  if (conferma.trim().toUpperCase() !== "ELIMINA") {
    return { ok: false, errore: "scrivi ELIMINA per confermare" };
  }

  try {
    const { storagePath } = await deleteProfile();
    if (storagePath) await removeObject(storagePath);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "eliminazione fallita" };
  }

  revalidatePath("/cv");
  revalidatePath("/");
  return { ok: true };
}
