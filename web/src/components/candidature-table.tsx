"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { CircleAlert } from "lucide-react";

import type { CandidaturaRow } from "@/lib/candidature";
import { cambiaStatoCandidatura } from "@/lib/candidature-actions";
import { APPLICATION_STATUS_LABEL, APPLICATION_TIER_LABEL, formatDate } from "@/lib/format";
import { ScoreBadge } from "@/components/badges";

const OPZIONI_STATO = [
  "submitted",
  "acknowledged",
  "interview",
  "rejected",
  "offer",
  "withdrawn",
] as const;

/**
 * La tabella di `/candidature` (Fase 9.1): stati aggiornabili a mano.
 *
 * Uno stato ottimistico locale, confermato da `router.refresh()` — stesso
 * pattern di `RowActions` nella tabella annunci: su una connessione lenta un
 * `<select>` che non reagisce subito viene toccato una seconda volta.
 */
export function CandidatureTable({ righe }: { righe: CandidaturaRow[] }) {
  if (righe.length === 0) {
    return (
      <p className="text-muted-foreground rounded-xl border border-dashed p-8 text-center text-sm">
        Nessuna candidatura tracciata. Compare qui una volta segnata come inviata dalla pagina
        dell&apos;annuncio.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border">
      <table className="w-full text-sm">
        <thead className="text-muted-foreground border-b text-left text-xs uppercase">
          <tr>
            <th className="px-4 py-3 font-medium">Ruolo</th>
            <th className="px-4 py-3 font-medium">Match %</th>
            <th className="px-4 py-3 font-medium">Tier</th>
            <th className="px-4 py-3 font-medium">Stato</th>
            <th className="px-4 py-3 font-medium">Inviata</th>
            <th className="px-4 py-3 font-medium">Follow-up</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {righe.map((riga) => (
            <Riga key={riga.applicationId} riga={riga} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Riga({ riga }: { riga: CandidaturaRow }) {
  const router = useRouter();
  const [stato, setStato] = useState(riga.status);
  const [pending, startTransition] = useTransition();
  const [errore, setErrore] = useState(false);

  async function cambia(nuovo: string) {
    const precedente = stato;
    setStato(nuovo as typeof stato);
    setErrore(false);

    const esito = await cambiaStatoCandidatura(riga.applicationId, nuovo);
    if (!esito.ok) {
      setStato(precedente);
      setErrore(true);
      return;
    }
    startTransition(() => router.refresh());
  }

  return (
    <tr className="hover:bg-muted/40">
      <td className="max-w-64 px-4 py-3">
        <Link
          href={`/annuncio/${riga.matchId}`}
          className="block truncate font-medium hover:underline"
          title={riga.title}
        >
          {riga.title}
        </Link>
        <span className="text-muted-foreground block truncate text-xs">{riga.company}</span>
      </td>
      <td className="px-4 py-3">
        <ScoreBadge score={riga.score} />
      </td>
      <td className="text-muted-foreground px-4 py-3 whitespace-nowrap">
        {APPLICATION_TIER_LABEL[riga.tier] ?? riga.tier}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <select
            value={stato}
            disabled={pending}
            onChange={(e) => void cambia(e.target.value)}
            className="border-input bg-background h-9 rounded-lg border px-2 text-sm"
          >
            {OPZIONI_STATO.map((opzione) => (
              <option key={opzione} value={opzione}>
                {APPLICATION_STATUS_LABEL[opzione]}
              </option>
            ))}
          </select>
          {errore ? (
            <span role="alert" title="non salvato">
              <CircleAlert className="text-destructive size-4" />
            </span>
          ) : null}
        </div>
      </td>
      <td className="text-muted-foreground px-4 py-3 whitespace-nowrap">
        {formatDate(riga.submittedAt)}
      </td>
      <td className="px-4 py-3 whitespace-nowrap">
        {riga.followUpDueAt ? (
          <span className="text-amber-700 dark:text-amber-500">{formatDate(riga.followUpDueAt)}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
    </tr>
  );
}
