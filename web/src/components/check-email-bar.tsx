"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Mail } from "lucide-react";

import { TaskProgress } from "@/components/task-progress";
import { avviaControlloEmail } from "@/lib/task-actions";
import type { StatoTask } from "@/lib/tasks";

/**
 * "Controlla posta adesso" (Fase 9): come `RefreshBar`, ma per `check_email`.
 *
 * Serve per due momenti che altrimenti aspetterebbero la run notturna: appena
 * acceso il tracciamento nelle Impostazioni, o subito dopo aver corretto uno
 * stato a mano e voler vedere se nel frattempo è arrivato qualcosa di nuovo.
 */
export function CheckEmailBar({
  taskIniziale,
  workerOnline,
}: {
  taskIniziale: StatoTask | null;
  workerOnline: boolean;
}) {
  const router = useRouter();
  const [task, setTask] = useState(taskIniziale);
  const [ultimoDalServer, setUltimoDalServer] = useState(taskIniziale);
  const [errore, setErrore] = useState<string | null>(null);
  const [nota, setNota] = useState<string | null>(null);
  const [inCorso, startTransition] = useTransition();

  if (taskIniziale?.id !== ultimoDalServer?.id || taskIniziale?.status !== ultimoDalServer?.status) {
    setUltimoDalServer(taskIniziale);
    setTask(taskIniziale);
  }

  const aperto = task?.status === "pending" || task?.status === "running";

  function avvia() {
    setErrore(null);
    setNota(null);
    startTransition(async () => {
      const esito = await avviaControlloEmail();
      if (!esito.ok) {
        setErrore(esito.errore);
        return;
      }
      if (esito.giaInCoda) setNota("Un controllo era già in coda: è lo stesso.");
      setTask({
        id: esito.id,
        tipo: "check_email",
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

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={avvia}
        disabled={inCorso || aperto}
        className="border-input hover:bg-accent inline-flex h-10 items-center gap-2 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
      >
        <Mail className="size-4" />
        Controlla posta adesso
      </button>

      {errore ? (
        <p role="alert" className="text-destructive text-sm">
          {errore}
        </p>
      ) : nota ? (
        <p className="text-muted-foreground text-sm">{nota}</p>
      ) : null}

      <TaskProgress
        iniziale={task}
        workerOnline={workerOnline}
        riepilogo={riepilogoControllo}
        compatto
      />
    </div>
  );
}

function riepilogoControllo(result: Record<string, unknown>): string {
  if (result.attivo === false) {
    return "Tracciamento disattivato nelle Impostazioni: nessuna casella aperta.";
  }
  const controllate = intero(result.candidature_controllate);
  const nuove = intero(result.mail_nuove);
  const cambi = intero(result.cambi_stato);
  const promemoria = intero(result.promemoria_inviati);

  const parti = [
    `${controllate} candidature controllate`,
    nuove === 0 ? "nessuna mail nuova" : `${nuove} mail nuove`,
    `${cambi} cambi di stato`,
  ];
  if (promemoria > 0) parti.push(`${promemoria} promemoria inviati`);

  return `${parti.join(" · ")}.`;
}

function intero(valore: unknown): number {
  return typeof valore === "number" && Number.isFinite(valore) ? valore : 0;
}
