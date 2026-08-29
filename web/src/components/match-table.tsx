import Link from "next/link";

import { SalaryCell, ScoreBadge, SourceList, WorkModeBadge } from "@/components/badges";
import { RowActions } from "@/components/row-actions";
import type { MatchListItem } from "@/lib/queries";
import { CONTRACT_LABEL, formatDate, formatLocation, formatSalary } from "@/lib/format";

/**
 * La tabella dei match.
 *
 * **Su desktop una tabella, su mobile una lista di card.** Il markup è doppio e
 * commutato dalle media query di Tailwind, non da JavaScript: così non c'è
 * nulla da idratare, il primo paint è già quello giusto e non si vede il
 * momento in cui il layout cambia idea. Il piano dice che la dashboard verrà
 * consultata soprattutto dal telefono, ed è l'unico punto in cui vale la pena
 * scrivere due volte la stessa riga.
 *
 * Niente TanStack Table, che pure il piano nominava: ordinamento, filtri e
 * paginazione girano su Postgres, quindi resterebbe solo la definizione delle
 * colonne — e in cambio la tabella dovrebbe diventare tutta un client
 * component. La parte interattiva sono le tre azioni di riga, che sono già un
 * componente a sé.
 *
 * **La larghezza minima è deliberata.** Nove colonne dentro un contenitore
 * stretto non diventano illeggibili gradualmente: si toccano. Sotto i 64rem la
 * tabella scorre in orizzontale invece di comprimersi, e le colonne mantengono
 * la loro aria a qualunque larghezza di finestra.
 */
export function MatchTable({ items }: { items: MatchListItem[] }) {
  if (items.length === 0) {
    return (
      <div className="text-muted-foreground rounded-xl border border-dashed p-12 text-center">
        <p>Nessun annuncio con questi filtri.</p>
        <p className="mt-1 text-sm">Allarga la soglia o togli qualche filtro.</p>
      </div>
    );
  }

  return (
    <>
      <div className="hidden overflow-x-auto rounded-xl border md:block">
        <table className="w-full min-w-[64rem] border-collapse text-left">
          <thead>
            <tr className="bg-muted/60 text-muted-foreground border-b text-xs tracking-[0.06em] uppercase">
              <Th className="pl-5">Ruolo</Th>
              <Th>Azienda</Th>
              <Th>Luogo</Th>
              <Th>Modalità</Th>
              <Th align="text-right">RAL</Th>
              <Th>Contratto</Th>
              <Th align="text-right">Match</Th>
              <Th>Fonte</Th>
              <Th align="text-right" className="pr-5">
                Azioni
              </Th>
            </tr>
          </thead>
          <tbody className="divide-border/70 divide-y">
            {items.map((item) => (
              <tr key={item.matchId} className="hover:bg-muted/40 transition-colors">
                <td className="w-[26rem] py-4 pr-3 pl-5 align-middle">
                  <Link
                    href={`/annuncio/${item.matchId}`}
                    scroll={false}
                    className="rounded-sm hover:underline"
                  >
                    <span className="line-clamp-2 font-medium">{item.title}</span>
                  </Link>
                  <span className="text-muted-foreground mt-1 flex items-center gap-2 text-xs">
                    <span className="num">{formatDate(item.postedAt)}</span>
                    {item.status === "new" ? <NewFlag /> : null}
                  </span>
                </td>

                <td className="w-[13rem] px-3 py-4 align-middle text-sm">
                  <span className="line-clamp-2">{item.company}</span>
                </td>

                <td className="text-muted-foreground w-[11rem] px-3 py-4 align-middle text-sm">
                  <span className="line-clamp-2">{formatLocation(item)}</span>
                </td>

                <td className="px-3 py-4 align-middle">
                  <WorkModeBadge mode={item.workMode} />
                </td>

                <td className="px-3 py-4 text-right align-middle">
                  <SalaryCell value={formatSalary(item)} />
                </td>

                <td className="text-muted-foreground px-3 py-4 align-middle text-sm">
                  {CONTRACT_LABEL[item.contractType] ?? item.contractType}
                </td>

                <td className="px-3 py-4 text-right align-middle">
                  <ScoreBadge score={item.score} />
                </td>

                <td className="w-[11rem] px-3 py-4 align-middle">
                  <SourceList sources={item.sources} atsType={item.atsType} />
                </td>

                <td className="py-4 pr-5 pl-3 align-middle">
                  <div className="flex justify-end">
                    <RowActions
                      matchId={item.matchId}
                      status={item.status}
                      applyUrl={item.applyUrl ?? item.url}
                      compact
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="space-y-3 md:hidden">
        {items.map((item) => (
          <li key={item.matchId} className="rounded-xl border p-4">
            <div className="flex items-start justify-between gap-4">
              <Link href={`/annuncio/${item.matchId}`} scroll={false} className="min-w-0 rounded-sm">
                <p className="line-clamp-2 font-medium">{item.title}</p>
                <p className="text-muted-foreground mt-1 text-sm">{item.company}</p>
              </Link>
              <ScoreBadge score={item.score} />
            </div>

            <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
              <WorkModeBadge mode={item.workMode} />
              <span>{formatLocation(item)}</span>
              <SalaryCell value={formatSalary(item)} />
              <span className="num text-xs">{formatDate(item.postedAt)}</span>
              {item.status === "new" ? <NewFlag /> : null}
            </div>

            <div className="mt-4 flex items-center justify-between gap-3">
              <SourceList sources={item.sources} atsType={item.atsType} />
              <RowActions
                matchId={item.matchId}
                status={item.status}
                applyUrl={item.applyUrl ?? item.url}
              />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

/** "Mai aperto". Un puntino più un'etichetta, non solo il colore. */
function NewFlag() {
  return (
    <span className="text-primary inline-flex items-center gap-1.5 font-medium">
      <span aria-hidden className="bg-primary size-1.5 rounded-full" />
      nuovo
    </span>
  );
}

function Th({
  children,
  className = "",
  align = "text-left",
}: {
  children: React.ReactNode;
  className?: string;
  align?: string;
}) {
  return (
    <th scope="col" className={`px-3 py-3 font-medium ${align} ${className}`}>
      {children}
    </th>
  );
}
