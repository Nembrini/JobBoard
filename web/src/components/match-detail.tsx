import { ExternalLink } from "lucide-react";

import { ScoreBadge, SourceList, WorkModeBadge } from "@/components/badges";
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
 *
 * `inset` distingue le due sedi: dentro il pannello serve spazio in alto per il
 * bottone di chiusura, che nella pagina intera non c'è.
 */
export async function MatchDetail({
  matchId,
  inset = true,
}: {
  matchId: number;
  inset?: boolean;
}) {
  const m = await getMatchDetail(matchId);

  if (!m) {
    return <div className="text-muted-foreground p-8">Questo annuncio non esiste più.</div>;
  }

  const sotto = (m.subscores ?? {}) as Record<string, number>;
  const link = m.applyUrl ?? m.url;

  return (
    <article className={inset ? "space-y-7 p-5 pt-14 sm:p-6 sm:pt-14" : "space-y-7 py-4"}>
      <header className="space-y-4">
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="font-heading text-xl leading-snug font-semibold tracking-tight">
              {m.title}
            </h1>
            <p className="text-muted-foreground mt-1.5">{m.company}</p>
          </div>
          <ScoreBadge score={m.score} />
        </div>

        {/* I fatti che l'annuncio non dichiara vengono omessi, non scritti
            "n.d.": una fila di n.d. affiancati non si distingue piu' dai dati
            veri. L'unica eccezione e' la RAL, dove il silenzio *e'*
            l'informazione — e dove una cifra mancante non va confusa con una
            stimata. */}
        <dl className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <WorkModeBadge mode={m.workMode} />
          <Fatto etichetta="Luogo">{formatLocation(m)}</Fatto>
          <Fatto etichetta="Contratto" omettiSe="n.d.">
            {CONTRACT_LABEL[m.contractType] ?? m.contractType}
          </Fatto>
          <Fatto etichetta="Livello" omettiSe="n.d.">
            {SENIORITY_LABEL[m.seniority] ?? m.seniority}
          </Fatto>
          <Fatto etichetta="RAL" mono>
            {formatSalary(m)}
          </Fatto>
          <Fatto etichetta="Pubblicato" mono omettiSe="—">
            {formatDate(m.postedAt)}
          </Fatto>
          <Fatto etichetta="Fonte">
            <SourceList sources={m.sources ?? []} atsType={m.atsType} />
          </Fatto>
        </dl>

        <div>
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex h-11 items-center gap-2 rounded-lg px-5 font-medium"
          >
            Apri l&apos;annuncio
            <ExternalLink className="size-4" />
          </a>
          {isAutoApplicable(m.atsType) ? (
            <p className="text-muted-foreground mt-2 text-sm">
              Ospitato su {m.atsType}: dalla Fase 7 la candidatura potrà partire da sola.
            </p>
          ) : null}
        </div>
      </header>

      {m.rationale ? (
        <section className="bg-muted/40 rounded-xl p-5">
          <h2 className="text-muted-foreground mb-2 text-xs font-medium tracking-[0.06em] uppercase">
            Perché questo punteggio
          </h2>
          <p className="leading-relaxed">{m.rationale}</p>
        </section>
      ) : null}

      {m.gaps.length > 0 ? (
        <section>
          <h2 className="text-muted-foreground mb-3 text-xs font-medium tracking-[0.06em] uppercase">
            Cosa manca ({m.gaps.length})
          </h2>
          <ul className="space-y-2">
            {m.gaps.map((gap, i) => (
              <li key={i} className="flex gap-2.5 leading-relaxed">
                <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-amber-500" />
                {gap}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {Object.keys(sotto).length > 0 ? (
        <section>
          <h2 className="text-muted-foreground mb-3 text-xs font-medium tracking-[0.06em] uppercase">
            Rubrica
          </h2>
          <dl className="space-y-2.5">
            {Object.entries(RUBRIC_WEIGHTS).map(([chiave, peso]) => {
              const valore = sotto[chiave];
              return (
                <div key={chiave} className="flex items-center gap-4 text-sm">
                  <dt className="w-44 shrink-0">{RUBRIC_LABEL[chiave] ?? chiave}</dt>
                  <div className="bg-muted h-2 flex-1 overflow-hidden rounded-full">
                    <div
                      className="bg-foreground/60 h-full rounded-full"
                      style={{ width: `${valore ?? 0}%` }}
                    />
                  </div>
                  <dd className="num w-16 shrink-0 text-right">
                    {valore ?? "—"}
                    <span className="text-muted-foreground ml-1.5 text-xs">
                      {Math.round(peso * 100)}%
                    </span>
                  </dd>
                </div>
              );
            })}
          </dl>
          <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
            <span className="num">50</span> significa &quot;non ci sono elementi per
            giudicare&quot;, non &quot;mediocre&quot;: è il valore che prendono i criteri su cui
            l&apos;annuncio tace.
          </p>
        </section>
      ) : null}

      {m.mustHave?.length || m.niceToHave?.length || m.techStack?.length ? (
        <section className="space-y-4">
          <h2 className="text-muted-foreground text-xs font-medium tracking-[0.06em] uppercase">
            Requisiti estratti
          </h2>
          <Requisiti titolo="Obbligatori" voci={m.mustHave} />
          <Requisiti titolo="Graditi" voci={m.niceToHave} />
          <Requisiti titolo="Stack" voci={m.techStack} />
          {m.minYears ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Esperienza richiesta:</span>{" "}
              <span className="num">{m.minYears}+</span> anni
            </p>
          ) : null}
          {m.remotePolicy ? (
            <p className="text-sm">
              <span className="text-muted-foreground">Presenza:</span> {m.remotePolicy}
            </p>
          ) : null}
          {m.redFlags?.length ? (
            <p className="text-destructive text-sm">Segnali negativi: {m.redFlags.join(", ")}</p>
          ) : null}
        </section>
      ) : null}

      <section>
        <h2 className="text-muted-foreground mb-3 text-xs font-medium tracking-[0.06em] uppercase">
          Annuncio completo {m.lang ? `(${m.lang})` : ""}
        </h2>
        <div className="text-sm leading-relaxed whitespace-pre-wrap">{m.description}</div>
      </section>
    </article>
  );
}

/**
 * Una coppia etichetta/valore della riga di intestazione.
 *
 * L'etichetta e' solo per chi legge con uno screen reader: a vederli, questi
 * valori si riconoscono da soli — "Milano, IT" e' un luogo, "Indeterminato" un
 * contratto — e stampare "Luogo:" davanti a ciascuno raddoppierebbe la riga per
 * dire cose che si vedono. Chi ascolta invece riceve una sequenza di valori
 * senza contesto, e li' l'etichetta e' l'unica cosa che li distingue.
 */
function Fatto({
  etichetta,
  mono = false,
  omettiSe,
  children,
}: {
  etichetta: string;
  mono?: boolean;
  omettiSe?: string;
  children: React.ReactNode;
}) {
  if (omettiSe !== undefined && children === omettiSe) return null;
  return (
    <div className="flex items-center gap-1.5">
      <dt className="sr-only">{etichetta}</dt>
      <dd className={mono ? "num" : undefined}>{children}</dd>
    </div>
  );
}

function Requisiti({ titolo, voci }: { titolo: string; voci: string[] | null }) {
  if (!voci?.length) return null;
  return (
    <div>
      <p className="text-muted-foreground mb-2 text-sm">{titolo}</p>
      <div className="flex flex-wrap gap-2">
        {voci.map((voce, i) => (
          <span key={i} className="bg-muted rounded-md px-2.5 py-1 text-sm">
            {voce}
          </span>
        ))}
      </div>
    </div>
  );
}
