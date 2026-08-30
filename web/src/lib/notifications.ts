import "server-only";

import { eq } from "drizzle-orm";
import { z } from "zod";

import { getDb } from "@/db";
import { settings } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * Le preferenze del digest email (Fase 8.3/8.4): lette e scritte dalla pagina
 * Impostazioni.
 *
 * Stessa riga ``settings`` che legge il worker (``jobboard.notify.settings``,
 * chiave ``"notifications"``): questo e' il lato che la scrive. Nessuna delle
 * due parti la crea di default — il worker la inizializza dai valori di
 * ``.env`` al primo ``run_pipeline`` utile, e finche' quello non e' successo
 * questa lettura restituisce semplicemente i default qui sotto, senza
 * scrivere niente: una GET non deve inserire una riga.
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

const NOTIFICATION_SETTING_KEY = "notifications";

export const notificationSettingsSchema = z.strictObject({
  enabled: z.boolean(),
  threshold: z.number().int().min(0).max(100),
  hour: z.number().int().min(0).max(23),
});

export type NotificationSettings = z.infer<typeof notificationSettingsSchema>;

/**
 * I valori di ripiego finche' nessuno ha ancora salvato una preferenza — o
 * dal worker (prima run), o da qui. Notifiche spente per prudenza, come
 * ``DRY_RUN``: un digest che parte da solo prima che qualcuno l'abbia
 * chiesto sarebbe una sorpresa, non una comodita'.
 */
export const DEFAULT_NOTIFICATION_SETTINGS: NotificationSettings = {
  enabled: false,
  threshold: 65,
  hour: 7,
};

export async function getNotificationSettings(): Promise<NotificationSettings> {
  await guard();

  const righe = await getDb()
    .select()
    .from(settings)
    .where(eq(settings.key, NOTIFICATION_SETTING_KEY))
    .limit(1);
  const riga = righe[0];
  if (!riga) return DEFAULT_NOTIFICATION_SETTINGS;

  // Un valore fuori range o malformato (scritto a mano, o da una versione
  // futura con un campo in più) non deve far esplodere la pagina: si torna
  // ai default piuttosto che mostrare un errore su una preferenza secondaria.
  const parsed = notificationSettingsSchema.safeParse(riga.value);
  return parsed.success ? parsed.data : DEFAULT_NOTIFICATION_SETTINGS;
}

export async function saveNotificationSettings(valori: NotificationSettings): Promise<void> {
  await guard();

  await getDb()
    .insert(settings)
    .values({
      key: NOTIFICATION_SETTING_KEY,
      value: valori,
      description:
        "Digest email di fine run: attivazione, soglia e orario preferito, modificabili dalla pagina Impostazioni",
      updatedAt: new Date(),
    })
    .onConflictDoUpdate({
      target: settings.key,
      set: { value: valori, updatedAt: new Date() },
    });
}
