"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ListChecks, RefreshCw } from "lucide-react";

import { TaskProgress } from "@/components/task-progress";
import { avviaRaccolta, avviaRivalutazione, type EsitoAvvio } from "@/lib/task-actions";
import type { StatoTask } from "@/lib/tasks";

/**
 * "Aggiorna adesso" e "Rivaluta tutto": chiedono al PC di casa una raccolta e
 * una valutazione — la seconda anche di ciò che era già stato valutato.
 *
 * Sono il bottone (e il suo gemello) che chiudono l'anello dell'architettura
 * split — la dashboard non può eseguire la pipeline, ma può
 * **commissionarla**. Per questo il testo accanto non parla mai di attesa in
 * secondi: dice se il worker è acceso, e quando è spento dice che il lavoro
 * parte da solo alla riaccensione. Un bottone che a PC spento restituisse un
 * errore starebbe rifiutando una richiesta perfettamente valida.
 *
 * I due bottoni condividono un solo stato di avanzamento — `run_pipeline` è
 * un tipo di task solo, la dashboard ne mostra sempre l'ultimo — quindi si
 * disabilitano a vicenda mentre uno dei due gira: due barre non ci stanno, e
 * il worker li lavorerebbe comunque in fila, mai insieme.
 */
export function RefreshBar({
  taskIniziale,
  workerOnline,
  ultimaRun,
}: {
  taskIniziale: StatoTask | null;
  workerOnline: boolean;
  ultimaRun: string | null;
}) {
  const router = useRouter();
  const [task, setTask] = useState(taskIniziale);
  const [ultimoDalServer, setUltimoDalServer] = useState(taskIniziale);
  const [errore, setErrore] = useState<string | null>(null);
  const [nota, setNota] = useState<string | null>(null);
  const [inCorso, startTransition] = useTransition();

  // Come in `TaskProgress`: quando il server manda uno stato diverso vince lui.
  // Serve soprattutto alla fine — è il refresh che segue la conclusione della
  // run a riaccendere il bottone, che altrimenti resterebbe spento per sempre.
  if (taskIniziale?.id !== ultimoDalServer?.id || taskIniziale?.status !== ultimoDalServer?.status) {
    setUltimoDalServer(taskIniziale);
    setTask(taskIniziale);
  }

  const aperto = task?.status === "pending" || task?.status === "running";

  function accoda(azione: () => Promise<EsitoAvvio>) {
    setErrore(null);
    setNota(null);
    startTransition(async () => {
      const esito = await azione();
      if (!esito.ok) {
        setErrore(esito.errore);
        return;
      }
      // Il bottone qui era acceso, ma il database sapeva di una richiesta già
      // in coda: succede col telefono e il portatile aperti insieme, o a worker
      // spento. Dirlo evita di far credere che il click non sia servito, senza
      // accodare una seconda raccolta identica.
      if (esito.giaInCoda) setNota("Una raccolta era già in coda: è la stessa.");
      // Lo stato completo lo porta il refresh del server; qui basta una riga
      // provvisoria perché la barra compaia nello stesso istante del click,
      // invece che al giro di rete dopo.
      setTask({
        id: esito.id,
        tipo: "run_pipeline",
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

  function avvia() {
    accoda(avviaRaccolta);
  }

  function rivaluta() {
    // Conferma perché il costo è reale e non ovvio dal solo testo del bottone:
    // rivaluta dalla rubrica LLM anche gli annunci già valutati, non solo i
    // nuovi — una chiamata a testa, come una raccolta molto più grande del
    // solito. Vale la pena solo dopo aver cambiato filtri o profilo.
    const confermato = window.confirm(
      "Rivaluta tutti gli annunci attivi con i filtri e il profilo attuali, non solo quelli nuovi. " +
        "Serve dopo aver cambiato filtri o profilo, e costa una chiamata LLM per ogni annuncio già valutato — " +
        "molte di più della solita raccolta. Procedere?",
    );
    if (!confermato) return;
    accoda(avviaRivalutazione);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button
          type="button"
          onClick={avvia}
          disabled={inCorso || aperto}
          className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
        >
          <RefreshCw className={`size-4 ${inCorso ? "animate-spin" : ""}`} />
          Aggiorna adesso
        </button>

        <button
          type="button"
          onClick={rivaluta}
          disabled={inCorso || aperto}
          title="Rivaluta anche gli annunci già valutati, non solo i nuovi — dopo un cambio di filtri o profilo."
          className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
        >
          <ListChecks className="size-4" />
          Rivaluta tutto
        </button>

        <p className="text-muted-foreground text-sm">
          {aperto
            ? "Una raccolta è già in corso."
            : ultimaRun
              ? `Ultima raccolta ${ultimaRun}.`
              : "Nessuna raccolta ancora registrata."}
        </p>
      </div>

      {errore ? (
        <p role="alert" className="text-destructive text-sm">
          {errore}
        </p>
      ) : nota ? (
        <p className="text-muted-foreground text-sm">{nota}</p>
      ) : null}

      <TaskProgress iniziale={task} workerOnline={workerOnline} riepilogo={riepilogoRaccolta} />
    </div>
  );
}

/**
 * Il `result` del task, tradotto in una frase.
 *
 * I numeri li produce il worker (`handlers._riepilogo`), la frase la compone
 * qui: è la UI a sapere quanto spazio ha e cosa vale la pena dire. "Nessun
 * annuncio nuovo" è un esito che va detto per esteso — è la risposta a "ha
 * funzionato?", e senza sembra che non sia successo niente.
 */
function riepilogoRaccolta(result: Record<string, unknown>): string {
  const nuovi = intero(result.annunci_nuovi);
  const valutati = intero(result.valutati);
  const sopra = intero(result.sopra_soglia);
  const soglia = intero(result.soglia);
  const cadute = Array.isArray(result.fonti_fallite) ? result.fonti_fallite.map(String) : [];

  const parti = [
    nuovi === 0 ? "Nessun annuncio nuovo" : `${nuovi} annunci nuovi`,
    `${valutati} valutati`,
    `${sopra} sopra la soglia di ${soglia}`,
  ];

  // Le fonti cadute si nominano: una raccolta magra e una fonte giù si
  // spiegano a vicenda, e senza il nome resterebbe solo la prima metà.
  if (cadute.length) parti.push(`non hanno risposto: ${cadute.join(", ")}`);

  return `${parti.join(" · ")}.`;
}

function intero(valore: unknown): number {
  return typeof valore === "number" && Number.isFinite(valore) ? valore : 0;
}
