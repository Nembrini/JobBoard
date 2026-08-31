import { z } from "zod";

import { nuovoId } from "@/lib/master-profile";
import type { MasterProfile } from "@/lib/master-profile";

/**
 * Lo specchio TypeScript di `worker/jobboard/schemas/applicant_info.py`.
 *
 * Stesso motivo dello specchio del `MasterProfile`: il pool è una colonna JSONB
 * scritta anche da qui, e un id duplicato o fuori formato romperebbe la Fase 6
 * la sera dopo, non al salvataggio. Vedi quel file per il perché questo pool
 * esiste separato sia dal CV master sia dalle risposte ai form — non è "il CV
 * master, ma meno rivisto": è materiale che la Fase 6 può scegliere di citare
 * *in aggiunta* al CV, non al suo posto.
 */

const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export const applicantInfoItemSchema = z.strictObject({
  id: z.string().trim().regex(ID, "id non valido: atteso kebab-case").max(120),
  label: z.string().trim().min(1, "l'etichetta è obbligatoria").max(120),
  text: z.string().trim().min(1, "il testo è obbligatorio").max(2000),
});

export const applicantInfoBankSchema = z
  .strictObject({
    items: z.array(applicantInfoItemSchema).max(200),
  })
  .superRefine((bank, ctx) => {
    const visti = new Set<string>();
    const doppi = new Set<string>();
    for (const voce of bank.items) {
      if (visti.has(voce.id)) doppi.add(voce.id);
      visti.add(voce.id);
    }
    if (doppi.size > 0) {
      ctx.addIssue({
        code: "custom",
        message: `id duplicati nel pool: ${[...doppi].sort().join(", ")}`,
      });
    }
  });

export type ApplicantInfoItem = z.infer<typeof applicantInfoItemSchema>;
export type ApplicantInfoBank = z.infer<typeof applicantInfoBankSchema>;

export const applicantInfoBankVuoto: ApplicantInfoBank = { items: [] };

/**
 * Il primo messaggio d'errore, con il percorso del campo — stessa forma di
 * `primoErrore` in `master-profile.ts`.
 */
export function primoErroreInfo(error: z.ZodError): string {
  const issue = error.issues[0];
  if (!issue) return "pool non valido";
  const dove = issue.path.join(".");
  return dove ? `${dove}: ${issue.message}` : issue.message;
}

/** Una voce proposta, senza ancora un id: lo prende quando viene davvero salvata. */
export type InformazioneProposta = { label: string; text: string };

/**
 * Le voci che il CV rivisto suggerisce, e che il pool non ha ancora.
 *
 * Deterministica e senza LLM: certificazioni e progetti sono già fatti veri e
 * strutturati nel `MasterProfile`, non serve chiedere a un modello di
 * "trovarli". Il confronto con quanto già salvato è sul testo normalizzato, non
 * sull'id — un id non esiste ancora per queste proposte, ed è proprio il
 * duplicato testuale ("l'ho già messo io a mano") che si vuole evitare di
 * riproporre a ogni caricamento.
 */
export function derivaInformazioniDalProfilo(
  profilo: MasterProfile,
  bank: ApplicantInfoBank,
): InformazioneProposta[] {
  const testiEsistenti = new Set(bank.items.map((voce) => normalizza(voce.text)));
  const proposte: InformazioneProposta[] = [];

  function proponi(label: string, text: string) {
    const pulito = text.trim();
    if (!pulito || testiEsistenti.has(normalizza(pulito))) return;
    proposte.push({ label, text: pulito });
  }

  for (const certificazione of profilo.certifications) {
    const pezzi = [certificazione.name, certificazione.issuer].filter(Boolean);
    const periodo = certificazione.issued ? ` (${certificazione.issued})` : "";
    proponi("Certificazione", `${pezzi.join(" — ")}${periodo}`);
  }

  for (const progetto of profilo.projects) {
    proponi("Progetto", `${progetto.name}: ${progetto.description}`);
  }

  return proposte;
}

/** Stessa normalizzazione di `nuovoId`: minuscolo, senza accenti, spazi collassati. */
function normalizza(testo: string): string {
  return testo
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** Un id nuovo per una voce del pool, riusando la stessa logica del CV master. */
export function nuovoIdInfo(testo: string, bank: ApplicantInfoBank): string {
  return nuovoId(
    testo,
    bank.items.map((voce) => voce.id),
  );
}
