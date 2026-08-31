"use server";

import { revalidatePath } from "next/cache";

import { autoWorkerSettingsSchema, saveAutoWorkerSettings } from "@/lib/auto-worker-settings";
import { requireApiSession } from "@/lib/dal";
import { notificationSettingsSchema, saveNotificationSettings } from "@/lib/notifications";
import { saveTrackingSettings, trackingSettingsSchema } from "@/lib/tracking-settings";

/**
 * Le azioni della pagina Impostazioni, una per sezione.
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

export async function salvaTracciamento(dati: unknown): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  const esito = trackingSettingsSchema.safeParse(dati);
  if (!esito.success) return { ok: false, errore: esito.error.issues[0]?.message ?? "dati non validi" };

  try {
    await saveTrackingSettings(esito.data);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "salvataggio fallito" };
  }

  revalidatePath("/impostazioni");
  return { ok: true };
}

export async function salvaAvvioAutomatico(dati: unknown): Promise<Esito> {
  if (!(await requireApiSession())) return { ok: false, errore: "non autorizzato" };

  const esito = autoWorkerSettingsSchema.safeParse(dati);
  if (!esito.success) return { ok: false, errore: esito.error.issues[0]?.message ?? "dati non validi" };

  try {
    await saveAutoWorkerSettings(esito.data);
  } catch (errore) {
    return { ok: false, errore: errore instanceof Error ? errore.message : "salvataggio fallito" };
  }

  revalidatePath("/impostazioni");
  return { ok: true };
}
