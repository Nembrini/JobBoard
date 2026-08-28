"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { EyeOff, Loader2, Send, Star } from "lucide-react";

import type { MatchStatus } from "@/db/schema";

/**
 * Le azioni di riga: shortlist, nascondi, candidati.
 *
 * È uno dei pochi frammenti interattivi della pagina. Tutto il resto —
 * tabella, filtri, punteggi — è renderizzato dal server: qui serve JavaScript
 * solo perché un click deve cambiare uno stato e rinfrescare la lista senza
 * ricaricare la pagina.
 *
 * Lo stato ottimistico è locale e viene poi confermato da `router.refresh()`:
 * su una connessione mobile lenta un bottone che non reagisce per un secondo
 * viene premuto due volte.
 */
export function RowActions({
  matchId,
  status,
  applyUrl,
  compact = false,
}: {
  matchId: number;
  status: MatchStatus;
  applyUrl: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [locale, setLocale] = useState<MatchStatus>(status);
  const [errore, setErrore] = useState(false);

  async function cambia(nuovo: MatchStatus) {
    const precedente = locale;
    setLocale(nuovo);
    setErrore(false);

    const risposta = await fetch(`/api/matches/${matchId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: nuovo }),
    }).catch(() => null);

    if (!risposta?.ok) {
      // Ripristino: lasciare la stella accesa su un salvataggio fallito
      // significa credere di aver messo in shortlist qualcosa che domani non
      // c'è più.
      setLocale(precedente);
      setErrore(true);
      return;
    }
    startTransition(() => router.refresh());
  }

  const inShortlist = locale === "shortlist";
  const dimensione = compact ? "size-8" : "size-9";

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => cambia(inShortlist ? "seen" : "shortlist")}
        disabled={pending}
        aria-pressed={inShortlist}
        aria-label={inShortlist ? "Togli dalla shortlist" : "Metti in shortlist"}
        title={inShortlist ? "Togli dalla shortlist" : "Metti in shortlist"}
        className={`${dimensione} hover:bg-accent grid place-items-center rounded-md transition-colors ${
          inShortlist ? "text-amber-500" : "text-muted-foreground"
        }`}
      >
        <Star className="size-4" fill={inShortlist ? "currentColor" : "none"} />
      </button>

      <button
        type="button"
        onClick={() => cambia("hidden")}
        disabled={pending}
        aria-label="Nascondi questo annuncio"
        title="Nascondi: non verrà più riproposto"
        className={`${dimensione} text-muted-foreground hover:bg-accent grid place-items-center rounded-md transition-colors`}
      >
        <EyeOff className="size-4" />
      </button>

      <a
        href={applyUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => {
          // Aprire l'annuncio è la prova che è stato guardato: segnarlo qui
          // evita di doverlo fare a mano, ed è il segnale su cui lavora il
          // filtro "nascondi già visti".
          if (locale === "new") void cambia("seen");
        }}
        aria-label="Apri l'annuncio originale"
        title="Apri l'annuncio originale"
        className={`${dimensione} text-muted-foreground hover:bg-accent grid place-items-center rounded-md transition-colors`}
      >
        {pending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
      </a>

      {errore ? (
        <span role="alert" className="text-destructive text-xs">
          non salvato
        </span>
      ) : null}
    </div>
  );
}
