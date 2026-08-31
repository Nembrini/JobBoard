import "server-only";

import { eq } from "drizzle-orm";
import { z } from "zod";

import { getDb } from "@/db";
import { settings } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * Le preferenze del tracciamento post-candidatura (Fase 9): lette e scritte
 * dalla pagina Impostazioni, stessa riga che legge il worker
 * (``jobboard.tracking.settings``, chiave ``"tracking"``).
 *
 * ``follow_up_after_days`` resta snake_case nello schema, non
 * ``followUpAfterDays``: è la stessa chiave JSON che il worker legge e
 * scrive, lo stesso motivo per cui ``master-profile.ts`` ricalca i nomi di
 * ``schemas/profile.py`` invece di convertirli — un campo rinominato solo da
 * un lato smette di leggere quello che l'altro ha scritto.
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

const TRACKING_SETTING_KEY = "tracking";

export const trackingSettingsSchema = z.strictObject({
  enabled: z.boolean(),
  follow_up_after_days: z.number().int().min(3).max(60),
});

export type TrackingSettings = z.infer<typeof trackingSettingsSchema>;

/**
 * Prudente come le notifiche: finché nessuno lo accende da qui (o il worker
 * non ha ancora eseguito un ``check_email`` utile), nessuna connessione IMAP
 * parte da sola.
 */
export const DEFAULT_TRACKING_SETTINGS: TrackingSettings = {
  enabled: false,
  follow_up_after_days: 7,
};

export async function getTrackingSettings(): Promise<TrackingSettings> {
  await guard();

  const righe = await getDb()
    .select()
    .from(settings)
    .where(eq(settings.key, TRACKING_SETTING_KEY))
    .limit(1);
  const riga = righe[0];
  if (!riga) return DEFAULT_TRACKING_SETTINGS;

  // Un valore fuori range o malformato non deve far esplodere la pagina:
  // stesso ripiego di ``getNotificationSettings``.
  const parsed = trackingSettingsSchema.safeParse(riga.value);
  return parsed.success ? parsed.data : DEFAULT_TRACKING_SETTINGS;
}

export async function saveTrackingSettings(valori: TrackingSettings): Promise<void> {
  await guard();

  await getDb()
    .insert(settings)
    .values({
      key: TRACKING_SETTING_KEY,
      value: valori,
      description:
        "Tracciamento post-candidatura: lettura IMAP delle risposte e giorni di silenzio " +
        "prima di un promemoria, modificabili dalla pagina Impostazioni",
      updatedAt: new Date(),
    })
    .onConflictDoUpdate({
      target: settings.key,
      set: { value: valori, updatedAt: new Date() },
    });
}
