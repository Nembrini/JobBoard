"use client";

import { useState, useTransition } from "react";
import { CircleCheck, CircleAlert } from "lucide-react";

import { salvaTracciamento } from "@/lib/settings-actions";
import type { TrackingSettings } from "@/lib/tracking-settings";

/**
 * Il form della sezione Tracciamento email (Fase 9): attivazione e giorni di
 * silenzio prima di un promemoria. Stesso pattern di `NotificationsForm`:
 * stato locale, submit esplicito.
 */
export function TrackingForm({ iniziale }: { iniziale: TrackingSettings }) {
  const [valori, setValori] = useState(iniziale);
  const [pending, startTransition] = useTransition();
  const [esito, setEsito] = useState<{ ok: boolean; messaggio: string } | null>(null);

  function salva() {
    setEsito(null);
    startTransition(async () => {
      const risultato = await salvaTracciamento(valori);
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
          <p className="font-medium">Controllo email</p>
          <p className="text-muted-foreground mt-1 max-w-md text-sm leading-relaxed">
            Legge le risposte dei recruiter nella stessa casella del digest, aggiorna lo stato
            della candidatura e segnala un follow-up dopo un silenzio prolungato. Richiede{" "}
            <span className="num">GMAIL_APP_PASSWORD</span> configurata nel worker, come il digest.
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

      <label className="block max-w-xs space-y-1.5 text-sm">
        <span className="font-medium">
          Promemoria dopo <span className="num">{valori.follow_up_after_days}</span> giorni di
          silenzio
        </span>
        <input
          type="range"
          min={3}
          max={30}
          step={1}
          value={valori.follow_up_after_days}
          onChange={(e) =>
            setValori((v) => ({ ...v, follow_up_after_days: Number(e.target.value) }))
          }
          className="block w-full"
        />
        <span className="text-muted-foreground block text-xs">
          Nessuna risposta classificata entro questi giorni dall&apos;invio: la candidatura compare
          in Candidature con un promemoria, e — se il controllo email è attivo — arriva una mail.
        </span>
      </label>

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
