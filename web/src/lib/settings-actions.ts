"use server";

import { revalidatePath } from "next/cache";

import { requireApiSession } from "@/lib/dal";
import { notificationSettingsSchema, saveNotificationSettings } from "@/lib/notifications";

/**
 * L'unica azione della pagina Impostazioni.
 *
 * Come in `profile-actions.ts`: sessione verificata e input validato prima di
 * qualunque scrittura, perché una Server Action è un endpoint pubblico anche
 * quando il bottone che la invoca sta dietro il login.
 */

export type Esito = { ok: true } | { ok: false; errore: string };

export async function salvaNotifiche(dati: unknown): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  const esito = notificationSettingsSchema.safeParse(dati);
  if (!esito.success) return { ok: false, errore: esito.error.issues[0]?.message ?? "dati non validi" };

  try {
    await saveNotificationSettings(esito.data);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "salvataggio fallito" };
  }

  revalidatePath("/impostazioni");
  return { ok: true };
}
