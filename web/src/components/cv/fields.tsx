"use client";

import { useId, useState } from "react";
import { Plus, X } from "lucide-react";

/**
 * I mattoni dell'editor del profilo.
 *
 * Tutti controllati e senza stato proprio, tranne `ElencoModificabile`, che
 * tiene solo il testo in corso di digitazione: lo stato del profilo sta in un
 * posto solo, nel componente radice, perché è un unico oggetto JSON e viene
 * salvato in un'unica scrittura.
 */

const INPUT =
  "border-input bg-background focus-visible:ring-ring/60 h-10 w-full rounded-lg border px-3 text-sm outline-none focus-visible:ring-2";

export function Campo({
  etichetta,
  valore,
  onChange,
  segnaposto,
  tipo = "text",
  larghezza,
  aiuto,
}: {
  etichetta: string;
  valore: string;
  onChange: (v: string) => void;
  segnaposto?: string;
  tipo?: string;
  larghezza?: string;
  aiuto?: string;
}) {
  const id = useId();
  return (
    <div className={larghezza}>
      <Etichetta htmlFor={id}>{etichetta}</Etichetta>
      <input
        id={id}
        type={tipo}
        value={valore}
        placeholder={segnaposto}
        onChange={(e) => onChange(e.target.value)}
        className={INPUT}
      />
      {aiuto ? <p className="text-muted-foreground mt-1 text-xs">{aiuto}</p> : null}
    </div>
  );
}

/** Data nella forma `2024-03`, l'unica che il profilo accetta. */
export function CampoMese({
  etichetta,
  valore,
  onChange,
  vuotoSignifica,
}: {
  etichetta: string;
  valore: string;
  onChange: (v: string) => void;
  vuotoSignifica?: string;
}) {
  const id = useId();
  return (
    <div>
      <Etichetta htmlFor={id}>{etichetta}</Etichetta>
      <input
        id={id}
        type="month"
        value={valore}
        onChange={(e) => onChange(e.target.value)}
        className={`${INPUT} num`}
      />
      {vuotoSignifica && !valore ? (
        <p className="text-muted-foreground mt-1 text-xs">{vuotoSignifica}</p>
      ) : null}
    </div>
  );
}

export function AreaTesto({
  etichetta,
  valore,
  onChange,
  righe = 3,
  massimo,
  segnaposto,
}: {
  etichetta: string;
  valore: string;
  onChange: (v: string) => void;
  righe?: number;
  massimo?: number;
  segnaposto?: string;
}) {
  const id = useId();
  const superato = massimo !== undefined && valore.length > massimo;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <Etichetta htmlFor={id}>{etichetta}</Etichetta>
        {massimo !== undefined ? (
          <span className={`num text-xs ${superato ? "text-destructive" : "text-muted-foreground"}`}>
            {valore.length}/{massimo}
          </span>
        ) : null}
      </div>
      <textarea
        id={id}
        rows={righe}
        value={valore}
        placeholder={segnaposto}
        onChange={(e) => onChange(e.target.value)}
        className="border-input bg-background focus-visible:ring-ring/60 w-full resize-y rounded-lg border px-3 py-2 text-sm leading-relaxed outline-none focus-visible:ring-2"
      />
    </div>
  );
}

export function Selezione<T extends string>({
  etichetta,
  valore,
  opzioni,
  onChange,
}: {
  etichetta: string;
  valore: T;
  opzioni: readonly (readonly [T, string])[];
  onChange: (v: T) => void;
}) {
  const id = useId();
  return (
    <div>
      <Etichetta htmlFor={id}>{etichetta}</Etichetta>
      <select
        id={id}
        value={valore}
        onChange={(e) => onChange(e.target.value as T)}
        className={INPUT}
      >
        {opzioni.map(([v, testo]) => (
          <option key={v} value={v}>
            {testo}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Un elenco di voci brevi: tecnologie, competenze, punti salienti.
 *
 * Invio aggiunge, la ✕ toglie. La virgola aggiunge anche lei, perché
 * incollando da un CV si incolla "Java, Kotlin, SQL" e ritrovarsi una sola
 * competenza chiamata "Java, Kotlin, SQL" è un errore che poi sfugge: quella
 * stringa non corrisponderà mai a nessun requisito di nessun annuncio.
 */
export function ElencoModificabile({
  etichetta,
  voci,
  onChange,
  segnaposto = "aggiungi e premi Invio",
}: {
  etichetta: string;
  voci: string[];
  onChange: (v: string[]) => void;
  segnaposto?: string;
}) {
  const id = useId();
  const [bozza, setBozza] = useState("");

  function aggiungi(testo: string) {
    const nuove = testo
      .split(",")
      .map((v) => v.trim())
      .filter((v) => v.length > 0 && !voci.includes(v));
    if (nuove.length > 0) onChange([...voci, ...nuove]);
    setBozza("");
  }

  return (
    <div>
      <Etichetta htmlFor={id}>{etichetta}</Etichetta>
      <div className="border-input focus-within:ring-ring/60 flex flex-wrap items-center gap-1.5 rounded-lg border p-1.5 focus-within:ring-2">
        {voci.map((voce) => (
          <span
            key={voce}
            className="bg-muted inline-flex items-center gap-1 rounded-md py-1 pr-1 pl-2.5 text-sm"
          >
            {voce}
            <button
              type="button"
              onClick={() => onChange(voci.filter((v) => v !== voce))}
              aria-label={`Togli ${voce}`}
              className="hover:bg-background text-muted-foreground hover:text-foreground grid size-5 place-items-center rounded"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={bozza}
          placeholder={voci.length === 0 ? segnaposto : ""}
          onChange={(e) => setBozza(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              aggiungi(bozza);
            } else if (e.key === "Backspace" && bozza === "" && voci.length > 0) {
              onChange(voci.slice(0, -1));
            }
          }}
          // Perdere quello che si è appena scritto cambiando campo è il modo
          // più sicuro di far ricominciare da capo: si aggiunge anche all'uscita.
          onBlur={() => aggiungi(bozza)}
          className="min-w-32 flex-1 bg-transparent px-1.5 py-1 text-sm outline-none"
        />
      </div>
    </div>
  );
}

export function Etichetta({
  htmlFor,
  children,
}: {
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-muted-foreground mb-1.5 block text-xs font-medium tracking-[0.06em] uppercase"
    >
      {children}
    </label>
  );
}

/** Il bottone che aggiunge una voce a un elenco. */
export function BottoneAggiungi({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="border-input hover:bg-accent text-muted-foreground hover:text-foreground inline-flex h-10 items-center gap-2 rounded-lg border border-dashed px-4 text-sm font-medium"
    >
      <Plus className="size-4" />
      {children}
    </button>
  );
}

/** L'id tecnico di una voce: si mostra, non si modifica. */
export function Targhetta({ id }: { id: string }) {
  return (
    <span
      className="num bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-xs"
      title="Identificativo stabile: da qui il validatore anti-invenzione risalirà alla voce che giustifica una frase del CV generato"
    >
      {id}
    </span>
  );
}
