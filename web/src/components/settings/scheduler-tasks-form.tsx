"use client";

import { useState, useTransition } from "react";
import { CircleCheck, CircleAlert } from "lucide-react";

import { salvaAttivitaPianificate } from "@/lib/settings-actions";
import type { SchedulerTasksSettings } from "@/lib/scheduler-settings";

/**
 * Il form della sezione "Attività pianificate": tre interruttori, uno per
 * ciascuna delle attività di Task Scheduler create da `.\setup-scheduler` —
 * stesso pattern di `NotificationsForm`/`TrackingForm`, con tre switch invece
 * di uno solo e un unico "Salva" che li scrive tutti insieme.
 *
 * Accesi di default, le tre: non si sta scegliendo se accendere qualcosa di
 * nuovo, ma se lasciare attivo quello che `.\setup-scheduler` fa già da
 * quando è stato lanciato una volta. Spegnere "Worker" ferma anche i bottoni
 * "Aggiorna adesso"/"Rivaluta tutto"; spegnere raccolta o backup lascia gli
 * altri due intatti — tre interruttori indipendenti, non uno solo.
 */
export function SchedulerTasksForm({ iniziale }: { iniziale: SchedulerTasksSettings }) {
  const [valori, setValori] = useState(iniziale);
  const [pending, startTransition] = useTransition();
  const [esito, setEsito] = useState<{ ok: boolean; messaggio: string } | null>(null);

  function salva() {
    setEsito(null);
    startTransition(async () => {
      const risultato = await salvaAttivitaPianificate(valori);
      setEsito(
        risultato.ok
          ? { ok: true, messaggio: "Salvato." }
          : { ok: false, messaggio: risultato.errore },
      );
    });
  }

  const modificato = JSON.stringify(valori) !== JSON.stringify(iniziale);

  return (
    <div className="space-y-6 rounded-xl border p-5">
      <div>
        <p className="font-medium">Attività pianificate</p>
        <p className="text-muted-foreground mt-1 max-w-md text-sm leading-relaxed">
          Le tre attività di Task Scheduler create da <span className="num">.\setup-scheduler</span>{" "}
          sul PC — senza, questi interruttori non hanno niente da accendere. Ognuna gira senza
          aprire una finestra sullo schermo.
        </p>
      </div>

      <div className="space-y-5">
        <Interruttore
          etichetta="Worker (ogni minuto)"
          descrizione={
            <>
              Prende in carico &quot;Aggiorna adesso&quot;, &quot;Rivaluta tutto&quot;, la
              generazione dei CV e le candidature entro un minuto dal click, senza aprire un
              terminale. Spento, ogni richiesta resta in coda finché non lanci{" "}
              <span className="num">.\jb work</span> a mano.
            </>
          }
          acceso={valori.worker}
          onChange={(acceso) => setValori((v) => ({ ...v, worker: acceso }))}
        />
        <Interruttore
          etichetta="Raccolta giornaliera (07:00)"
          descrizione="Avvia da sola la raccolta ogni mattina, come premere Aggiorna adesso. Richiede anche il Worker acceso: senza, la raccolta si accoda ma nessuno la esegue."
          acceso={valori.trigger}
          onChange={(acceso) => setValori((v) => ({ ...v, trigger: acceso }))}
        />
        <Interruttore
          etichetta="Backup notturno (03:00)"
          descrizione="Esporta ogni tabella del database in un CSV compresso, ogni notte."
          acceso={valori.backup}
          onChange={(acceso) => setValori((v) => ({ ...v, backup: acceso }))}
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={salva}
          disabled={pending || !modificato}
          className="bg-primary text-primary-foreground inline-flex h-10 items-center rounded-lg px-4 text-sm font-medium disabled:opacity-50"
        >
          {pending ? "Salvo…" : "Salva"}
        </button>
        {esito ? (
          <span
            className={`inline-flex items-center gap-1.5 text-sm ${
              esito.ok ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"
            }`}
          >
            {esito.ok ? <CircleCheck className="size-4" /> : <CircleAlert className="size-4" />}
            {esito.messaggio}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function Interruttore({
  etichetta,
  descrizione,
  acceso,
  onChange,
}: {
  etichetta: string;
  descrizione: React.ReactNode;
  acceso: boolean;
  onChange: (acceso: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-sm font-medium">{etichetta}</p>
        <p className="text-muted-foreground mt-0.5 max-w-md text-sm leading-relaxed">
          {descrizione}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={acceso}
        aria-label={etichetta}
        onClick={() => onChange(!acceso)}
        className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${
          acceso ? "bg-primary" : "bg-muted"
        }`}
      >
        <span
          className={`absolute top-1 size-5 rounded-full bg-white shadow transition-transform ${
            acceso ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}
