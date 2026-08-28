import { ExternalLink } from "lucide-react";

import { ScoreBadge, WorkModeBadge } from "@/components/badges";
import {
  CONTRACT_LABEL,
  RUBRIC_LABEL,
  RUBRIC_WEIGHTS,
  SENIORITY_LABEL,
  formatDate,
  formatLocation,
  formatSalary,
  isAutoApplicable,
} from "@/lib/format";
import { getMatchDetail } from "@/lib/queries";

/**
 * Il dettaglio di un annuncio: rubrica, motivazione, gap, requisiti estratti,
 * job description completa.
 *
 * Server component: legge dal database e restituisce HTML. Il drawer che lo
 * contiene è l'unico pezzo interattivo.
 *
 * L'ordine delle sezioni è quello con cui si decide se candidarsi: prima
 * *perché* questo punteggio, poi *cosa manca*, poi cosa chiede l'annuncio, e
 * solo alla fine il testo integrale — che è lungo, ed è la parte che si legge
 * solo se le prime tre hanno convinto.
 */
export async function MatchDetail({ matchId }: { matchId: number }) {
  const m = await getMatchDetail(matchId);

  if (!m) {
    return (
      <div className="text-muted-foreground p-8 text-sm">
        Questo annuncio non esiste più.
      </div>
    );
  }

  const sotto = (m.subscores ?? {}) as Record<string, number>;
  const link = m.applyUrl ?? m.url;

  return (
    <article className="space-y-6 p-5 pt-14 sm:p-6 sm:pt-14">
      <header className="space-y-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="font-heading text-lg leading-snug font-semibold">{m.title}</h2>
            <p className="text-muted-foreground mt-1 text-sm">{m.company}</p>
          </div>
          <ScoreBadge score={m.score} />
        </div>

        <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
          <WorkModeBadge mode={m.workMode} />
          <span>{formatLocation(m)}</span>
          <span>{CONTRACT_LABEL[m.contractType] ?? m.contractType}</span>
          <span>{SENIORITY_LABEL[m.seniority] ?? m.seniority}</span>
          <span>{formatSalary(m)}</span>
          <span>{formatDate(m.postedAt)}</span>
        </div>

        <a
          href={link}
          target="_blank"
          rel="noopener noreferrer"
          className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-10 items-center gap-2 rounded-lg px-4 text-sm font-medium"
        >
          Apri l&apos;annuncio
          <ExternalLink className="size-4" />
        </a>
        {isAutoApplicable(m.atsType) ? (
          <p className="text-muted-foreground text-xs">
            Ospitato su {m.atsType}: dalla Fase 7 la candidatura potrà partire da sola.
          </p>
        ) : null}
      </header>

      {m.rationale ? (
        <section className="bg-muted/40 rounded-xl p-4">
          <h3 className="text-muted-foreground mb-1.5 text-xs font-medium">Perché questo punteggio</h3>
          <p className="text-sm leading-relaxed">{m.rationale}</p>
        </section>
      ) : null}

      {m.gaps.length > 0 ? (
        <section>
          <h3 className="text-muted-foreground mb-2 text-xs font-medium">
            Cosa manca ({m.gaps.length})
          </h3>
          <ul className="space-y-1.5">
            {m.gaps.map((gap, i) => (
              <li key={i} className="flex gap-2 text-sm leading-relaxed">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-amber-500" />
                {gap}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {Object.keys(sotto).length > 0 ? (
        <section>
          <h3 className="text-muted-foreground mb-2 text-xs font-medium">Rubrica</h3>
          <dl className="space-y-1.5">
            {Object.entries(RUBRIC_WEIGHTS).map(([chiave, peso]) => {
              const valore = sotto[chiave];
              return (
                <div key={chiave} className="flex items-center gap-3 text-sm">
                  <dt className="w-44 shrink-0 truncate">{RUBRIC_LABEL[chiave] ?? chiave}</dt>
                  <div className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
                    <div
                      className="bg-foreground/60 h-full rounded-full"
                      style={{ width: `${valore ?? 0}%` }}
                    />
                  </div>
                  <dd className="w-14 shrink-0 text-right tabular-nums">
                    {valore ?? "—"}
                    <span className="text-muted-foreground ml-1 text-xs">
                      {Math.round(peso * 100)}%
                    </span>
                  </dd>
                </div>
              );
            })}
          </dl>
          <p className="text-muted-foreground mt-2 text-xs leading-relaxed">
            50 significa &quot;non ci sono elementi per giudicare&quot;, non &quot;mediocre&quot;:
            è il valore che prendono i criteri su cui l&apos;annuncio tace.
          </p>
        </section>
      ) : null}

      {m.mustHave?.length || m.niceToHave?.length || m.techStack?.length ? (
        <section className="space-y-3">
          <h3 className="text-muted-foreground text-xs font-medium">Requisiti estratti</h3>
          <Requisiti titolo="Obbligatori" voci={m.mustHave} />
          <Requisiti titolo="Graditi" voci={m.niceToHave} />
          <Requisiti titolo="Stack" voci={m.techStack} />
          {m.minYears ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Esperienza richiesta:</span> {m.minYears}+ anni
            </p>
          ) : null}
          {m.remotePolicy ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Presenza:</span> {m.remotePolicy}
            </p>
          ) : null}
          {m.redFlags?.length ? (
            <p className="text-destructive text-sm">
              Segnali negativi: {m.redFlags.join(", ")}
            </p>
          ) : null}
        </section>
      ) : null}

      <section>
        <h3 className="text-muted-foreground mb-2 text-xs font-medium">
          Annuncio completo {m.lang ? `(${m.lang})` : ""}
        </h3>
        <div className="text-sm leading-relaxed whitespace-pre-wrap">{m.description}</div>
      </section>
    </article>
  );
}

function Requisiti({ titolo, voci }: { titolo: string; voci: string[] | null }) {
  if (!voci?.length) return null;
  return (
    <div>
      <p className="text-muted-foreground mb-1.5 text-xs">{titolo}</p>
      <div className="flex flex-wrap gap-1.5">
        {voci.map((voce, i) => (
          <span key={i} className="bg-muted rounded-md px-2 py-1 text-xs">
            {voce}
          </span>
        ))}
      </div>
    </div>
  );
}
