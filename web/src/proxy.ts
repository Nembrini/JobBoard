import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { auth } from "@/auth";

/**
 * Controllo **ottimistico**: reindirizza al login chi non ha un cookie di
 * sessione valido, prima ancora che una pagina venga renderizzata.
 *
 * Si chiama `proxy` e non `middleware` perché da Next.js 16 il vecchio nome è
 * deprecato; la funzione esportata deve chiamarsi così, e il runtime è Node.js
 * e non più edge.
 *
 * **Non è l'unica difesa, ed è importante che non lo sia.** Il proxy gira anche
 * sulle rotte che il browser preleva in anticipo, quindi legge solo il cookie e
 * non tocca il database. Il controllo vero — quello che decide se dei dati
 * possono uscire — sta accanto ai dati, in `lib/dal.ts`, ed è quello che ogni
 * query chiama. Se un giorno questo file venisse cancellato per sbaglio, la
 * dashboard smetterebbe di reindirizzare ma continuerebbe a non mostrare nulla
 * a chi non ha diritto di vederlo.
 */
export default auth((req: NextRequest & { auth: unknown }) => {
  const { pathname } = req.nextUrl;
  const autenticato = Boolean(req.auth);

  // Le API rispondono con un 401 JSON, non con un reindirizzamento: chi ha
  // chiesto dati riceverebbe una pagina HTML di login con stato 307, cioè un
  // errore di parsing invece di un errore comprensibile. Il drawer se ne
  // accorgerebbe soltanto come "JSON malformato".
  if (!autenticato && pathname.startsWith("/api/")) {
    return Response.json({ error: "non autorizzato" }, { status: 401 });
  }

  if (!autenticato && pathname !== "/login") {
    const login = new URL("/login", req.nextUrl);
    // Dove voleva andare, per riportarcelo dopo il login invece di scaricarlo
    // sulla home: aprendo un link dal digest email si finisce su una riga
    // precisa, e perderla sarebbe fastidioso ogni singola volta.
    if (pathname !== "/") login.searchParams.set("next", pathname + req.nextUrl.search);
    return NextResponse.redirect(login);
  }

  if (autenticato && pathname === "/login") {
    return NextResponse.redirect(new URL("/", req.nextUrl));
  }

  return NextResponse.next();
});

export const config = {
  // Tutto tranne le rotte di Auth.js (che devono restare raggiungibili senza
  // sessione, altrimenti il login stesso verrebbe reindirizzato al login) e gli
  // asset statici, su cui girare sarebbe solo lavoro sprecato.
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|webp)$).*)"],
};
