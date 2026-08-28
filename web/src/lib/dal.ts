import "server-only";

import { cache } from "react";
import { redirect } from "next/navigation";

import { auth } from "@/auth";

/**
 * Data Access Layer: il punto in cui si verifica *davvero* chi sta chiedendo.
 *
 * Il proxy reindirizza chi non ha un cookie, ma gira prima del rendering e su
 * rotte prelevate in anticipo dal browser: è un filtro, non una garanzia. La
 * documentazione di Next.js è esplicita sul punto, e la conseguenza pratica è
 * questa: **ogni funzione che legge dal database chiama `requireSession()`
 * prima di leggere**. Una rotta nuova aggiunta fra sei mesi eredita la
 * protezione perché passa da qui, non perché qualcuno si ricorda di aggiungerla
 * a un elenco.
 */

/** Chi sta guardando la dashboard, o `null`. */
export const getSession = cache(async () => {
  // `cache` di React deduplica la verifica dentro una singola richiesta: una
  // pagina che rende testata, tabella e drawer la invocherebbe tre volte.
  const session = await auth();
  return session?.user?.email ? session : null;
});

/**
 * La sessione, o un reindirizzamento al login.
 *
 * Da usare nelle pagine e in ogni funzione di lettura. Non ritorna mai `null`:
 * o c'è una sessione, o l'esecuzione non prosegue.
 */
export async function requireSession() {
  const session = await getSession();
  if (!session) redirect("/login");
  return session;
}

/**
 * Come `requireSession`, ma per i route handler, dove un redirect verso una
 * pagina HTML sarebbe una risposta assurda a una richiesta JSON.
 */
export async function requireApiSession(): Promise<{ email: string } | null> {
  const session = await getSession();
  const email = session?.user?.email;
  return email ? { email } : null;
}

/** Risposta standard per le API quando la sessione manca. */
export function unauthorized() {
  return Response.json({ error: "non autorizzato" }, { status: 401 });
}
