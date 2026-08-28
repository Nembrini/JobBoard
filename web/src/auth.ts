import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

/**
 * Auth.js con Google, e una allowlist di **un solo indirizzo**.
 *
 * La dashboard sta su un URL pubblico e mostra il CV, i dati personali e un
 * bottone che invia candidature. "Chi vuoi che la trovi" non è un modello di
 * sicurezza: l'URL di un progetto Vercel è indovinabile, e i crawler lo trovano
 * comunque.
 *
 * Il controllo sta nel callback `signIn`, non in una pagina: chiunque può fare
 * login con Google, ma solo l'indirizzo in `AUTH_ALLOWED_EMAIL` ottiene una
 * sessione. Gli altri vengono respinti prima che esista un cookie.
 */

/** L'unico account ammesso. Confronto in minuscolo: Google restituisce l'email
 *  con la capitalizzazione scelta dall'utente, che può cambiare. */
const allowed = (process.env.AUTH_ALLOWED_EMAIL ?? "").trim().toLowerCase();

if (!allowed && process.env.NODE_ENV === "production") {
  // Meglio un deploy che non parte di uno che parte aperto a tutti: senza
  // allowlist il callback lascerebbe entrare qualunque account Google.
  throw new Error(
    "AUTH_ALLOWED_EMAIL non impostata: la dashboard resterebbe accessibile a chiunque abbia un account Google.",
  );
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [Google],
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    /** L'unico punto in cui si decide chi entra. */
    signIn({ profile }) {
      // `email_verified` conta: senza, un account con un'email non verificata
      // potrebbe dichiarare un indirizzo che non gli appartiene.
      if (!profile?.email || profile.email_verified === false) return false;
      return profile.email.toLowerCase() === allowed;
    },
    /** L'email finisce nel token JWT, così le pagine non devono interrogare Google. */
    jwt({ token, profile }) {
      if (profile?.email) token.email = profile.email;
      return token;
    },
    session({ session, token }) {
      if (token.email) session.user.email = token.email;
      return session;
    },
  },
  session: {
    strategy: "jwt",
    // Trenta giorni: è un'app personale usata dal telefono, e rifare il login
    // ogni settimana sarebbe l'unico motivo per smettere di aprirla.
    maxAge: 60 * 60 * 24 * 30,
  },
});
