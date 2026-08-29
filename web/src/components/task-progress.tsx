"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, CircleCheck, Loader2 } from "lucide-react";

import type { TaskType } from "@/db/schema";
import type { StatoTask } from "@/lib/tasks";

/**
 * Lo stato di un lavoro chiesto al worker: in coda, in corso, fatto, errore.
 *
 * Uno solo per tutti i tipi di task. Il motivo non è il riuso in sé, è che le
 * quattro frasi difficili sono sempre le stesse: **"in coda" con il worker
 * spento non è un errore**, un errore che tornerà in coda non è un fallimento,
 * e "fatto" senza dire cosa è stato fatto lascia comunque a chi guarda il
 * dubbio se valga la pena ricaricare. Scritte una volta, valgono per il CV
 * come per la raccolta.
 *
 * Il polling interroga `/api/tasks`, non `router.refresh()`: la dashboard fa
 * tre query e ricaricarla ogni pochi secondi per muovere una barra sarebbe un
 * carico ricorrente su Supabase per un dato che sta in una riga sola. Il
 * refresh vero si fa **una volta**, quando il lavoro finisce e c'è davvero
 * qualcosa di nuovo da mostrare.
 */

/** Cadenza del polling. Il worker riscrive il progresso a ogni passo della
 *  pipeline — una manciata di volte al minuto — quindi guardare più spesso
 *  aggiungerebbe richieste senza aggiungere informazione. */
const OGNI_MS = 4000;

type Testi = {
  inCoda: string;
  inCodaOffline: string;
  inCorso: string;
};

const TESTI: Record<TaskType, Testi> = {
  run_pipeline: {
    inCoda: "Raccolta in coda: il worker la prende entro mezzo minuto.",
    inCodaOffline: "Raccolta in coda. Il PC di casa è spento: parte da sola alla riaccensione.",
    inCorso: "Raccolta in corso.",
  },
  reparse_profile: {
    inCoda: "In coda: il worker rilegge il CV entro mezzo minuto.",
    inCodaOffline: "In coda. Il PC di casa è spento: parte da solo alla riaccensione.",
    inCorso: "Il worker sta rileggendo il CV.",
  },
  generate_cv: {
    inCoda: "CV su misura in coda.",
    inCodaOffline: "CV su misura in coda. Il PC di casa è spento: parte alla riaccensione.",
    inCorso: "Sto generando il CV.",
  },
  apply: {
    inCoda: "Candidatura in coda.",
    inCodaOffline: "Candidatura in coda. Il PC di casa è spento: parte alla riaccensione.",
    inCorso: "Invio della candidatura in corso.",
  },
  check_email: {
    inCoda: "Controllo della posta in coda.",
    inCodaOffline: "Controllo della posta in coda: parte alla riaccensione del PC.",
    inCorso: "Sto leggendo le risposte.",
  },
};

export function TaskProgress({
  iniziale,
  workerOnline,
  riepilogo,
  compatto = false,
}: {
  /** Lo stato letto dal server al primo render: la UI è giusta già nell'HTML. */
  iniziale: StatoTask | null;
  workerOnline: boolean;
  /** Come raccontare `task.result`. Senza, a fine lavoro si scrive solo "fatto". */
  riepilogo?: (result: Record<string, unknown>) => string;
  /** Dentro una scheda che ha già un bordo, la riga non ne mette un altro. */
  compatto?: boolean;
}) {
  const router = useRouter();
  const [stato, setStato] = useState(iniziale);
  const [ultimoDalServer, setUltimoDalServer] = useState(iniziale);
  // A quale task è già stato dedicato un `router.refresh()`. Parte già
  // "consumato" se il server ci consegna un lavoro concluso: quello è successo
  // prima che questa pagina esistesse, e i suoi dati sono già nell'HTML.
  const rinfrescatoPer = useRef(iniziale?.status === "done" ? iniziale.id : null);

  // Il server è la fonte di verità. Riallineare durante il render invece che in
  // un effetto evita il lampeggio di un valore vecchio, ed è il caso previsto
  // da React per uno stato derivato da una prop.
  if (iniziale?.id !== ultimoDalServer?.id || iniziale?.status !== ultimoDalServer?.status) {
    setUltimoDalServer(iniziale);
    setStato(iniziale);
  }

  const idAperto =
    stato && (stato.status === "pending" || stato.status === "running") ? stato.id : null;

  const leggi = useCallback(async (id: number) => {
    const risposta = await fetch(`/api/tasks?id=${id}`, { cache: "no-store" });
    if (!risposta.ok) return null;
    const dati = (await risposta.json()) as { task: StatoTask | null };
    return dati.task;
  }, []);

  useEffect(() => {
    if (idAperto === null) return;
    const id = idAperto;
    let fermato = false;

    async function guarda() {
      // Una scheda in secondo piano — il telefono in tasca — non ha una barra
      // da aggiornare: continuare a chiedere sarebbe carico su Supabase per un
      // pixel che nessuno sta guardando. Al ritorno in primo piano il primo
      // giro riallinea tutto.
      if (document.visibilityState !== "visible") return;

      const aggiornato = await leggi(id);
      if (fermato || !aggiornato) return;

      setStato(aggiornato);
      if (aggiornato.status === "done" && rinfrescatoPer.current !== aggiornato.id) {
        // Una volta sola, alla fine: ora i dati del server sono cambiati
        // davvero, e questo è il momento in cui vale la pena rileggerli.
        rinfrescatoPer.current = aggiornato.id;
        router.refresh();
      }
    }

    const timer = setInterval(guarda, OGNI_MS);
    document.addEventListener("visibilitychange", guarda);
    return () => {
      fermato = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", guarda);
    };
  }, [idAperto, leggi, router]);

  if (!stato) return null;

  const testi = TESTI[stato.tipo];
  const cornice = compatto ? "border-t px-5 py-3" : "rounded-xl border px-4 py-3";

  if (stato.status === "pending") {
    // `attempts > 0` vuol dire che un tentativo è già fallito e la coda lo sta
    // riprovando. Mostrarlo come una normale attesa nasconderebbe l'unica cosa
    // che spiega perché ci sta mettendo così tanto.
    const riprova = stato.attempts > 0;
    return (
      <Riga classe={cornice} icona={<Loader2 className="size-4 shrink-0 animate-spin" />}>
        {riprova
          ? `Tentativo ${stato.attempts + 1} di ${stato.maxAttempts} dopo un errore: ${stato.error ?? "causa non registrata"}`
          : workerOnline
            ? testi.inCoda
            : testi.inCodaOffline}
      </Riga>
    );
  }

  if (stato.status === "running") {
    return (
      <div className={cornice}>
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="size-4 shrink-0 animate-spin" />
          <span className="min-w-0 flex-1 truncate">
            {stato.progressMessage ?? testi.inCorso}
          </span>
          <span className="num text-foreground shrink-0">{stato.progress}%</span>
        </p>
        {/* Barra e non spinner: la raccolta più la valutazione durano diversi
            minuti, e uno spinner che gira da cinque minuti è indistinguibile da
            uno bloccato. */}
        <div
          role="progressbar"
          aria-valuenow={stato.progress}
          aria-valuemin={0}
          aria-valuemax={100}
          className="bg-muted mt-2 h-1.5 overflow-hidden rounded-full"
        >
          <div
            className="bg-primary h-full rounded-full transition-[width] duration-500"
            style={{ width: `${Math.max(2, stato.progress)}%` }}
          />
        </div>
      </div>
    );
  }

  if (stato.status === "failed") {
    return (
      <Riga
        classe={`${cornice} border-destructive/40 bg-destructive/5`}
        icona={<CircleAlert className="text-destructive mt-0.5 size-4 shrink-0" />}
        allineaInAlto
      >
        {stato.error ?? "il worker non ha detto perché."}
      </Riga>
    );
  }

  if (stato.status === "cancelled") {
    return (
      <Riga classe={cornice} icona={<CircleAlert className="size-4 shrink-0" />}>
        Annullato.
      </Riga>
    );
  }

  return (
    <Riga
      classe={cornice}
      icona={<CircleCheck className="size-4 shrink-0 text-emerald-600" />}
      allineaInAlto
    >
      {(stato.result && riepilogo?.(stato.result)) || "Fatto."}
    </Riga>
  );
}

function Riga({
  classe,
  icona,
  allineaInAlto = false,
  children,
}: {
  classe: string;
  icona: React.ReactNode;
  allineaInAlto?: boolean;
  children: React.ReactNode;
}) {
  return (
    <p
      className={`text-muted-foreground flex gap-2 text-sm leading-relaxed ${
        allineaInAlto ? "items-start" : "items-center"
      } ${classe}`}
    >
      {icona}
      <span className="min-w-0">{children}</span>
    </p>
  );
}
