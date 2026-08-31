import "server-only";

import { eq } from "drizzle-orm";
import { z } from "zod";

import { getDb } from "@/db";
import { settings } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * L'interruttore dell'avvio automatico: lo stesso letto dal worker
 * (``jobboard.queue_settings``, chiave ``"auto_worker"``), questo è il lato
 * che lo scrive.
 *
 * ``.\setup-scheduler`` crea "JobBoard - worker", un'attività di Task
 * Scheduler che lancia ``jb work --once`` ogni minuto — è così che "Aggiorna
 * adesso" e "Rivaluta tutto" smettono di restare in coda finché qualcuno non
 * apre un terminale: il prossimo tick prende il task da solo, lo esegue, e il
 * processo termina — non serve nessun altro codice per "spegnerlo", ``--once``
 * esce da sé a fine lavoro. Quell'attività però esiste incondizionata appena
 * creata, e ``schtasks`` non ha modo di leggere una riga di Postgres: questa
 * preferenza è quello che il tick controlla prima di reclamare un task.
 *
 * **Acceso di default** (a differenza di notifiche e tracciamento): chi ha
 * già eseguito ``.\setup-scheduler`` conta da tempo su quel tick per la
 * raccolta di ogni mattina, e nascere spento la fermerebbe in silenzio.
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

const AUTO_WORKER_SETTING_KEY = "auto_worker";

export const autoWorkerSettingsSchema = z.strictObject({
  enabled: z.boolean(),
});

export type AutoWorkerSettings = z.infer<typeof autoWorkerSettingsSchema>;

/**
 * Acceso di default: non è un'azione nuova che va scelta per esistere, è il
 * comportamento che l'attività di Task Scheduler già creata da
 * ``.\setup-scheduler`` ha da sempre. Spegnerlo qui è quello che serve a chi
 * lo vuole fermare senza cancellare quell'attività.
 */
export const DEFAULT_AUTO_WORKER_SETTINGS: AutoWorkerSettings = {
  enabled: true,
};

export async function getAutoWorkerSettings(): Promise<AutoWorkerSettings> {
  await guard();

  const righe = await getDb()
    .select()
    .from(settings)
    .where(eq(settings.key, AUTO_WORKER_SETTING_KEY))
    .limit(1);
  const riga = righe[0];
  if (!riga) return DEFAULT_AUTO_WORKER_SETTINGS;

  // Un valore malformato non deve far esplodere la pagina: stesso ripiego
  // di ``getNotificationSettings`` e ``getTrackingSettings``.
  const parsed = autoWorkerSettingsSchema.safeParse(riga.value);
  return parsed.success ? parsed.data : DEFAULT_AUTO_WORKER_SETTINGS;
}

export async function saveAutoWorkerSettings(valori: AutoWorkerSettings): Promise<void> {
  await guard();

  await getDb()
    .insert(settings)
    .values({
      key: AUTO_WORKER_SETTING_KEY,
      value: valori,
      description:
        "Avvio automatico: se il tick di Task Scheduler ('JobBoard - worker', ogni minuto) " +
        "può reclamare un task dalla coda, modificabile dalla pagina Impostazioni",
      updatedAt: new Date(),
    })
    .onConflictDoUpdate({
      target: settings.key,
      set: { value: valori, updatedAt: new Date() },
    });
}
