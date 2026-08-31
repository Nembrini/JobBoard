"use client";

import { useState, useTransition } from "react";
import { CircleCheck, CircleAlert } from "lucide-react";

import { salvaAvvioAutomatico } from "@/lib/settings-actions";
import type { AutoWorkerSettings } from "@/lib/auto-worker-settings";

/**
 * Il form della sezione Avvio automatico: un solo interruttore, stesso
 * pattern di `NotificationsForm` e `TrackingForm`.
 *
 * Acceso di default, non spento come le altre due sezioni: qui non si sta
 * scegliendo se accendere qualcosa di nuovo, ma se lasciare attivo quello che
 * `.\setup-scheduler` fa già da quando è stato lanciato una volta. Non c'è
 * altro da configurare: l'orario e la cadenza restano dell'attività di Task
 * Scheduler, questo interruttore decide solo se il tick può reclamare un
 * task o deve lasciarlo in coda.
 */
export function AutoWorkerForm({ iniziale }: { iniziale: AutoWorkerSettings }) {
  const [valori, setValori] = useState(iniziale);
  const [pending, startTransition] = useTransition();
  const [esito, setEsito] = useState<{ ok: boolean; messaggio: string } | null>(null);

  function salva() {
    setEsito(null);
    startTransition(async () => {
      const risultato = await salvaAvvioAutomatico(valori);
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-medium">Avvio automatico</p>
          <p className="text-muted-foreground mt-1 max-w-md text-sm leading-relaxed">
            Con &quot;Aggiorna adesso&quot; o &quot;Rivaluta tutto&quot;: il worker si accende da solo
            entro un minuto, esegue quel lavoro e si spegne — senza aprire un terminale sul PC. Vale anche
            per la raccolta giornaliera automatica. Richiede{" "}
            <span className="num">.\setup-scheduler</span> già eseguito una volta sul PC — senza,
            questo interruttore non ha niente da accendere. Spento, ogni richiesta resta in coda
            finché non lanci <span className="num">.\jb work</span> a mano.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={valori.enabled}
          onClick={() => setValori((v) => ({ ...v, enabled: !v.enabled }))}
          className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${
            valori.enabled ? "bg-primary" : "bg-muted"
          }`}
        >
          <span
            className={`absolute top-1 size-5 rounded-full bg-white shadow transition-transform ${
              valori.enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
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
