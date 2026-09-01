import "server-only";

import { eq } from "drizzle-orm";
import { z } from "zod";

import { getDb } from "@/db";
import { settings } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";

/**
 * Gli interruttori delle tre attività di Task Scheduler create da
 * `.\setup-scheduler` — gli stessi letti da `jobboard.queue_settings` lato
 * worker, questo è il lato che li scrive.
 *
 * `.\setup-scheduler` crea "JobBoard - worker" (`jb work --once` ogni
 * minuto), "JobBoard - trigger giornaliero" (`jb work trigger --scheduled`
 * alle 07:00) e "JobBoard - backup notturno" (`jb backup run --scheduled`
 * alle 03:00). Ognuna esiste incondizionata appena creata — `schtasks` non
 * ha modo di leggere una riga di Postgres prima di agire — e ognuna di
 * queste tre righe è solo l'interruttore per fermarla dalla pagina
 * Impostazioni senza cancellare l'attività di Windows.
 *
 * **Accesi di default, tutti e tre** (a differenza di notifiche e
 * tracciamento): chi ha già eseguito `.\setup-scheduler` conta da tempo su
 * quei tick, e nascere spenti fermerebbe in silenzio un'automazione già in
 * uso al primo deploy di questo file.
 *
 * **Letti solo dal tick automatico.** `--once` legge sempre l'interruttore
 * del worker; `trigger`/`backup run` lo leggono solo se invocati con
 * `--scheduled`, il flag che passa solo l'azione di Task Scheduler — lanciati
 * a mano restano un'azione esplicita di Filippo, non soggetta all'interruttore.
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

const WORKER_SETTING_KEY = "auto_worker";
const TRIGGER_SETTING_KEY = "scheduled_trigger";
const BACKUP_SETTING_KEY = "scheduled_backup";

const toggleSchema = z.strictObject({ enabled: z.boolean() });
type ToggleSettings = z.infer<typeof toggleSchema>;

const DEFAULT_ON: ToggleSettings = { enabled: true };

/** Un valore malformato non deve far esplodere la pagina: stesso ripiego di
 *  `getNotificationSettings` e `getTrackingSettings`. */
async function getToggle(key: string): Promise<ToggleSettings> {
  const righe = await getDb().select().from(settings).where(eq(settings.key, key)).limit(1);
  const riga = righe[0];
  if (!riga) return DEFAULT_ON;

  const parsed = toggleSchema.safeParse(riga.value);
  return parsed.success ? parsed.data : DEFAULT_ON;
}

async function saveToggle(key: string, description: string, valori: ToggleSettings): Promise<void> {
  await getDb()
    .insert(settings)
    .values({ key, value: valori, description, updatedAt: new Date() })
    .onConflictDoUpdate({
      target: settings.key,
      set: { value: valori, updatedAt: new Date() },
    });
}

export const schedulerTasksSchema = z.strictObject({
  worker: z.boolean(),
  trigger: z.boolean(),
  backup: z.boolean(),
});

export type SchedulerTasksSettings = z.infer<typeof schedulerTasksSchema>;

export const DEFAULT_SCHEDULER_TASKS_SETTINGS: SchedulerTasksSettings = {
  worker: true,
  trigger: true,
  backup: true,
};

export async function getSchedulerTasksSettings(): Promise<SchedulerTasksSettings> {
  await guard();

  const [worker, trigger, backup] = await Promise.all([
    getToggle(WORKER_SETTING_KEY),
    getToggle(TRIGGER_SETTING_KEY),
    getToggle(BACKUP_SETTING_KEY),
  ]);
  return { worker: worker.enabled, trigger: trigger.enabled, backup: backup.enabled };
}

export async function saveSchedulerTasksSettings(valori: SchedulerTasksSettings): Promise<void> {
  await guard();

  await Promise.all([
    saveToggle(
      WORKER_SETTING_KEY,
      "Worker (ogni minuto): se 'JobBoard - worker' può reclamare un task dalla " +
        "coda, modificabile dalla pagina Impostazioni",
      { enabled: valori.worker },
    ),
    saveToggle(
      TRIGGER_SETTING_KEY,
      "Raccolta giornaliera (07:00): se 'JobBoard - trigger giornaliero' accoda " +
        "da solo un run_pipeline, modificabile dalla pagina Impostazioni",
      { enabled: valori.trigger },
    ),
    saveToggle(
      BACKUP_SETTING_KEY,
      "Backup notturno (03:00): se 'JobBoard - backup notturno' esporta davvero " +
        "il database, modificabile dalla pagina Impostazioni",
      { enabled: valori.backup },
    ),
  ]);
}
