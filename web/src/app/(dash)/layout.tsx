/**
 * Il guscio della parte autenticata.
 *
 * Esiste per lo slot `@drawer`, non per la testata. Il dettaglio di un annuncio
 * e' una **rotta vera** (`/annuncio/<id>`) che dalla lista viene *intercettata*
 * e disegnata nello slot: la lista sotto non viene rinavigata, quindi le sue
 * tre query — elenco, opzioni dei filtri, contatori — non si rieseguono per
 * aprire un pannello che non le usa. Prima aprire un annuncio rifaceva tutta la
 * dashboard, ed e' il motivo per cui era lento.
 *
 * Su ricaricamento o su link condiviso non c'e' nessuna intercettazione: lo
 * slot cade su `@drawer/default.tsx` e la rotta si apre come pagina intera.
 *
 * Il gruppo `(dash)` non compare negli URL: serve a tenere `/login` fuori da
 * questo layout, che altrimenti gli metterebbe sopra una testata con dentro il
 * bottone "Esci".
 */
export default function DashboardLayout({ children, drawer }: LayoutProps<"/">) {
  return (
    <>
      {children}
      {drawer}
    </>
  );
}
