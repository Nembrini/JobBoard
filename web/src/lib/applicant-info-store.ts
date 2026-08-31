import "server-only";

import { getDb } from "@/db";
import { applicantInfo } from "@/db/schema";
import {
  applicantInfoBankSchema,
  applicantInfoBankVuoto,
  type ApplicantInfoBank,
} from "@/lib/applicant-info";
import { requireApiSession } from "@/lib/dal";

/**
 * Lettura e scrittura del pool di informazioni applicante.
 *
 * Stessa forma di `profile.ts`: sessione verificata prima di ogni accesso, e un
 * pool assente sul database si legge come vuoto — non è un errore, è lo stato
 * di chi non ha ancora aggiunto nessuna voce.
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

export type PoolCaricato = {
  bank: ApplicantInfoBank;
  /** Compilato solo quando il JSON salvato non supera più la validazione. */
  invalido: string | null;
  updatedAt: Date | null;
};

export async function getApplicantInfo(): Promise<PoolCaricato> {
  await guard();

  const righe = await getDb().select().from(applicantInfo).limit(1);
  const riga = righe[0];
  if (!riga) return { bank: applicantInfoBankVuoto, invalido: null, updatedAt: null };

  const esito = applicantInfoBankSchema.safeParse({ items: riga.items });
  return {
    bank: esito.success ? esito.data : applicantInfoBankVuoto,
    invalido: esito.success ? null : descriviErrore(esito.error.issues),
    updatedAt: riga.updatedAt,
  };
}

/**
 * Scrive il pool per intero: stessa scelta di `saveProfile`, un solo oggetto JSONB.
 *
 * A differenza del profilo CV, questa riga non nasce da un import del worker: la
 * prima voce aggiunta dalla dashboard deve poter creare la riga da sola, quindi
 * qui l'`INSERT` mancante non è un errore ma il caso normale della prima volta.
 */
export async function saveApplicantInfo(nuovo: ApplicantInfoBank): Promise<void> {
  await guard();

  const db = getDb();
  const esistente = await db.select({ id: applicantInfo.id }).from(applicantInfo).limit(1);

  if (esistente.length === 0) {
    await db.insert(applicantInfo).values({ id: 1, items: nuovo.items });
    return;
  }

  await db.update(applicantInfo).set({ items: nuovo.items, updatedAt: new Date() });
}

function descriviErrore(issues: { path: PropertyKey[]; message: string }[]): string {
  const primo = issues[0];
  if (!primo) return "pool non valido";
  const dove = primo.path.map(String).join(".");
  return dove ? `${dove}: ${primo.message}` : primo.message;
}
