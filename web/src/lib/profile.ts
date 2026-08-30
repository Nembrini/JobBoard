import "server-only";

import { getDb } from "@/db";
import { profile } from "@/db/schema";
import { requireApiSession } from "@/lib/dal";
import { masterProfileSchema, type MasterProfile } from "@/lib/master-profile";
import { enqueueTask } from "@/lib/tasks";

/**
 * Lettura e scrittura del profilo dalla dashboard.
 *
 * Come in `queries.ts`, ogni funzione verifica la sessione **prima** di
 * toccare i dati: qui dentro passano il CV, i recapiti e la storia lavorativa
 * di una persona, che è il contenuto più sensibile dell'applicazione.
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

export type ProfiloCaricato = {
  masterProfile: MasterProfile | null;
  /** Compilato solo quando il JSON salvato non supera più la validazione. */
  invalido: string | null;
  sourceFileName: string;
  sourceStoragePath: string | null;
  reviewed: boolean;
  reviewedAt: Date | null;
  embeddingModel: string | null;
  embeddingDim: number | null;
  /** `true` se il profilo è stato modificato dopo il calcolo dell'embedding. */
  embeddingObsoleto: boolean;
  updatedAt: Date;
  createdAt: Date;
};

export async function getProfile(): Promise<ProfiloCaricato | null> {
  await guard();

  const righe = await getDb().select().from(profile).limit(1);
  const riga = righe[0];
  if (!riga) return null;

  // Il JSON arriva da una colonna JSONB, non da un tipo: se è stato scritto da
  // una versione precedente dello schema va mostrato l'errore, non fatto
  // esplodere il rendering di tutta la pagina.
  const esito = masterProfileSchema.safeParse(riga.masterProfile);

  return {
    masterProfile: esito.success ? esito.data : null,
    invalido: esito.success ? null : descriviErrore(esito.error.issues),
    sourceFileName: riga.sourceFileName,
    sourceStoragePath: riga.sourceStoragePath,
    reviewed: riga.reviewed,
    reviewedAt: riga.reviewedAt,
    embeddingModel: riga.embeddingModel,
    embeddingDim: riga.embeddingDim,
    embeddingObsoleto: riga.embeddingModel === null,
    updatedAt: riga.updatedAt,
    createdAt: riga.createdAt,
  };
}

/**
 * Salva il profilo modificato a mano e **azzera l'embedding**.
 *
 * L'azzeramento è il punto delicato. L'embedding è il vettore su cui gira lo
 * Stadio 1 del matching: se cambiano le esperienze e il vettore resta quello di
 * prima, i punteggi continuano a essere calcolati sul CV vecchio senza che
 * niente lo segnali. Meglio nessun vettore che uno che mente: il worker vede
 * `embedding_model` nullo e lo ricalcola alla run successiva.
 *
 * Il flag `reviewed` invece **resta acceso**: chi corregge a mano sta facendo
 * esattamente la revisione che quel flag certifica. Spegnerlo bloccherebbe la
 * pipeline come punizione per aver sistemato un refuso.
 */
export async function saveProfile(nuovo: MasterProfile): Promise<void> {
  await guard();

  const aggiornate = await getDb()
    .update(profile)
    .set({
      masterProfile: nuovo,
      embedding: null,
      embeddingModel: null,
      embeddingDim: null,
      updatedAt: new Date(),
    })
    .returning({ id: profile.id });

  if (aggiornate.length === 0) {
    throw new Error("nessun profilo da aggiornare: caricare prima un CV");
  }
}

/** Cancella il profilo. Restituisce il percorso del file da rimuovere, se c'era. */
export async function deleteProfile(): Promise<{ storagePath: string | null }> {
  await guard();

  const cancellate = await getDb()
    .delete(profile)
    .returning({ storagePath: profile.sourceStoragePath });

  return { storagePath: cancellate[0]?.storagePath ?? null };
}

/**
 * Conferma il profilo: è il flag che sblocca il matching.
 *
 * Il worker salva ogni estrazione come **non rivista**, perché un'estrazione
 * automatica non è una revisione e un profilo sbagliato avvelena ogni punteggio
 * a valle — è il guardrail della Fase 1.3. Prima la conferma si dava da riga di
 * comando (`jb profile load`); ora si dà da qui, dopo aver riletto le voci.
 */
export async function confirmProfile(): Promise<void> {
  await guard();

  const aggiornate = await getDb()
    .update(profile)
    .set({ reviewed: true, reviewedAt: new Date(), updatedAt: new Date() })
    .returning({ id: profile.id });

  if (aggiornate.length === 0) throw new Error("nessun profilo da confermare");
}

/**
 * Accoda la rielaborazione di un CV appena caricato.
 *
 * La coda vera sta in `tasks.ts`: qui resta solo il nome delle chiavi del
 * payload, che è l'unica cosa che il worker e la dashboard devono avere uguale
 * — `handlers.reparse_profile` legge esattamente questi due nomi.
 */
export async function enqueueReparse(storagePath: string, fileName: string): Promise<number> {
  const esito = await enqueueTask("reparse_profile", {
    storage_path: storagePath,
    file_name: fileName,
  });
  return esito.id;
}

function descriviErrore(issues: { path: PropertyKey[]; message: string }[]): string {
  const primo = issues[0];
  if (!primo) return "profilo non valido";
  const dove = primo.path.map(String).join(".");
  return dove ? `${dove}: ${primo.message}` : primo.message;
}
