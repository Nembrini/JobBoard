"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, Loader2, TriangleAlert } from "lucide-react";

import { confermaProfilo } from "@/lib/profile-actions";

/**
 * Il profilo estratto ma non ancora confermato.
 *
 * **Il matching non gira finché non lo si conferma.** È il guardrail della Fase
 * 1.3: un'estrazione automatica non è una revisione, e un profilo strutturato
 * male non produce punteggi sbagliati in modo visibile — produce punteggi
 * plausibili e sbagliati, che è molto peggio.
 *
 * L'avviso è quindi anche un blocco, e dirlo qui evita la domanda che
 * arriverebbe altrimenti: perché ho caricato il CV e la lista non si aggiorna.
 */
export function ConfirmBanner() {
  const router = useRouter();
  const [inCorso, setInCorso] = useState(false);
  const [errore, setErrore] = useState<string | null>(null);

  return (
    <div className="space-y-3 rounded-xl border border-amber-500/40 bg-amber-500/5 p-4">
      <p className="flex gap-3 text-sm leading-relaxed">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
        <span>
          Questo profilo è stato estratto da un LLM e <strong>non è ancora confermato</strong>:
          finché non lo è, il matching non valuta annunci nuovi. Rileggi le voci qui sotto —
          soprattutto date, aziende e i punti senza risultato — e poi confermalo.
        </span>
      </p>
      <div className="flex flex-wrap items-center gap-3 pl-7">
        <button
          type="button"
          disabled={inCorso}
          onClick={async () => {
            setErrore(null);
            setInCorso(true);
            const esito = await confermaProfilo();
            setInCorso(false);
            if (esito.ok) router.refresh();
            else setErrore(esito.errore);
          }}
          className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium disabled:opacity-60"
        >
          {inCorso ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          Ho riletto: conferma il profilo
        </button>
        {errore ? (
          <span role="alert" className="text-destructive text-sm">
            {errore}
          </span>
        ) : null}
      </div>
    </div>
  );
}
