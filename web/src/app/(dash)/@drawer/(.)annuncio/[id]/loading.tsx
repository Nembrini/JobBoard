import { DrawerShell } from "@/components/drawer-shell";

/**
 * Lo scheletro del pannello.
 *
 * Non e' solo cortesia: Next.js **non prefetcha una rotta dinamica** che non ha
 * un confine di caricamento. Con questo file il guscio del pannello viene
 * scaricato mentre il puntatore e' ancora sulla riga, e al click resta da
 * aspettare solo la query del dettaglio. Senza, il click aspettava tutto.
 *
 * Le barre imitano l'ingombro reale — titolo, azienda, bottone, motivazione —
 * cosi' quando il contenuto arriva prende il posto che occupava lo scheletro
 * invece di spostare quello che si stava gia' leggendo.
 */
export default function CaricamentoAnnuncio() {
  return (
    <DrawerShell>
      <div className="animate-pulse space-y-6 p-5 pt-14 sm:p-6 sm:pt-14" aria-hidden>
        <div className="space-y-3">
          <div className="bg-muted h-6 w-3/4 rounded" />
          <div className="bg-muted h-4 w-1/3 rounded" />
          <div className="bg-muted h-10 w-44 rounded-lg" />
        </div>
        <div className="bg-muted/60 h-24 rounded-xl" />
        <div className="space-y-2">
          <div className="bg-muted h-4 w-full rounded" />
          <div className="bg-muted h-4 w-11/12 rounded" />
          <div className="bg-muted h-4 w-4/5 rounded" />
        </div>
      </div>
      <span className="sr-only">Carico l&apos;annuncio…</span>
    </DrawerShell>
  );
}
