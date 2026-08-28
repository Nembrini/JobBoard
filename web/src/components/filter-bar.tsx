"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";
import { SlidersHorizontal, X } from "lucide-react";

import { SORTS, WORK_MODES, type MatchFilters, type Sort } from "@/lib/filters";
import { WORK_MODE_LABEL } from "@/lib/format";

/**
 * La barra dei filtri.
 *
 * Ogni modifica riscrive la query string e lascia che il server rifaccia la
 * query: nessuno stato duplicato, nessuna lista tenuta in memoria da due parti
 * che poi divergono. Il costo è una navigazione per click, che con i server
 * component è una risposta parziale e non un ricaricamento.
 */
export function FilterBar({
  filters,
  options,
  total,
}: {
  filters: MatchFilters;
  options: { countries: string[]; sources: { adapter: string; displayName: string }[] };
  total: number;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [aperto, setAperto] = useState(false);

  function aggiorna(mutate: (p: URLSearchParams) => void) {
    const prossimi = new URLSearchParams(params.toString());
    mutate(prossimi);
    // Cambiare un filtro e restare a pagina 7 mostra una lista vuota e sembra
    // un guasto: si torna sempre alla prima.
    prossimi.delete("page");
    startTransition(() => router.push(`${pathname}?${prossimi}`, { scroll: false }));
  }

  function alterna(chiave: string, valore: string) {
    aggiorna((p) => {
      const correnti = p.getAll(chiave);
      p.delete(chiave);
      const prossimi = correnti.includes(valore)
        ? correnti.filter((v) => v !== valore)
        : [...correnti, valore];
      for (const v of prossimi) p.append(chiave, v);
    });
  }

  const attivi =
    filters.workModes.length +
    filters.countries.length +
    filters.sources.length +
    (filters.minScore > 0 ? 1 : 0) +
    (filters.onlyNew ? 1 : 0) +
    (filters.hideSeen ? 1 : 0) +
    (filters.onlyShortlist ? 1 : 0);

  return (
    <div className={pending ? "opacity-60 transition-opacity" : "transition-opacity"}>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setAperto((v) => !v)}
          aria-expanded={aperto}
          className="border-input hover:bg-accent inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium"
        >
          <SlidersHorizontal className="size-4" />
          Filtri
          {attivi > 0 ? (
            <span className="bg-primary text-primary-foreground grid size-5 place-items-center rounded-full text-[11px]">
              {attivi}
            </span>
          ) : null}
        </button>

        <Toggle attivo={filters.onlyNew} onClick={() => aggiorna((p) => toggle(p, "new"))}>
          Solo nuovi
        </Toggle>
        <Toggle
          attivo={filters.onlyShortlist}
          onClick={() => aggiorna((p) => toggle(p, "shortlist"))}
        >
          Shortlist
        </Toggle>
        <Toggle attivo={filters.hideSeen} onClick={() => aggiorna((p) => toggle(p, "unseen"))}>
          Nascondi già visti
        </Toggle>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-muted-foreground hidden text-sm sm:inline">{total} annunci</span>
          <label className="sr-only" htmlFor="ordina">
            Ordina per
          </label>
          <select
            id="ordina"
            value={filters.sort}
            onChange={(e) => aggiorna((p) => p.set("sort", e.target.value))}
            className="border-input bg-background h-9 rounded-lg border px-2 text-sm"
          >
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {SORT_LABEL[s]}
              </option>
            ))}
          </select>
        </div>
      </div>

      {aperto ? (
        <div className="bg-muted/40 mt-3 space-y-4 rounded-xl border p-4">
          <Gruppo titolo="Modalità">
            {WORK_MODES.map((mode) => (
              <Chip
                key={mode}
                attivo={filters.workModes.includes(mode)}
                onClick={() => alterna("mode", mode)}
              >
                {WORK_MODE_LABEL[mode]}
              </Chip>
            ))}
          </Gruppo>

          {options.countries.length > 0 ? (
            <Gruppo titolo="Paese">
              {options.countries.map((c) => (
                <Chip
                  key={c}
                  attivo={filters.countries.includes(c)}
                  onClick={() => alterna("country", c)}
                >
                  {c}
                </Chip>
              ))}
            </Gruppo>
          ) : null}

          {options.sources.length > 0 ? (
            <Gruppo titolo="Fonte">
              {options.sources.map((s) => (
                <Chip
                  key={s.adapter}
                  attivo={filters.sources.includes(s.adapter)}
                  onClick={() => alterna("source", s.adapter)}
                >
                  {s.displayName}
                </Chip>
              ))}
            </Gruppo>
          ) : null}

          <div className="space-y-2">
            <label htmlFor="soglia" className="text-muted-foreground text-xs font-medium">
              Punteggio minimo: <span className="text-foreground">{filters.minScore}</span>
            </label>
            <input
              id="soglia"
              type="range"
              min={0}
              max={100}
              step={5}
              defaultValue={filters.minScore}
              // `onChange` a ogni pixel farebbe una navigazione per movimento
              // del dito: si aggiorna quando lo slider viene rilasciato.
              onPointerUp={(e) => aggiorna((p) => p.set("min", e.currentTarget.value))}
              onKeyUp={(e) => aggiorna((p) => p.set("min", e.currentTarget.value))}
              className="w-full max-w-xs"
            />
          </div>

          {attivi > 0 ? (
            <button
              type="button"
              onClick={() => startTransition(() => router.push(pathname, { scroll: false }))}
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
            >
              <X className="size-3.5" />
              Azzera i filtri
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

const SORT_LABEL: Record<Sort, string> = {
  score: "Compatibilità",
  recent: "Più recenti",
  salary: "RAL dichiarata",
};

function toggle(params: URLSearchParams, chiave: string) {
  if (params.get(chiave) === "1") params.delete(chiave);
  else params.set(chiave, "1");
}

function Gruppo({ titolo, children }: { titolo: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs font-medium">{titolo}</p>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function Chip({
  attivo,
  onClick,
  children,
}: {
  attivo: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={attivo}
      className={`h-7 rounded-full border px-3 text-xs font-medium transition-colors ${
        attivo
          ? "border-primary bg-primary text-primary-foreground"
          : "border-input hover:bg-accent"
      }`}
    >
      {children}
    </button>
  );
}

function Toggle({
  attivo,
  onClick,
  children,
}: {
  attivo: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={attivo}
      className={`h-9 rounded-lg border px-3 text-sm font-medium transition-colors ${
        attivo ? "border-primary bg-primary text-primary-foreground" : "border-input hover:bg-accent"
      }`}
    >
      {children}
    </button>
  );
}
