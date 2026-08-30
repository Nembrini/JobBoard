import "server-only";

import { eq } from "drizzle-orm";

import { getDb } from "@/db";
import { application, type ApplicationStatus } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";
import { getProfile } from "@/lib/profile";

/**
 * Il CV su misura come lo legge la dashboard.
 *
 * Il documento lo scrive il worker (Fase 6), qui si fa una cosa sola: mostrarlo
 * in modo che si possa **decidere se spedirlo**. Da qui il diff: il PDF da solo
 * si può leggere, ma per fidarsi serve vedere accanto a ogni frase riscritta
 * quella del CV originale da cui viene. Il validatore garantisce che una fonte
 * ci sia; il diff è come si controlla, in dieci secondi invece che rileggendo
 * due documenti.
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

/** La forma di `application.cv_payload`, cioè l'output di `ai/tailor.py`. */
type CvPayload = {
  top_keywords?: unknown;
  summary?: unknown;
  experience?: unknown;
  skills?: { hard?: unknown; soft?: unknown };
};

export type BulletRiscritto = {
  /** Il testo generato, quello che finisce nel PDF. */
  testo: string;
  /** Il bullet del profilo da cui dichiara di venire, se esiste ancora. */
  originale: string | null;
  sourceId: string;
};

export type EsperienzaRiscritta = {
  id: string;
  ruolo: string;
  azienda: string;
  bullets: BulletRiscritto[];
};

export type CvGenerato = {
  status: ApplicationStatus;
  storagePath: string | null;
  lingua: string | null;
  /** Quante compressioni sono servite per stare in una pagina. */
  compressioni: number | null;
  keywords: string[];
  summary: string;
  /** Il summary del profilo master, per confronto. Può non esserci. */
  summaryOriginale: string | null;
  esperienze: EsperienzaRiscritta[];
  skills: { hard: string[]; soft: string[] };
  aggiornatoIl: Date;
};

/**
 * Il CV generato per un annuncio, già ricucito con il profilo master.
 *
 * La ricucitura avviene qui e non nel componente perché richiede una seconda
 * lettura dal database — il profilo — e i componenti non interrogano il
 * database: lo fa questo livello, che è anche quello che verifica la sessione.
 */
export async function getGeneratedCv(matchId: number): Promise<CvGenerato | null> {
  await guard();

  const righe = await getDb()
    .select()
    .from(application)
    .where(eq(application.matchId, matchId))
    .limit(1);

  const riga = righe[0];
  if (!riga?.cvPayload) return null;

  const payload = riga.cvPayload as CvPayload;
  const profilo = await getProfile();
  const master = profilo?.masterProfile ?? null;

  // Indici per il diff. Un id che non c'è più significa che il profilo è stato
  // modificato dopo la generazione: si mostra il testo generato senza originale
  // a fianco, invece di far sparire la riga.
  const bulletOriginali = new Map<string, string>();
  const esperienzeOriginali = new Map<string, { ruolo: string; azienda: string }>();
  for (const esperienza of master?.experiences ?? []) {
    esperienzeOriginali.set(esperienza.id, {
      ruolo: esperienza.role,
      azienda: esperienza.company,
    });
    for (const bullet of esperienza.bullets ?? []) {
      bulletOriginali.set(bullet.id, bullet.text);
    }
  }

  return {
    status: riga.status,
    storagePath: riga.cvStoragePath,
    lingua: riga.cvLanguage,
    compressioni: riga.cvFitIterations,
    keywords: stringhe(payload.top_keywords).slice(0, 5),
    summary: typeof payload.summary === "string" ? payload.summary : "",
    summaryOriginale: master?.summary ?? null,
    esperienze: esperienze(payload.experience, bulletOriginali, esperienzeOriginali),
    skills: {
      hard: skill(payload.skills?.hard),
      soft: skill(payload.skills?.soft),
    },
    aggiornatoIl: riga.updatedAt,
  };
}

/**
 * Approva il CV: la candidatura passa in coda per l'invio (Fase 7).
 *
 * Solo da `cv_ready`. Approvare una candidatura già inviata non vuol dire
 * niente, e riportarla indietro nel ciclo di vita nasconderebbe il fatto che è
 * partita davvero.
 */
export async function approveApplication(matchId: number): Promise<ApplicationStatus | null> {
  await guard();

  const aggiornate = await getDb()
    .update(application)
    .set({ status: "approved", updatedAt: new Date() })
    .where(eq(application.matchId, matchId))
    .returning({ status: application.status, id: application.id });

  return aggiornate[0]?.status ?? null;
}

/** Lo stato attuale, per decidere se l'approvazione è ancora possibile. */
export async function getApplicationStatus(matchId: number): Promise<ApplicationStatus | null> {
  await guard();

  const righe = await getDb()
    .select({ status: application.status })
    .from(application)
    .where(eq(application.matchId, matchId))
    .limit(1);

  return righe[0]?.status ?? null;
}

function stringhe(valore: unknown): string[] {
  return Array.isArray(valore) ? valore.filter((v): v is string => typeof v === "string") : [];
}

/**
 * Le competenze si stampano come `text`, non come `source`.
 *
 * `source` è la voce del profilo che le giustifica e serve al validatore del
 * worker; mostrarla qui vorrebbe dire far leggere due volte la stessa cosa.
 */
function skill(valore: unknown): string[] {
  if (!Array.isArray(valore)) return [];
  return valore
    .map((voce) =>
      typeof voce === "object" && voce !== null && typeof (voce as { text?: unknown }).text === "string"
        ? ((voce as { text: string }).text)
        : typeof voce === "string"
          ? voce
          : null,
    )
    .filter((v): v is string => v !== null);
}

function esperienze(
  valore: unknown,
  bulletOriginali: Map<string, string>,
  esperienzeOriginali: Map<string, { ruolo: string; azienda: string }>,
): EsperienzaRiscritta[] {
  if (!Array.isArray(valore)) return [];

  const voci: EsperienzaRiscritta[] = [];
  for (const grezza of valore) {
    if (typeof grezza !== "object" || grezza === null) continue;
    const id = (grezza as { id?: unknown }).id;
    if (typeof id !== "string") continue;

    const fonte = esperienzeOriginali.get(id);
    const bullets = Array.isArray((grezza as { bullets?: unknown }).bullets)
      ? ((grezza as { bullets: unknown[] }).bullets)
      : [];

    voci.push({
      id,
      ruolo: fonte?.ruolo ?? id,
      azienda: fonte?.azienda ?? "",
      bullets: bullets.flatMap((b) => {
        if (typeof b !== "object" || b === null) return [];
        const testo = (b as { text?: unknown }).text;
        const sourceId = (b as { source_id?: unknown }).source_id;
        if (typeof testo !== "string" || typeof sourceId !== "string") return [];
        return [{ testo, sourceId, originale: bulletOriginali.get(sourceId) ?? null }];
      }),
    });
  }
  return voci;
}
