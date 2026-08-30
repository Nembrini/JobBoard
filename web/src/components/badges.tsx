import type { WorkMode } from "@/db/schema";
import { formatSource, isAutoApplicable, scoreBand, WORK_MODE_LABEL } from "@/lib/format";

/**
 * I badge colorati della tabella.
 *
 * Server component senza JavaScript: sono testo con uno sfondo, e spedire un
 * bundle per disegnarli sarebbe sproporzionato.
 *
 * La pagina è per il resto acromatica di proposito: gli unici elementi con un
 * colore sono i **due giudizi** che la macchina ha espresso — dove si lavora e
 * quanto è compatibile. Aggiungere colore altrove toglierebbe a questi due il
 * significato che hanno proprio perché sono soli.
 */

const MODE_STYLE: Record<WorkMode, string> = {
  remote: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-400",
  hybrid: "bg-sky-500/12 text-sky-700 dark:text-sky-400",
  on_site: "bg-amber-500/12 text-amber-700 dark:text-amber-500",
  unknown: "bg-muted text-muted-foreground",
};

export function WorkModeBadge({ mode }: { mode: WorkMode }) {
  return (
    <span
      className={`inline-flex h-7 items-center rounded-full px-3 text-xs font-medium whitespace-nowrap ${MODE_STYLE[mode]}`}
    >
      {WORK_MODE_LABEL[mode]}
    </span>
  );
}

const BAND_STYLE = {
  alto: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  medio: "bg-amber-500/15 text-amber-700 dark:text-amber-500",
  basso: "bg-muted text-muted-foreground",
  assente: "bg-muted text-muted-foreground",
} as const;

export function ScoreBadge({ score }: { score: number | null }) {
  const fascia = scoreBand(score);
  return (
    <span
      className={`num inline-flex h-9 min-w-13 items-center justify-center rounded-lg px-2.5 text-base font-semibold ${BAND_STYLE[fascia]}`}
      title={
        score === null
          ? "Non ancora valutato dalla rubrica"
          : "Media pesata dei sei criteri della rubrica"
      }
    >
      {score ?? "—"}
    </span>
  );
}

/**
 * La retribuzione. Riceve una stringa già formattata: la regola su cosa si può
 * mostrare sta in un posto solo, in `lib/format.ts`.
 */
export function SalaryCell({ value }: { value: string }) {
  if (value === "n.d.") {
    return (
      <span
        className="text-muted-foreground text-sm"
        title="L'annuncio non dichiara la retribuzione"
      >
        n.d.
      </span>
    );
  }
  return <span className="num text-sm whitespace-nowrap">{value}</span>;
}

/**
 * Dove sta l'annuncio.
 *
 * Mostra il **portale**, non l'adapter che l'ha pescato: "LinkedIn", non
 * "jsearch". Quando lo stesso annuncio arriva da più parti compare il primo e
 * un contatore, perché la colonna serve a sapere dove si finisce cliccando, non
 * a fare l'elenco di chi lo ha indicizzato — quello sta nel dettaglio.
 */
export function SourceList({ sources, atsType }: { sources: string[]; atsType: string }) {
  const [primo, ...altri] = sources;
  return (
    <span className="text-muted-foreground inline-flex items-center gap-2 text-sm">
      <span className="truncate">{primo ? formatSource(primo) : "—"}</span>
      {altri.length > 0 ? (
        <span
          className="num bg-muted rounded px-1.5 py-0.5 text-xs"
          title={sources.map(formatSource).join(", ")}
        >
          +{altri.length}
        </span>
      ) : null}
      {isAutoApplicable(atsType) ? <AutoApplyDot atsType={atsType} /> : null}
    </span>
  );
}

/** Segnala gli annunci su cui il worker sa precompilare il form da solo (Tier A). */
export function AutoApplyDot({ atsType }: { atsType: string }) {
  return (
    <span
      className="inline-block size-1.5 shrink-0 rounded-full bg-violet-500"
      title={`Form precompilato automaticamente su ${atsType} — l'invio resta sempre un tuo click`}
      aria-label={`Form precompilato automaticamente su ${atsType}, invio sempre manuale`}
    />
  );
}
