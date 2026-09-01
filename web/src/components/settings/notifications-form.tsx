"use client";

import { useState, useTransition } from "react";
import { CircleCheck, CircleAlert } from "lucide-react";

import { salvaNotifiche } from "@/lib/settings-actions";
import type { NotificationSettings } from "@/lib/notifications";

/**
 * Il form della pagina Impostazioni: attivazione, soglia e orario del digest (Fase 8.4).
 *
 * Uno stato locale che parte da quello salvato e si aggiorna con un submit
 * esplicito — non un salvataggio a ogni digitazione, che per una preferenza
 * che decide se una mail parte da sola sarebbe più sorprendente che comodo.
 */
export function NotificationsForm({ iniziale }: { iniziale: NotificationSettings }) {
  const [valori, setValori] = useState(iniziale);
  const [pending, startTransition] = useTransition();
  const [esito, setEsito] = useState<{ ok: boolean; messaggio: string } | null>(null);

  function salva() {
    setEsito(null);
    startTransition(async () => {
      const risultato = await salvaNotifiche(valori);
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
          <p className="font-medium">Digest email</p>
          <p className="text-muted-foreground mt-1 max-w-md text-sm leading-relaxed">
            A fine raccolta, un&apos;email con i nuovi annunci sopra soglia — solo quando ce n&apos;è
            almeno uno. Richiede <span className="num">GMAIL_APP_PASSWORD</span> configurata nel
            worker.
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
            className={`absolute top-1 left-0 size-5 rounded-full bg-white shadow transition-transform ${
              valori.enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">
            Punteggio minimo: <span className="num">{valori.threshold}</span>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={valori.threshold}
            onChange={(e) => setValori((v) => ({ ...v, threshold: Number(e.target.value) }))}
            className="block w-full"
          />
          <span className="text-muted-foreground block text-xs">
            Solo gli annunci nuovi con un punteggio pari o superiore entrano nel digest.
          </span>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Orario preferito</span>
          <select
            value={valori.hour}
            onChange={(e) => setValori((v) => ({ ...v, hour: Number(e.target.value) }))}
            className="border-input bg-background block h-10 w-full rounded-lg border px-2.5"
          >
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, "0")}:00
              </option>
            ))}
          </select>
          <span className="text-muted-foreground block text-xs">
            Solo una preferenza registrata: la raccolta parte davvero all&apos;orario
            dell&apos;attività di Task Scheduler sul PC (<span className="num">.\setup-scheduler</span>{" "}
            la crea alle 07:00). Cambiarlo qui non sposta quell&apos;attività.
          </span>
        </label>
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
            {esito.ok ? (
              <CircleCheck className="size-4" />
            ) : (
              <CircleAlert className="size-4" />
            )}
            {esito.messaggio}
          </span>
        ) : null}
      </div>
    </div>
  );
}
