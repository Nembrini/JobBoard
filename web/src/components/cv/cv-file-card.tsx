"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Download, FileText, Loader2, TriangleAlert, Upload } from "lucide-react";

import { TaskProgress } from "@/components/task-progress";
import { eliminaProfilo } from "@/lib/profile-actions";
import type { StatoTask } from "@/lib/tasks";

/**
 * Il CV attualmente caricato, con le due azioni che lo riguardano.
 *
 * **Sostituire non è un salvataggio, è una commissione.** Il file arriva su
 * Supabase in un secondo, ma estrarne il testo, farlo strutturare a un LLM e
 * ricalcolare l'embedding tocca al PC di casa: la scheda lo dice invece di
 * mostrare una spunta e lasciar credere che sia già fatto.
 */
export function CvFileCard({
  fileName,
  caricatoIl,
  reviewed,
  embeddingModel,
  embeddingDim,
  downloadUrl,
  workerOnline,
  taskInCorso,
}: {
  fileName: string;
  caricatoIl: string;
  reviewed: boolean;
  embeddingModel: string | null;
  embeddingDim: number | null;
  downloadUrl: string | null;
  workerOnline: boolean;
  taskInCorso: StatoTask | null;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [inCaricamento, setInCaricamento] = useState(false);
  const [errore, setErrore] = useState<string | null>(null);
  const [conferma, setConferma] = useState(false);
  const [testoConferma, setTestoConferma] = useState("");
  const [inEliminazione, setInEliminazione] = useState(false);

  async function carica(file: File) {
    setErrore(null);
    setInCaricamento(true);
    try {
      const corpo = new FormData();
      corpo.append("file", file);
      const risposta = await fetch("/api/profile/cv", { method: "POST", body: corpo });
      if (!risposta.ok) {
        const dati = (await risposta.json().catch(() => null)) as { errore?: string } | null;
        setErrore(dati?.errore ?? `caricamento fallito (${risposta.status})`);
        return;
      }
      router.refresh();
    } catch {
      setErrore("caricamento fallito: connessione interrotta");
    } finally {
      setInCaricamento(false);
      if (input.current) input.current.value = "";
    }
  }

  async function elimina() {
    setErrore(null);
    setInEliminazione(true);
    const esito = await eliminaProfilo(testoConferma);
    setInEliminazione(false);
    if (!esito.ok) {
      setErrore(esito.errore);
      return;
    }
    setConferma(false);
    router.refresh();
  }

  return (
    <div className="rounded-xl border">
      <div className="flex flex-wrap items-start gap-4 p-5">
        <span className="bg-muted text-muted-foreground grid size-11 shrink-0 place-items-center rounded-lg">
          <FileText className="size-5" />
        </span>

        <div className="min-w-0 flex-1">
          <p className="font-medium break-words">{fileName}</p>
          <p className="text-muted-foreground mt-1 text-sm">
            caricato {caricatoIl}
            {reviewed ? " · rivisto a mano" : " · non ancora rivisto"}
            {embeddingModel ? (
              <>
                {" · vettore "}
                <span className="num">{embeddingDim}d</span> con {embeddingModel}
              </>
            ) : (
              " · vettore da ricalcolare"
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {downloadUrl ? (
            <a
              href={downloadUrl}
              className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium"
            >
              <Download className="size-4" />
              Scarica
            </a>
          ) : null}

          <button
            type="button"
            onClick={() => input.current?.click()}
            disabled={inCaricamento}
            className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-60"
          >
            {inCaricamento ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            Sostituisci
          </button>

          <button
            type="button"
            onClick={() => setConferma((v) => !v)}
            className="text-muted-foreground hover:text-destructive inline-flex h-10 items-center rounded-lg px-3 text-sm font-medium"
          >
            Rimuovi
          </button>
        </div>

        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void carica(file);
          }}
        />
      </div>

      {errore ? (
        <p role="alert" className="text-destructive border-t px-5 py-3 text-sm">
          {errore}
        </p>
      ) : null}

      {/* Le quattro frasi (in coda, in corso, fatto, errore) stanno tutte in
          `TaskProgress`: erano scritte qui, ma "in coda a worker spento non è
          un errore" è una lezione che vale identica per la raccolta, e due
          copie della stessa frase divergono alla prima correzione. */}
      <TaskProgress
        iniziale={taskInCorso}
        workerOnline={workerOnline}
        riepilogo={riepilogoRilettura}
        compatto
      />

      {conferma ? (
        <div className="space-y-3 border-t px-5 py-4">
          <p className="flex gap-2.5 text-sm leading-relaxed">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
            <span>
              Rimuovere il profilo <strong>ferma il matching</strong> e cancella la revisione fatta
              a mano sul JSON, che è il passaggio più lungo della configurazione. Gli annunci già
              valutati restano, ma non se ne valutano di nuovi finché non carichi un altro CV.
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="conferma-elimina" className="text-muted-foreground text-sm">
              Scrivi <span className="num text-foreground">ELIMINA</span> per confermare:
            </label>
            <input
              id="conferma-elimina"
              value={testoConferma}
              onChange={(e) => setTestoConferma(e.target.value)}
              className="border-input bg-background num h-10 w-40 rounded-lg border px-3 text-sm"
            />
            <button
              type="button"
              onClick={elimina}
              disabled={inEliminazione || testoConferma.trim().toUpperCase() !== "ELIMINA"}
              className="bg-destructive inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium text-white disabled:opacity-40"
            >
              {inEliminazione ? <Loader2 className="size-4 animate-spin" /> : null}
              Rimuovi il profilo
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Cosa dire quando il worker ha finito di rileggere il CV.
 *
 * Il conteggio di esperienze e punti non è decorazione: è il modo più rapido di
 * accorgersi che l'estrazione ha perso metà del CV, che è l'errore che poi si
 * paga in punteggi sbagliati per mesi. La frase finale la scrive il worker
 * stesso (`next`), perché è lui a sapere che il matching resta fermo finché il
 * profilo non è confermato.
 */
function riepilogoRilettura(result: Record<string, unknown>): string {
  const esperienze = typeof result.experiences === "number" ? result.experiences : 0;
  const punti = typeof result.bullets === "number" ? result.bullets : 0;
  const coda = typeof result.next === "string" ? ` ${result.next}` : "";
  return `Riletto: ${esperienze} esperienze, ${punti} punti.${coda}`;
}

/** La stessa scheda quando non c'è ancora nessun CV. */
export function CvVuoto() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [inCaricamento, setInCaricamento] = useState(false);
  const [errore, setErrore] = useState<string | null>(null);

  async function carica(file: File) {
    setErrore(null);
    setInCaricamento(true);
    try {
      const corpo = new FormData();
      corpo.append("file", file);
      const risposta = await fetch("/api/profile/cv", { method: "POST", body: corpo });
      if (!risposta.ok) {
        const dati = (await risposta.json().catch(() => null)) as { errore?: string } | null;
        setErrore(dati?.errore ?? `caricamento fallito (${risposta.status})`);
        return;
      }
      router.refresh();
    } finally {
      setInCaricamento(false);
    }
  }

  return (
    <div className="rounded-xl border border-dashed p-10 text-center">
      <p className="font-medium">Nessun CV caricato.</p>
      <p className="text-muted-foreground mx-auto mt-1 max-w-md text-sm leading-relaxed">
        Da qui parte tutto il resto: i punteggi si calcolano su questo profilo e i CV su misura non
        potranno affermare nulla che non ci sia dentro.
      </p>
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={inCaricamento}
        className="bg-primary text-primary-foreground hover:bg-primary/90 mt-5 inline-flex h-11 items-center gap-2 rounded-lg px-5 font-medium disabled:opacity-60"
      >
        {inCaricamento ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
        Carica un CV
      </button>
      <p className="text-muted-foreground mt-3 text-xs">PDF o DOCX, fino a 10 MB.</p>
      {errore ? (
        <p role="alert" className="text-destructive mt-3 text-sm">
          {errore}
        </p>
      ) : null}
      <input
        ref={input}
        type="file"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void carica(file);
        }}
      />
    </div>
  );
}
