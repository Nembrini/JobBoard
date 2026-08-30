"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Check, Download, RefreshCw, Send, Sparkles } from "lucide-react";

import { TaskProgress } from "@/components/task-progress";
import type { CvGenerato, StatoInvio } from "@/lib/applications";
import { approvaCandidatura, generaCv, inviaCandidatura, segnaCandidaturaInviata } from "@/lib/cv-actions";
import type { StatoTask } from "@/lib/tasks";

/**
 * Il CV su misura di un annuncio: anteprima, diff e le due decisioni.
 *
 * **Il diff è la parte che conta.** Il PDF si può già aprire; quello che non si
 * può fare guardando un PDF è sapere *da dove viene* ogni frase. Il validatore
 * del worker garantisce che ogni bullet risalga a una voce del CV master e che
 * nessuna cifra sia inventata, ma è una garanzia che va vista almeno una volta
 * per essere creduta. Qui ogni frase riscritta sta accanto alla sua originale.
 *
 * Le cinque keyword sono evidenziate nel testo e non elencate a parte: quello
 * che serve sapere non è quali sono — è **se il CV le dice davvero**, e un
 * elenco in cima alla pagina non risponde a quella domanda.
 */
export function CvPanel({
  matchId,
  cv,
  taskIniziale,
  applyTaskIniziale,
  statoInvio,
  workerOnline,
  pdfUrl,
}: {
  matchId: number;
  cv: CvGenerato | null;
  taskIniziale: StatoTask | null;
  applyTaskIniziale: StatoTask | null;
  statoInvio: StatoInvio | null;
  workerOnline: boolean;
  pdfUrl: string | null;
}) {
  const router = useRouter();
  const [task, setTask] = useState(taskIniziale);
  const [ultimoDalServer, setUltimoDalServer] = useState(taskIniziale);
  const [applyTask, setApplyTask] = useState(applyTaskIniziale);
  const [ultimoApplyDalServer, setUltimoApplyDalServer] = useState(applyTaskIniziale);
  const [errore, setErrore] = useState<string | null>(null);
  const [erroreInvio, setErroreInvio] = useState<string | null>(null);
  const [chiedeConfermaAzienda, setChiedeConfermaAzienda] = useState(false);
  const [approvato, setApprovato] = useState(cv?.status === "approved");
  const [inCorso, startTransition] = useTransition();
  const [invioInCorso, startInvio] = useTransition();

  // Come nelle altre barre: quando il server manda uno stato diverso vince lui.
  if (taskIniziale?.id !== ultimoDalServer?.id || taskIniziale?.status !== ultimoDalServer?.status) {
    setUltimoDalServer(taskIniziale);
    setTask(taskIniziale);
  }
  if (
    applyTaskIniziale?.id !== ultimoApplyDalServer?.id ||
    applyTaskIniziale?.status !== ultimoApplyDalServer?.status
  ) {
    setUltimoApplyDalServer(applyTaskIniziale);
    setApplyTask(applyTaskIniziale);
  }

  const aperto = task?.status === "pending" || task?.status === "running";
  const invioAperto = applyTask?.status === "pending" || applyTask?.status === "running";

  function genera() {
    setErrore(null);
    startTransition(async () => {
      const esito = await generaCv(matchId);
      if (!esito.ok) {
        setErrore(esito.errore);
        return;
      }
      setTask({
        id: esito.taskId,
        tipo: "generate_cv",
        status: "pending",
        progress: 0,
        progressMessage: null,
        error: null,
        result: null,
        createdAt: new Date().toISOString(),
        finishedAt: null,
        attempts: 0,
        maxAttempts: 3,
      });
      router.refresh();
    });
  }

  function approva() {
    setErrore(null);
    startTransition(async () => {
      const esito = await approvaCandidatura(matchId);
      if (!esito.ok) {
        setErrore(esito.errore);
        return;
      }
      setApprovato(true);
      router.refresh();
    });
  }

  /** "Invia candidatura": accoda la preparazione. Puo' fermarsi a chiedere conferma. */
  function invia(confermaNuovaAzienda = false) {
    setErroreInvio(null);
    startInvio(async () => {
      const esito = await inviaCandidatura(matchId, confermaNuovaAzienda);
      if (!esito.ok) {
        if (esito.richiedeConfermaAzienda) {
          setChiedeConfermaAzienda(true);
          return;
        }
        setErroreInvio(esito.errore);
        return;
      }
      setChiedeConfermaAzienda(false);
      setApplyTask({
        id: esito.taskId,
        tipo: "apply",
        status: "pending",
        progress: 0,
        progressMessage: null,
        error: null,
        result: null,
        createdAt: new Date().toISOString(),
        finishedAt: null,
        attempts: 0,
        maxAttempts: 3,
      });
      router.refresh();
    });
  }

  /** "Segna come inviata": solo dopo che l'hai spedita tu nel browser. */
  function segnaInviata() {
    setErroreInvio(null);
    startInvio(async () => {
      const esito = await segnaCandidaturaInviata(matchId);
      if (!esito.ok) {
        setErroreInvio(esito.errore);
        return;
      }
      router.refresh();
    });
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-heading text-base font-semibold tracking-tight">CV su misura</h2>
        <div className="flex flex-wrap items-center gap-2">
          {pdfUrl ? (
            <a
              href={pdfUrl}
              className="border-input hover:bg-accent inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium"
            >
              <Download className="size-4" />
              Scarica
            </a>
          ) : null}

          <button
            type="button"
            onClick={genera}
            disabled={inCorso || aperto}
            className="border-input hover:bg-accent inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium disabled:opacity-50"
          >
            {cv ? <RefreshCw className="size-4" /> : <Sparkles className="size-4" />}
            {cv ? "Rigenera" : "Genera"}
          </button>

          {cv ? (
            <button
              type="button"
              onClick={approva}
              disabled={inCorso || approvato || cv.status !== "cv_ready"}
              className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-9 items-center gap-2 rounded-lg px-4 text-sm font-medium disabled:opacity-40"
            >
              <Check className="size-4" />
              {approvato ? "Approvato" : "Approva"}
            </button>
          ) : null}

          {statoInvio?.status === "approved" ? (
            <button
              type="button"
              onClick={() => invia(false)}
              disabled={invioInCorso || invioAperto}
              className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-9 items-center gap-2 rounded-lg px-4 text-sm font-medium disabled:opacity-40"
            >
              <Send className="size-4" />
              Invia candidatura
            </button>
          ) : null}

          {statoInvio?.status === "needs_human" ? (
            <button
              type="button"
              onClick={segnaInviata}
              disabled={invioInCorso}
              className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-9 items-center gap-2 rounded-lg px-4 text-sm font-medium disabled:opacity-40"
            >
              <Check className="size-4" />
              Segna come inviata
            </button>
          ) : null}
        </div>
      </div>

      {errore ? (
        <p role="alert" className="text-destructive text-sm">
          {errore}
        </p>
      ) : null}

      <TaskProgress
        iniziale={task}
        workerOnline={workerOnline}
        riepilogo={riepilogoGenerazione}
      />

      {erroreInvio ? (
        <p role="alert" className="text-destructive text-sm">
          {erroreInvio}
        </p>
      ) : null}

      {chiedeConfermaAzienda ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
          <p className="text-muted-foreground">
            È la prima candidatura verso questa azienda: confermi che il worker apra il browser e
            prepari il form?
          </p>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={() => invia(true)}
              disabled={invioInCorso}
              className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-8 items-center rounded-lg px-3 text-sm font-medium disabled:opacity-40"
            >
              Conferma
            </button>
            <button
              type="button"
              onClick={() => setChiedeConfermaAzienda(false)}
              className="border-input hover:bg-accent inline-flex h-8 items-center rounded-lg border px-3 text-sm font-medium"
            >
              Annulla
            </button>
          </div>
        </div>
      ) : null}

      <TaskProgress iniziale={applyTask} workerOnline={workerOnline} riepilogo={riepilogoInvio} />

      {statoInvio?.status === "needs_human" ? (
        <p className="text-muted-foreground bg-muted/40 rounded-xl p-4 text-sm leading-relaxed">
          Il worker ha aperto il form (tier {statoInvio.tier}) e si è fermato prima di inviarlo:
          controllalo sullo schermo del PC e premi invia <strong>tu, nel browser</strong>. Poi
          torna qui e premi <strong>Segna come inviata</strong>.
        </p>
      ) : null}

      {cv === null ? (
        <p className="text-muted-foreground bg-muted/40 rounded-xl p-4 text-sm leading-relaxed">
          Nessun CV per questo annuncio. Generarlo riscrive summary, punti e competenze sulle
          parole di questa offerta, <strong>senza aggiungere niente</strong> che non sia già nel
          tuo CV: quello che il profilo non dice, il CV non lo dirà.
          {workerOnline
            ? null
            : " Il worker non risulta attivo: il lavoro resta in coda e parte da solo non appena riparte."}
        </p>
      ) : (
        <Contenuto cv={cv} pdfUrl={pdfUrl} />
      )}
    </section>
  );
}

function Contenuto({ cv, pdfUrl }: { cv: CvGenerato; pdfUrl: string | null }) {
  return (
    <div className="space-y-5">
      <p className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="text-foreground font-medium">{STATO[cv.status] ?? cv.status}</span>
        {cv.lingua ? <span>lingua {cv.lingua.toUpperCase()}</span> : null}
        {cv.compressioni ? (
          // Un numero alto qui dice che il CV master ha piu' contenuto di quanto
          // ne regga una pagina: e' un'informazione sul profilo, non sul CV.
          <span>{cv.compressioni} compressioni per stare in una pagina</span>
        ) : null}
      </p>

      {cv.keywords.length ? (
        <p className="text-muted-foreground text-sm">
          Parole su cui punta:{" "}
          {cv.keywords.map((parola, i) => (
            <span key={parola}>
              {i > 0 ? ", " : ""}
              <mark className="rounded bg-amber-200/60 px-1 dark:bg-amber-500/25">{parola}</mark>
            </span>
          ))}
        </p>
      ) : null}

      {pdfUrl ? (
        <object
          data={pdfUrl}
          type="application/pdf"
          // Alto quanto una A4 a questa larghezza. Un'anteprima piu' bassa
          // costringerebbe a scorrere dentro un riquadro dentro una pagina che
          // gia' scorre, che e' il modo piu' rapido di rendere inutile
          // un'anteprima.
          className="h-[36rem] w-full rounded-xl border"
          aria-label="Anteprima del CV generato"
        >
          <p className="text-muted-foreground p-4 text-sm">
            Il browser non mostra i PDF qui dentro.{" "}
            <a className="underline" href={pdfUrl}>
              Aprilo in una scheda
            </a>
            .
          </p>
        </object>
      ) : null}

      <Diff cv={cv} />
    </div>
  );
}

/**
 * Il confronto fra quello che c'era e quello che è stato scritto.
 *
 * Una colonna sola su telefono, due su schermo largo, commutate dalle media
 * query e non da JavaScript — come la tabella degli annunci.
 */
function Diff({ cv }: { cv: CvGenerato }) {
  return (
    <div className="space-y-4">
      <h3 className="text-muted-foreground text-sm">
        Da dove viene ogni frase — a sinistra il tuo CV, a destra questa versione
      </h3>

      {cv.summary ? (
        <Coppia
          titolo="Presentazione"
          originale={cv.summaryOriginale}
          // Il summary è l'unico pezzo che può non avere un originale senza che
          // niente sia andato storto: molti CV non hanno una presentazione, e
          // questo ne scrive una nuova per ogni annuncio. Dirlo come si dice per
          // i bullet — "la voce non c'è più" — segnalerebbe un guasto inesistente.
          mancante="Il tuo CV non ha una presentazione: questa è scritta per questo annuncio."
          riscritto={cv.summary}
          keywords={cv.keywords}
        />
      ) : null}

      {cv.esperienze.map((esperienza) => (
        <div key={esperienza.id} className="space-y-2">
          <p className="text-sm font-medium">
            {esperienza.ruolo}
            {esperienza.azienda ? ` — ${esperienza.azienda}` : ""}
          </p>
          {esperienza.bullets.map((bullet, i) => (
            <Coppia
              key={`${bullet.sourceId}-${i}`}
              originale={bullet.originale}
              riscritto={bullet.testo}
              keywords={cv.keywords}
            />
          ))}
        </div>
      ))}

      {cv.skills.hard.length || cv.skills.soft.length ? (
        <div className="space-y-1">
          <p className="text-sm font-medium">Competenze</p>
          <p className="text-sm leading-relaxed">
            <Evidenziato testo={[...cv.skills.hard, ...cv.skills.soft].join(" · ")} keywords={cv.keywords} />
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Coppia({
  titolo,
  originale,
  riscritto,
  keywords,
  mancante = "La voce di origine non è più nel profilo: rigenera per riallineare.",
}: {
  titolo?: string;
  originale: string | null;
  riscritto: string;
  keywords: string[];
  /** Cosa scrivere quando l'originale non c'è. Il perché cambia il messaggio. */
  mancante?: string;
}) {
  return (
    <div className="space-y-1">
      {titolo ? <p className="text-sm font-medium">{titolo}</p> : null}
      <div className="grid gap-2 sm:grid-cols-2">
        <p className="text-muted-foreground bg-muted/40 rounded-lg p-3 text-sm leading-relaxed">
          {/* Sul bullet, un originale assente significa che il profilo è
              cambiato dopo la generazione: si dice, invece di far sparire la
              riga, perché è il caso in cui vale la pena rigenerare. */}
          {originale ?? <span className="italic">{mancante}</span>}
        </p>
        <p className="rounded-lg border p-3 text-sm leading-relaxed">
          <Evidenziato testo={riscritto} keywords={keywords} />
        </p>
      </div>
    </div>
  );
}

/**
 * Il testo con le keyword evidenziate.
 *
 * Si costruisce un array di nodi e non una stringa di HTML: il testo arriva da
 * un modello che ha letto una job description scaricata da internet, e
 * `dangerouslySetInnerHTML` su quel percorso sarebbe un XSS con tre passaggi di
 * distanza.
 */
function Evidenziato({ testo, keywords }: { testo: string; keywords: string[] }) {
  const pulite = keywords.map((k) => k.trim()).filter(Boolean);
  if (!pulite.length) return <>{testo}</>;

  const pattern = new RegExp(`(${pulite.map(escapeRegex).join("|")})`, "gi");
  const pezzi = testo.split(pattern);

  return (
    <>
      {pezzi.map((pezzo, i) =>
        // `split` con un gruppo di cattura alterna testo e corrispondenze: le
        // posizioni dispari sono le keyword.
        i % 2 === 1 ? (
          <mark key={i} className="rounded bg-amber-200/60 px-0.5 dark:bg-amber-500/25">
            {pezzo}
          </mark>
        ) : (
          <span key={i}>{pezzo}</span>
        ),
      )}
    </>
  );
}

function escapeRegex(testo: string): string {
  return testo.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const STATO: Record<string, string> = {
  draft: "In preparazione",
  cv_ready: "Pronto da rivedere",
  approved: "Approvato, in attesa di invio",
  needs_human: "Serve il tuo intervento",
  submitted: "Candidatura inviata",
  failed: "Invio non riuscito",
  withdrawn: "Ritirata",
  acknowledged: "Ricevuta confermata",
  interview: "Colloquio",
  rejected: "Rifiutata",
  offer: "Offerta",
};

/** Il `result` del task, in una frase. */
function riepilogoGenerazione(result: Record<string, unknown>): string {
  const pagine = typeof result.pages === "number" ? result.pages : 1;
  const tentativi = typeof result.attempts === "number" ? result.attempts : 1;
  const lingua = typeof result.language === "string" ? result.language.toUpperCase() : "";

  const parti = [`CV pronto in ${lingua || "?"}`, pagine === 1 ? "una pagina" : `${pagine} pagine`];
  if (tentativi > 1) {
    // Vale la pena dirlo: un CV che ha richiesto tre tentativi e' passato
    // comunque dal validatore, ma dice qualcosa su quanto il modello stia
    // forzando la mano su questo annuncio.
    parti.push(`${tentativi} tentativi prima di superare il controllo`);
  }
  return `${parti.join(" · ")}.`;
}

/** Il `result` del task `apply`, in una frase — vedi `apply_to_job` nel worker. */
function riepilogoInvio(result: Record<string, unknown>): string {
  const tier = typeof result.tier === "string" ? result.tier : "?";

  if (result.dry_run) return `Dry-run (tier ${tier}): nessun browser aperto.`;
  if (tier === "c_manual") return "Nessun form diretto: apri il link e candidati a mano.";

  const compilati = Array.isArray(result.fields_filled) ? result.fields_filled.length : 0;
  const cv = result.resume_uploaded ? "CV caricato" : "CV non caricato: caricalo tu";
  return `Form pronto (tier ${tier}): ${compilati} campi compilati, ${cv}.`;
}
