"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { X } from "lucide-react";

/**
 * Il guscio del drawer: sfondo, chiusura con Esc, blocco dello scorrimento.
 *
 * È un client component che riceve il contenuto come `children`, e il
 * contenuto è renderizzato dal server: il pattern serve a tenere in JavaScript
 * *solo* quello che deve reagire a un tasto o a un click, e a lasciare al
 * server il dettaglio dell'annuncio, che è testo e non ha bisogno di essere
 * idratato.
 *
 * Il drawer è aperto da `?open=<id>`, cioè da un URL. Costa una navigazione,
 * ma in cambio il tasto "indietro" del telefono lo chiude — che è il gesto che
 * si fa d'istinto — e il link a un annuncio si può mandare a qualcuno.
 */
export function DrawerShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") router.back();
    }
    document.addEventListener("keydown", onKey);

    // Lo sfondo non deve scorrere sotto il pannello: su iOS è il modo più
    // rapido di perdere la posizione nella lista.
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [router]);

  return (
    <div role="dialog" aria-modal="true" aria-label="Dettaglio annuncio" className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Chiudi"
        onClick={() => router.back()}
        className="absolute inset-0 bg-black/40 backdrop-blur-[1px]"
      />
      <div className="bg-background absolute inset-x-0 bottom-0 top-12 overflow-y-auto rounded-t-2xl border-t shadow-xl sm:inset-y-0 sm:left-auto sm:right-0 sm:top-0 sm:w-full sm:max-w-xl sm:rounded-none sm:border-t-0 sm:border-l">
        <button
          type="button"
          onClick={() => router.back()}
          aria-label="Chiudi"
          className="bg-background/80 hover:bg-accent absolute right-3 top-3 z-10 grid size-9 place-items-center rounded-full backdrop-blur"
        >
          <X className="size-4" />
        </button>
        {children}
      </div>
    </div>
  );
}
