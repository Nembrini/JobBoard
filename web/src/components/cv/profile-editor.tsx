"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Loader2, Plus, RotateCcw, Trash2 } from "lucide-react";

import {
  AreaTesto,
  BottoneAggiungi,
  Campo,
  CampoMese,
  ElencoModificabile,
  Etichetta,
  Selezione,
  Targhetta,
} from "@/components/cv/fields";
import { salvaProfilo } from "@/lib/profile-actions";
import {
  CEFR,
  idInUso,
  nuovoId,
  type Bullet,
  type Certification,
  type Education,
  type Experience,
  type MasterProfile,
  type Project,
} from "@/lib/master-profile";

/**
 * L'editor del profilo estratto dal CV.
 *
 * **Un solo componente con dentro tutto lo stato, e un solo salvataggio.** Il
 * profilo è una colonna JSONB: si riscrive per intero o non si riscrive. Otto
 * form indipendenti che salvano a turno darebbero l'illusione di modifiche
 * parziali su un dato che parziale non è, e basterebbe una di quelle scritture
 * a fallire per lasciare sul database un profilo mezzo vecchio e mezzo nuovo.
 *
 * Gli **id non sono modificabili**. Sono le chiavi con cui il validatore
 * anti-invenzione della Fase 6 dirà *quale* voce del CV giustifica una frase di
 * quello generato: si assegnano una volta, alla creazione, e restano. Sono
 * visibili perché servono a leggere i messaggi di quel validatore, non perché
 * ci sia qualcosa da metterci mano.
 */
export function ProfileEditor({ iniziale }: { iniziale: MasterProfile }) {
  const router = useRouter();
  const [base, setBase] = useState(iniziale);
  const [profilo, setProfilo] = useState(iniziale);
  const [errore, setErrore] = useState<string | null>(null);
  const [salvato, setSalvato] = useState(false);
  const [inCorso, startTransition] = useTransition();

  const modificato = JSON.stringify(profilo) !== JSON.stringify(base);

  function muta(fn: (p: MasterProfile) => MasterProfile) {
    setProfilo(fn);
    setSalvato(false);
  }

  async function salva() {
    setErrore(null);
    const esito = await salvaProfilo(profilo);
    if (!esito.ok) {
      setErrore(esito.errore);
      return;
    }
    setBase(profilo);
    setSalvato(true);
    // I punteggi in home sono calcolati su questo profilo: la lista va riletta.
    startTransition(() => router.refresh());
  }

  return (
    <div className="space-y-10 pb-28">
      <Sezione titolo="Contatti">
        <div className="grid gap-4 sm:grid-cols-2">
          <Campo
            etichetta="Nome e cognome"
            valore={profilo.contact.full_name}
            onChange={(v) => muta((p) => ({ ...p, contact: { ...p.contact, full_name: v } }))}
          />
          <Campo
            etichetta="Email"
            tipo="email"
            valore={testo(profilo.contact.email)}
            onChange={(v) => muta((p) => ({ ...p, contact: { ...p.contact, email: nullo(v) } }))}
          />
          <Campo
            etichetta="Telefono"
            valore={testo(profilo.contact.phone)}
            onChange={(v) => muta((p) => ({ ...p, contact: { ...p.contact, phone: nullo(v) } }))}
          />
          <div className="grid grid-cols-[1fr_7rem] gap-4">
            <Campo
              etichetta="Città"
              valore={testo(profilo.contact.city)}
              onChange={(v) => muta((p) => ({ ...p, contact: { ...p.contact, city: nullo(v) } }))}
            />
            <Campo
              etichetta="Paese"
              segnaposto="IT"
              valore={testo(profilo.contact.country)}
              onChange={(v) => muta((p) => ({ ...p, contact: { ...p.contact, country: nullo(v) } }))}
            />
          </div>
          <Campo
            etichetta="LinkedIn"
            valore={testo(profilo.contact.linkedin_url)}
            onChange={(v) =>
              muta((p) => ({ ...p, contact: { ...p.contact, linkedin_url: nullo(v) } }))
            }
          />
          <Campo
            etichetta="GitHub"
            valore={testo(profilo.contact.github_url)}
            onChange={(v) =>
              muta((p) => ({ ...p, contact: { ...p.contact, github_url: nullo(v) } }))
            }
          />
          <Campo
            etichetta="Portfolio"
            valore={testo(profilo.contact.portfolio_url)}
            onChange={(v) =>
              muta((p) => ({ ...p, contact: { ...p.contact, portfolio_url: nullo(v) } }))
            }
          />
        </div>
      </Sezione>

      <Sezione
        titolo="Presentazione"
        nota="Il sommario originale. Quello su misura viene riscritto per ogni annuncio, partendo da qui."
      >
        <div className="space-y-4">
          <Campo
            etichetta="Titolo professionale"
            segnaposto="Software Developer"
            valore={testo(profilo.headline)}
            onChange={(v) => muta((p) => ({ ...p, headline: nullo(v) }))}
          />
          <AreaTesto
            etichetta="Sommario"
            righe={4}
            massimo={1200}
            valore={testo(profilo.summary)}
            onChange={(v) => muta((p) => ({ ...p, summary: nullo(v) }))}
          />
        </div>
      </Sezione>

      <Sezione
        titolo="Esperienze"
        conteggio={profilo.experiences.length}
        nota={`${contaBullet(profilo)} punti in totale: sono le uniche affermazioni da cui un CV su misura potrà attingere.`}
      >
        <ol className="space-y-4">
          {profilo.experiences.map((esperienza, i) => (
            <EsperienzaCard
              key={esperienza.id}
              esperienza={esperienza}
              profilo={profilo}
              onChange={(nuova) =>
                muta((p) => ({ ...p, experiences: sostituisci(p.experiences, i, nuova) }))
              }
              onElimina={() =>
                muta((p) => ({ ...p, experiences: p.experiences.filter((_, j) => j !== i) }))
              }
            />
          ))}
        </ol>
        <BottoneAggiungi
          onClick={() =>
            muta((p) => ({
              ...p,
              experiences: [...p.experiences, nuovaEsperienza(p)],
            }))
          }
        >
          Aggiungi esperienza
        </BottoneAggiungi>
      </Sezione>

      <Sezione titolo="Formazione" conteggio={profilo.education.length}>
        <div className="space-y-4">
          {profilo.education.map((voce, i) => (
            <Scheda
              key={voce.id}
              id={voce.id}
              titolo={voce.degree || "Nuovo titolo di studio"}
              onElimina={() =>
                muta((p) => ({ ...p, education: p.education.filter((_, j) => j !== i) }))
              }
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Campo
                  etichetta="Titolo"
                  valore={voce.degree}
                  onChange={(v) => muta(campia("education", i, { degree: v }))}
                />
                <Campo
                  etichetta="Istituto"
                  valore={voce.institution}
                  onChange={(v) => muta(campia("education", i, { institution: v }))}
                />
                <Campo
                  etichetta="Ambito"
                  valore={testo(voce.field_of_study)}
                  onChange={(v) => muta(campia("education", i, { field_of_study: nullo(v) }))}
                />
                <Campo
                  etichetta="Voto"
                  valore={testo(voce.grade)}
                  onChange={(v) => muta(campia("education", i, { grade: nullo(v) }))}
                />
                <CampoMese
                  etichetta="Inizio"
                  valore={testo(voce.start)}
                  onChange={(v) => muta(campia("education", i, { start: nullo(v) }))}
                />
                <CampoMese
                  etichetta="Fine"
                  valore={testo(voce.end)}
                  onChange={(v) => muta(campia("education", i, { end: nullo(v) }))}
                />
              </div>
              <ElencoModificabile
                etichetta="Punti salienti"
                voci={voce.highlights}
                onChange={(v) => muta(campia("education", i, { highlights: v }))}
              />
            </Scheda>
          ))}
        </div>
        <BottoneAggiungi
          onClick={() => muta((p) => ({ ...p, education: [...p.education, nuovaFormazione(p)] }))}
        >
          Aggiungi titolo di studio
        </BottoneAggiungi>
      </Sezione>

      <Sezione titolo="Progetti" conteggio={profilo.projects.length}>
        <div className="space-y-4">
          {profilo.projects.map((voce, i) => (
            <Scheda
              key={voce.id}
              id={voce.id}
              titolo={voce.name || "Nuovo progetto"}
              onElimina={() =>
                muta((p) => ({ ...p, projects: p.projects.filter((_, j) => j !== i) }))
              }
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Campo
                  etichetta="Nome"
                  valore={voce.name}
                  onChange={(v) => muta(campia("projects", i, { name: v }))}
                />
                <Selezione
                  etichetta="Contesto"
                  valore={voce.context}
                  opzioni={CONTESTI}
                  onChange={(v) => muta(campia("projects", i, { context: v }))}
                />
              </div>
              <Campo
                etichetta="URL"
                valore={testo(voce.url)}
                segnaposto="https://github.com/…"
                aiuto="Indirizzo completo: un CV su misura lo riporta così com'è."
                onChange={(v) => muta(campia("projects", i, { url: nullo(v) }))}
              />
              <AreaTesto
                etichetta="Descrizione"
                massimo={600}
                valore={voce.description}
                onChange={(v) => muta(campia("projects", i, { description: v }))}
              />
              <ElencoModificabile
                etichetta="Tecnologie"
                voci={voce.tech}
                onChange={(v) => muta(campia("projects", i, { tech: v }))}
              />
            </Scheda>
          ))}
        </div>
        <BottoneAggiungi
          onClick={() => muta((p) => ({ ...p, projects: [...p.projects, nuovoProgetto(p)] }))}
        >
          Aggiungi progetto
        </BottoneAggiungi>
      </Sezione>

      <Sezione titolo="Certificazioni" conteggio={profilo.certifications.length}>
        <div className="space-y-4">
          {profilo.certifications.map((voce, i) => (
            <Scheda
              key={voce.id}
              id={voce.id}
              titolo={voce.name || "Nuova certificazione"}
              onElimina={() =>
                muta((p) => ({
                  ...p,
                  certifications: p.certifications.filter((_, j) => j !== i),
                }))
              }
            >
              <div className="grid gap-4 sm:grid-cols-2">
                <Campo
                  etichetta="Nome"
                  valore={voce.name}
                  onChange={(v) => muta(campia("certifications", i, { name: v }))}
                />
                <Campo
                  etichetta="Ente"
                  valore={testo(voce.issuer)}
                  onChange={(v) => muta(campia("certifications", i, { issuer: nullo(v) }))}
                />
                <CampoMese
                  etichetta="Rilasciata"
                  valore={testo(voce.issued)}
                  onChange={(v) => muta(campia("certifications", i, { issued: nullo(v) }))}
                />
                <CampoMese
                  etichetta="Scadenza"
                  valore={testo(voce.expires)}
                  vuotoSignifica="Vuoto: non scade."
                  onChange={(v) => muta(campia("certifications", i, { expires: nullo(v) }))}
                />
              </div>
              <Campo
                etichetta="Verifica"
                valore={testo(voce.credential_url)}
                onChange={(v) => muta(campia("certifications", i, { credential_url: nullo(v) }))}
              />
            </Scheda>
          ))}
        </div>
        <BottoneAggiungi
          onClick={() =>
            muta((p) => ({ ...p, certifications: [...p.certifications, nuovaCertificazione(p)] }))
          }
        >
          Aggiungi certificazione
        </BottoneAggiungi>
      </Sezione>

      <Sezione
        titolo="Competenze"
        nota="Le hard entrano nel punteggio con un confronto esatto sul testo dell'annuncio. Le soft finiscono nel CV generato ma non nel punteggio: dedurle da una job description produce solo rumore."
      >
        <div className="space-y-4">
          <ElencoModificabile
            etichetta="Hard"
            voci={profilo.skills.hard}
            onChange={(v) => muta((p) => ({ ...p, skills: { ...p.skills, hard: v } }))}
          />
          <ElencoModificabile
            etichetta="Soft"
            voci={profilo.skills.soft}
            onChange={(v) => muta((p) => ({ ...p, skills: { ...p.skills, soft: v } }))}
          />
        </div>
      </Sezione>

      <Sezione
        titolo="Lingue"
        conteggio={profilo.languages.length}
        nota="Un annuncio che chiede una lingua che non compare qui viene escluso dai filtri duri: l'elenco vuoto non esclude nulla, ma nemmeno aiuta."
      >
        <div className="space-y-3">
          {profilo.languages.map((lingua, i) => (
            <div key={i} className="flex items-end gap-3">
              <Campo
                etichetta="Codice"
                larghezza="w-28"
                segnaposto="it"
                valore={lingua.code}
                onChange={(v) =>
                  muta((p) => ({
                    ...p,
                    languages: sostituisci(p.languages, i, { ...lingua, code: v }),
                  }))
                }
              />
              <Selezione
                etichetta="Livello"
                valore={lingua.level}
                opzioni={LIVELLI}
                onChange={(v) =>
                  muta((p) => ({
                    ...p,
                    languages: sostituisci(p.languages, i, { ...lingua, level: v }),
                  }))
                }
              />
              <BottoneElimina
                etichetta="Togli la lingua"
                onClick={() =>
                  muta((p) => ({ ...p, languages: p.languages.filter((_, j) => j !== i) }))
                }
              />
            </div>
          ))}
        </div>
        <BottoneAggiungi
          onClick={() =>
            muta((p) => ({ ...p, languages: [...p.languages, { code: "", level: "B2" as const }] }))
          }
        >
          Aggiungi lingua
        </BottoneAggiungi>
      </Sezione>

      <BarraSalvataggio
        modificato={modificato}
        inCorso={inCorso}
        errore={errore}
        salvato={salvato}
        onSalva={salva}
        onAnnulla={() => {
          setProfilo(base);
          setErrore(null);
        }}
      />
    </div>
  );
}

// --- l'esperienza e i suoi bullet --------------------------------------------

const MODALITA = [
  ["unknown", "Non dichiarata"],
  ["on_site", "In sede"],
  ["hybrid", "Ibrido"],
  ["remote", "Remoto"],
] as const;

const CONTESTI = [
  ["personal", "Personale"],
  ["academic", "Accademico"],
  ["professional", "Professionale"],
  ["open_source", "Open source"],
] as const;

const LIVELLI = CEFR.map((l) => [l, l === "native" ? "Madrelingua" : l] as const);

/**
 * Una esperienza.
 *
 * Il segno strutturale è **l'intervallo di date**, non un numero d'ordine: le
 * esperienze sono già una sequenza, e a ordinarle sono le date. Numerarle
 * 01/02/03 aggiungerebbe un ordine inventato sopra a quello che i dati hanno
 * già, e nasconderebbe l'unica informazione che serve davvero — quale è ancora
 * in corso. Quella la dice il pallino: pieno se il lavoro non è finito.
 */
function EsperienzaCard({
  esperienza,
  profilo,
  onChange,
  onElimina,
}: {
  esperienza: Experience;
  profilo: MasterProfile;
  onChange: (e: Experience) => void;
  onElimina: () => void;
}) {
  const inCorso = !esperienza.end;

  return (
    <li className="rounded-xl border p-4 sm:p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            title={inCorso ? "in corso" : undefined}
            className={`size-2.5 shrink-0 rounded-full border-2 ${
              inCorso ? "border-emerald-500 bg-emerald-500" : "border-muted-foreground/50"
            }`}
          />
          <span className="num text-muted-foreground text-xs">
            {esperienza.start || "····-··"} → {esperienza.end || "oggi"}
          </span>
          <Targhetta id={esperienza.id} />
        </div>
        <BottoneElimina etichetta="Elimina l'esperienza" onClick={onElimina} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Campo
          etichetta="Ruolo"
          valore={esperienza.role}
          onChange={(v) => onChange({ ...esperienza, role: v })}
        />
        <Campo
          etichetta="Azienda"
          valore={esperienza.company}
          onChange={(v) => onChange({ ...esperienza, company: v })}
        />
        <Campo
          etichetta="Luogo"
          valore={testo(esperienza.location)}
          onChange={(v) => onChange({ ...esperienza, location: nullo(v) })}
        />
        <Selezione
          etichetta="Modalità"
          valore={esperienza.work_mode}
          opzioni={MODALITA}
          onChange={(v) => onChange({ ...esperienza, work_mode: v })}
        />
        <CampoMese
          etichetta="Inizio"
          valore={esperienza.start}
          onChange={(v) => onChange({ ...esperienza, start: v })}
        />
        <CampoMese
          etichetta="Fine"
          valore={testo(esperienza.end)}
          vuotoSignifica="Vuoto: in corso."
          onChange={(v) => onChange({ ...esperienza, end: nullo(v) })}
        />
        <Campo
          etichetta="Tipo di contratto"
          valore={testo(esperienza.employment_type)}
          segnaposto="Indeterminato, stage, freelance…"
          onChange={(v) => onChange({ ...esperienza, employment_type: nullo(v) })}
        />
      </div>

      <div className="mt-4">
        <ElencoModificabile
          etichetta="Tecnologie"
          voci={esperienza.tech}
          onChange={(v) => onChange({ ...esperienza, tech: v })}
        />
      </div>

      <div className="mt-6 space-y-3">
        <Etichetta>Punti ({esperienza.bullets.length})</Etichetta>
        {esperienza.bullets.map((bullet, i) => (
          <BulletCard
            key={bullet.id}
            bullet={bullet}
            onChange={(nuovo) =>
              onChange({ ...esperienza, bullets: sostituisci(esperienza.bullets, i, nuovo) })
            }
            onElimina={() =>
              onChange({ ...esperienza, bullets: esperienza.bullets.filter((_, j) => j !== i) })
            }
          />
        ))}
        <button
          type="button"
          onClick={() =>
            onChange({
              ...esperienza,
              bullets: [
                ...esperienza.bullets,
                {
                  id: nuovoId(`${esperienza.id}-${esperienza.bullets.length + 1}`, idInUso(profilo)),
                  text: "",
                  action: null,
                  context: null,
                  result: null,
                  skills: [],
                },
              ],
            })
          }
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm"
        >
          <Plus className="size-4" />
          Aggiungi un punto
        </button>
      </div>
    </li>
  );
}

/**
 * Un punto del CV, scomposto secondo ACR — Azione, Contesto, Risultato.
 *
 * È l'elemento centrale di questa pagina, perché è l'unità che il generatore
 * della Fase 6 riscriverà e che il validatore anti-invenzione dovrà poter
 * ricondurre a qualcosa di vero. Mostrarne la scomposizione, e non solo la
 * frase, rende visibile l'unico limite che conta: **un punto senza risultato
 * misurabile non può acquistarne uno.** Il CV su misura riformulerà la frase,
 * ma da un dato che qui non c'è non può nascere una percentuale là.
 */
function BulletCard({
  bullet,
  onChange,
  onElimina,
}: {
  bullet: Bullet;
  onChange: (b: Bullet) => void;
  onElimina: () => void;
}) {
  return (
    <div className="bg-muted/30 rounded-lg border p-3 sm:p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <Targhetta id={bullet.id} />
        <BottoneElimina etichetta="Elimina il punto" onClick={onElimina} />
      </div>

      <AreaTesto
        etichetta="Testo"
        righe={2}
        massimo={400}
        valore={bullet.text}
        segnaposto="Come appare nel CV"
        onChange={(v) => onChange({ ...bullet, text: v })}
      />

      <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-[6rem_1fr]">
        <Slot etichetta="Azione">
          <input
            value={testo(bullet.action)}
            onChange={(e) => onChange({ ...bullet, action: nullo(e.target.value) })}
            placeholder="il verbo: ridotto, progettato, migrato"
            className="hover:bg-muted focus-visible:ring-ring/60 w-full rounded border border-transparent bg-transparent px-2 py-1 outline-none transition-colors focus-visible:ring-2"
          />
        </Slot>
        <Slot etichetta="Contesto">
          <input
            value={testo(bullet.context)}
            onChange={(e) => onChange({ ...bullet, context: nullo(e.target.value) })}
            placeholder="prodotto, team, scala, vincoli"
            className="hover:bg-muted focus-visible:ring-ring/60 w-full rounded border border-transparent bg-transparent px-2 py-1 outline-none transition-colors focus-visible:ring-2"
          />
        </Slot>
        <Slot etichetta="Risultato">
          <input
            value={testo(bullet.result)}
            onChange={(e) => onChange({ ...bullet, result: nullo(e.target.value) })}
            placeholder="il numero, se c'è"
            className="hover:bg-muted focus-visible:ring-ring/60 w-full rounded border border-transparent bg-transparent px-2 py-1 outline-none transition-colors focus-visible:ring-2"
          />
        </Slot>
      </dl>

      {!bullet.result ? (
        <p className="text-muted-foreground mt-2 border-l-2 border-amber-500/60 pl-3 text-xs leading-relaxed">
          Nessun risultato misurabile. Il CV su misura potrà riformulare la frase, non aggiungerci
          un numero.
        </p>
      ) : null}

      <div className="mt-3">
        <ElencoModificabile
          etichetta="Competenze citate"
          voci={bullet.skills}
          onChange={(v) => onChange({ ...bullet, skills: v })}
        />
      </div>
    </div>
  );
}

function Slot({ etichetta, children }: { etichetta: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground pt-1.5 text-xs font-medium tracking-[0.06em] uppercase">
        {etichetta}
      </dt>
      <dd>{children}</dd>
    </>
  );
}

// --- impalcatura --------------------------------------------------------------

function Sezione({
  titolo,
  conteggio,
  nota,
  children,
}: {
  titolo: string;
  conteggio?: number;
  nota?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="border-b pb-2">
        <h2 className="font-heading flex items-baseline gap-2 text-lg font-semibold tracking-tight">
          {titolo}
          {conteggio !== undefined ? (
            <span className="num text-muted-foreground text-sm font-normal">{conteggio}</span>
          ) : null}
        </h2>
        {nota ? (
          <p className="text-muted-foreground mt-1 max-w-2xl text-sm leading-relaxed">{nota}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function Scheda({
  id,
  titolo,
  onElimina,
  children,
}: {
  id: string;
  titolo: string;
  onElimina: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-4 rounded-xl border p-4 sm:p-5">
      {/* Niente `flex-wrap` qui: con una targhetta lunga il cestino finiva a
          capo, sotto al titolo, dove sembra il bottone della sezione invece che
          di questa scheda. Va a capo il gruppo titolo+targhetta, che è testo. */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
          <span className="font-medium">{titolo}</span>
          <Targhetta id={id} />
        </div>
        <BottoneElimina etichetta={`Elimina ${titolo}`} onClick={onElimina} />
      </div>
      {children}
    </div>
  );
}

function BottoneElimina({ etichetta, onClick }: { etichetta: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={etichetta}
      title={etichetta}
      className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive grid size-9 shrink-0 place-items-center rounded-md transition-colors"
    >
      <Trash2 className="size-4" />
    </button>
  );
}

/**
 * La barra di salvataggio.
 *
 * Fissa in basso e visibile solo quando c'è qualcosa da salvare: la pagina è
 * lunga, e un bottone in fondo si trova solo scorrendo fino in fondo — cioè
 * dopo aver dimenticato di aver modificato qualcosa in cima.
 */
function BarraSalvataggio({
  modificato,
  inCorso,
  errore,
  salvato,
  onSalva,
  onAnnulla,
}: {
  modificato: boolean;
  inCorso: boolean;
  errore: string | null;
  salvato: boolean;
  onSalva: () => void;
  onAnnulla: () => void;
}) {
  const [attesa, setAttesa] = useState(false);

  if (!modificato) {
    return salvato ? (
      <p role="status" className="text-muted-foreground text-sm">
        Profilo salvato. L&apos;embedding verrà ricalcolato dal worker alla prossima run: fino ad
        allora i punteggi restano quelli di prima.
      </p>
    ) : null;
  }

  return (
    <div className="bg-background/95 fixed inset-x-0 bottom-0 z-40 border-t backdrop-blur">
      <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <p className="text-sm">
          {errore ? (
            <span className="text-destructive">{errore}</span>
          ) : (
            "Ci sono modifiche non salvate."
          )}
        </p>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onAnnulla}
            disabled={attesa || inCorso}
            className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
          >
            <RotateCcw className="size-4" />
            Annulla
          </button>
          <button
            type="button"
            onClick={async () => {
              setAttesa(true);
              try {
                await onSalva();
              } finally {
                setAttesa(false);
              }
            }}
            disabled={attesa || inCorso}
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-10 items-center gap-2 rounded-lg px-5 text-sm font-medium disabled:opacity-60"
          >
            {attesa ? <Loader2 className="size-4 animate-spin" /> : null}
            Salva le modifiche
          </button>
        </div>
      </div>
    </div>
  );
}

// --- utilità ------------------------------------------------------------------

/** `null` -> `""` per gli input, che non accettano `null` senza diventare scontrollati. */
function testo(v: string | null): string {
  return v ?? "";
}

/** `""` -> `null`: di là "assente" e "stringa vuota" non sono la stessa cosa. */
function nullo(v: string): string | null {
  return v.trim() === "" ? null : v;
}

function sostituisci<T>(elenco: T[], indice: number, valore: T): T[] {
  return elenco.map((v, i) => (i === indice ? valore : v));
}

/** Aggiorna un campo di una voce dentro uno degli elenchi del profilo. */
function campia<K extends "education" | "projects" | "certifications">(
  chiave: K,
  indice: number,
  patch: Partial<MasterProfile[K][number]>,
) {
  return (p: MasterProfile): MasterProfile => ({
    ...p,
    [chiave]: p[chiave].map((v, i) => (i === indice ? { ...v, ...patch } : v)),
  });
}

function contaBullet(p: MasterProfile): number {
  return p.experiences.reduce((n, e) => n + e.bullets.length, 0);
}

function nuovaEsperienza(p: MasterProfile): Experience {
  return {
    id: nuovoId("nuova-esperienza", idInUso(p)),
    company: "",
    role: "",
    location: null,
    work_mode: "unknown",
    employment_type: null,
    start: new Date().toISOString().slice(0, 7),
    end: null,
    bullets: [],
    tech: [],
  };
}

function nuovaFormazione(p: MasterProfile): Education {
  return {
    id: nuovoId("nuovo-titolo", idInUso(p)),
    institution: "",
    degree: "",
    field_of_study: null,
    start: null,
    end: null,
    grade: null,
    highlights: [],
  };
}

function nuovoProgetto(p: MasterProfile): Project {
  return {
    id: nuovoId("nuovo-progetto", idInUso(p)),
    name: "",
    description: "",
    url: null,
    tech: [],
    context: "personal",
  };
}

function nuovaCertificazione(p: MasterProfile): Certification {
  return {
    id: nuovoId("nuova-certificazione", idInUso(p)),
    name: "",
    issuer: null,
    issued: null,
    expires: null,
    credential_url: null,
  };
}
