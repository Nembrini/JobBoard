/**
 * Lo slot vuoto.
 *
 * Serve su ogni navigazione che non e' un'intercettazione: caricamento a
 * freddo, ricaricamento della pagina, `/cv`. Senza questo file Next.js
 * risponderebbe 404 allo slot che non trova, invece di non disegnare niente.
 */
export default function NessunDrawer() {
  return null;
}
