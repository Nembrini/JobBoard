import Link from "next/link";

import { AutoApplyDot, SalaryCell, ScoreBadge, WorkModeBadge } from "@/components/badges";
import { RowActions } from "@/components/row-actions";
import type { MatchListItem } from "@/lib/queries";
import {
  CONTRACT_LABEL,
  formatDate,
  formatLocation,
  formatSalary,
  isAutoApplicable,
} from "@/lib/format";

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
 */
export function MatchTable({ items }: { items: MatchListItem[] }) {
  if (items.length === 0) {
    return (
      <div className="text-muted-foreground rounded-xl border border-dashed p-12 text-center">
        <p className="text-sm">Nessun annuncio con questi filtri.</p>
      </div>
    );
  }

  return (
    <>
      <div className="hidden overflow-x-auto rounded-xl border md:block">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground text-xs">
            <tr>
              <Th className="pl-4">Ruolo</Th>
              <Th>Azienda</Th>
              <Th>Luogo</Th>
              <Th>Modalità</Th>
              <Th className="text-right">RAL</Th>
              <Th>Tipo</Th>
              <Th className="text-right">Match</Th>
              <Th>Fonte</Th>
              <Th className="pr-4 text-right">Azioni</Th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {items.map((item) => (
              <tr key={item.matchId} className="hover:bg-muted/30 transition-colors">
                <td className="max-w-[22rem] py-3 pl-4">
                  <Link
                    href={`/?open=${item.matchId}`}
                    scroll={false}
                    className="hover:underline"
                    prefetch={false}
                  >
                    <span className="line-clamp-2 font-medium">{item.title}</span>
                  </Link>
                  <span className="text-muted-foreground mt-0.5 block text-xs">
                    {formatDate(item.postedAt)}
                    {item.status === "new" ? (
                      <span className="text-primary ml-2 font-medium">nuovo</span>
                    ) : null}
                  </span>
                </td>
                <td className="max-w-[12rem] py-3">
                  <span className="line-clamp-1">{item.company}</span>
                </td>
                <td className="text-muted-foreground max-w-[10rem] py-3">
                  <span className="line-clamp-1">{formatLocation(item)}</span>
                </td>
                <td className="py-3">
                  <WorkModeBadge mode={item.workMode} />
                </td>
                <td className="py-3 text-right">
                  <SalaryCell value={formatSalary(item)} />
                </td>
                <td className="text-muted-foreground py-3 text-xs">
                  {CONTRACT_LABEL[item.contractType] ?? item.contractType}
                </td>
                <td className="py-3 text-right">
                  <ScoreBadge score={item.score} />
                </td>
                <td className="text-muted-foreground py-3 text-xs">
                  <span className="inline-flex items-center gap-1.5">
                    {item.sources[0] ?? "—"}
                    {item.sources.length > 1 ? `+${item.sources.length - 1}` : ""}
                    {isAutoApplicable(item.atsType) ? <AutoApplyDot atsType={item.atsType} /> : null}
                  </span>
                </td>
                <td className="py-3 pr-4">
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

      <ul className="space-y-2 md:hidden">
        {items.map((item) => (
          <li key={item.matchId} className="rounded-xl border p-4">
            <div className="flex items-start justify-between gap-3">
              <Link href={`/?open=${item.matchId}`} scroll={false} prefetch={false} className="min-w-0">
                <p className="line-clamp-2 font-medium">{item.title}</p>
                <p className="text-muted-foreground mt-0.5 text-sm">{item.company}</p>
              </Link>
              <ScoreBadge score={item.score} />
            </div>

            <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
              <WorkModeBadge mode={item.workMode} />
              <span>{formatLocation(item)}</span>
              <SalaryCell value={formatSalary(item)} />
              <span>{formatDate(item.postedAt)}</span>
            </div>

            <div className="mt-3 flex items-center justify-between">
              <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
                {item.sources.join(", ") || "—"}
                {isAutoApplicable(item.atsType) ? <AutoApplyDot atsType={item.atsType} /> : null}
              </span>
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

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th scope="col" className={`py-2.5 text-left font-medium ${className}`}>
      {children}
    </th>
  );
}
