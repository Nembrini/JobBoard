import { z } from "zod";

/**
 * Lo specchio TypeScript di `worker/jobboard/schemas/profile.py`.
 *
 * **Perché esiste una seconda definizione dello stesso oggetto.** Il profilo è
 * una colonna JSONB: il database non ne verifica la forma. Finché a scriverlo
 * era solo il worker, la validazione di Pydantic bastava. Ora lo scrive anche
 * la dashboard, e un profilo con un campo in più o una data malformata non dà
 * errore al salvataggio — lo dà la sera dopo, quando la pipeline di matching
 * prova a rileggerlo e si ferma. Il posto giusto per rifiutarlo è qui.
 *
 * Le regole ricopiate dal Pydantic, e il motivo di ciascuna:
 *
 * - **oggetti stretti** (`strictObject`): di là c'è `extra="forbid"`. Un campo
 *   in più scritto da qui farebbe fallire la rilettura, non lo ignorerebbe.
 * - **id kebab-case e univoci**: sono le chiavi con cui il validatore
 *   anti-invenzione della Fase 6 dirà *quale* voce giustifica una frase del CV
 *   generato. Due voci con lo stesso id rendono quella risposta ambigua.
 * - **date `YYYY-MM`**: un CV scrive "Gen 2022", "01/2022", "2022"; la
 *   normalizzazione avviene in estrazione e qui si accetta una sola forma.
 * - **stringhe vuote convertite in `null`**: un campo svuotato in un form
 *   arriva come `""`, che di là è una stringa valida di zero caratteri e non
 *   "assente". La differenza conta: `result: ""` significherebbe che il bullet
 *   *ha* un risultato misurabile, e che è vuoto.
 */

const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const ANNO_MESE = /^\d{4}-(0[1-9]|1[0-2])$/;

/** Testo facoltativo: assente, non presente e vuoto. */
function opzionale(max: number) {
  return z.preprocess(
    (v) => (typeof v === "string" && v.trim() === "" ? null : v),
    z.string().trim().max(max).nullable(),
  );
}

const idSchema = z.string().trim().regex(ID, "id non valido: atteso kebab-case").max(120);
const annoMese = z.string().trim().regex(ANNO_MESE, "data non valida: attesa nella forma 2024-03");
const annoMeseOpzionale = z.preprocess(
  (v) => (typeof v === "string" && v.trim() === "" ? null : v),
  annoMese.nullable(),
);

/** Elenco di parole: niente vuote, niente doppioni, ordine conservato. */
const elenco = (max: number) =>
  z
    .array(z.string().trim().max(120))
    .max(max)
    .transform((voci) => [...new Set(voci.filter(Boolean))]);

export const contactSchema = z.strictObject({
  full_name: z.string().trim().min(2, "il nome è obbligatorio").max(120),
  email: opzionale(320),
  phone: opzionale(40),
  city: opzionale(120),
  country: z.preprocess(
    (v) => (typeof v === "string" && v.trim() === "" ? null : v),
    z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z]{2}$/, "codice paese ISO a due lettere, es. IT")
      .nullable(),
  ),
  linkedin_url: opzionale(512),
  github_url: opzionale(512),
  portfolio_url: opzionale(512),
});

export const bulletSchema = z.strictObject({
  id: idSchema,
  text: z.string().trim().min(10, "almeno 10 caratteri").max(400),
  action: opzionale(200),
  context: opzionale(400),
  result: opzionale(200),
  skills: elenco(40),
});

export const experienceSchema = z
  .strictObject({
    id: idSchema,
    company: z.string().trim().min(1, "azienda obbligatoria").max(200),
    role: z.string().trim().min(1, "ruolo obbligatorio").max(200),
    location: opzionale(200),
    work_mode: z.enum(["on_site", "hybrid", "remote", "unknown"]),
    employment_type: opzionale(120),
    start: annoMese,
    end: annoMeseOpzionale,
    bullets: z.array(bulletSchema).max(30),
    tech: elenco(60),
  })
  .refine((e) => !e.end || e.end >= e.start, {
    error: "la data di fine precede quella di inizio",
    path: ["end"],
  });

export const educationSchema = z.strictObject({
  id: idSchema,
  institution: z.string().trim().min(1, "istituto obbligatorio").max(200),
  degree: z.string().trim().min(1, "titolo obbligatorio").max(200),
  field_of_study: opzionale(200),
  start: annoMeseOpzionale,
  end: annoMeseOpzionale,
  grade: opzionale(60),
  highlights: z.array(z.string().trim().min(1).max(400)).max(20),
});

export const projectSchema = z.strictObject({
  id: idSchema,
  name: z.string().trim().min(1, "nome obbligatorio").max(200),
  description: z.string().trim().max(600),
  url: opzionale(512),
  tech: elenco(40),
  context: z.enum(["personal", "academic", "professional", "open_source"]),
});

export const certificationSchema = z.strictObject({
  id: idSchema,
  name: z.string().trim().min(1, "nome obbligatorio").max(200),
  issuer: opzionale(200),
  issued: annoMeseOpzionale,
  expires: annoMeseOpzionale,
  credential_url: opzionale(512),
});

export const CEFR = ["A1", "A2", "B1", "B2", "C1", "C2", "native"] as const;

export const languageSchema = z.strictObject({
  code: z
    .string()
    .trim()
    .toLowerCase()
    .regex(/^[a-z]{2,3}$/, "codice lingua ISO 639-1, es. it"),
  level: z.enum(CEFR),
});

export const masterProfileSchema = z
  .strictObject({
    contact: contactSchema,
    headline: opzionale(120),
    summary: opzionale(1200),
    experiences: z.array(experienceSchema).max(40),
    education: z.array(educationSchema).max(20),
    projects: z.array(projectSchema).max(30),
    certifications: z.array(certificationSchema).max(30),
    skills: z.strictObject({ hard: elenco(120), soft: elenco(60) }),
    languages: z.array(languageSchema).max(15),
  })
  .superRefine((p, ctx) => {
    const visti = new Set<string>();
    const doppi = new Set<string>();
    for (const id of tuttiGliId(p)) {
      if (visti.has(id)) doppi.add(id);
      visti.add(id);
    }
    if (doppi.size > 0) {
      ctx.addIssue({
        code: "custom",
        message: `id duplicati nel profilo: ${[...doppi].sort().join(", ")}`,
      });
    }
  });

export type MasterProfile = z.infer<typeof masterProfileSchema>;
export type Experience = MasterProfile["experiences"][number];
export type Bullet = Experience["bullets"][number];
export type Education = MasterProfile["education"][number];
export type Project = MasterProfile["projects"][number];
export type Certification = MasterProfile["certifications"][number];
export type LanguageSkill = MasterProfile["languages"][number];

function tuttiGliId(p: {
  experiences: { id: string; bullets: { id: string }[] }[];
  education: { id: string }[];
  projects: { id: string }[];
  certifications: { id: string }[];
}): string[] {
  return [
    ...p.experiences.map((e) => e.id),
    ...p.experiences.flatMap((e) => e.bullets.map((b) => b.id)),
    ...p.education.map((x) => x.id),
    ...p.projects.map((x) => x.id),
    ...p.certifications.map((x) => x.id),
  ];
}

/**
 * Un id nuovo, derivato dal testo e reso univoco rispetto a quelli esistenti.
 *
 * Gli id non si scrivono a mano nella UI: sono chiavi tecniche, e lasciarli
 * modificabili significherebbe poter rinominare la voce a cui un giorno il
 * validatore anti-invenzione dovrà risalire. Qui si generano una volta e non si
 * toccano più.
 */
export function nuovoId(testo: string, presi: Iterable<string>): string {
  const base =
    testo
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60)
      .replace(/-+$/, "") || "voce";

  const occupati = new Set(presi);
  if (!occupati.has(base)) return base;
  for (let n = 2; ; n++) {
    const tentativo = `${base}-${n}`;
    if (!occupati.has(tentativo)) return tentativo;
  }
}

/** Tutti gli id già in uso, per non generarne uno che collide. */
export function idInUso(p: MasterProfile): string[] {
  return tuttiGliId(p);
}

/**
 * Il primo messaggio d'errore, con il percorso del campo.
 *
 * "experiences.0.end: la data di fine precede quella di inizio" dice dove
 * guardare; "Invalid input" no.
 */
export function primoErrore(error: z.ZodError): string {
  const issue = error.issues[0];
  if (!issue) return "profilo non valido";
  const dove = issue.path.join(".");
  return dove ? `${dove}: ${issue.message}` : issue.message;
}
