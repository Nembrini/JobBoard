import { redirect } from "next/navigation";

import { signIn } from "@/auth";
import { getSession } from "@/lib/dal";

export const metadata = { title: "Accedi" };

/**
 * L'unica pagina raggiungibile senza sessione.
 *
 * Non dice quale account sia quello ammesso: sarebbe un indirizzo email
 * pubblicato su una pagina pubblica, cioè un regalo a chi raccoglie indirizzi.
 * Chi prova con un account diverso torna qui con un messaggio generico.
 */
export default async function LoginPage(props: PageProps<"/login">) {
  const params = await props.searchParams;
  if (await getSession()) redirect("/");

  const errore = typeof params.error === "string" ? params.error : null;
  const next = typeof params.next === "string" && params.next.startsWith("/") ? params.next : "/";

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="w-full max-w-sm space-y-8">
        <header className="space-y-2">
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Job Board</h1>
          <p className="text-muted-foreground text-sm leading-relaxed">
            Dashboard personale di ricerca lavoro. L&apos;accesso è limitato a un solo account.
          </p>
        </header>

        {errore ? (
          <p
            role="alert"
            className="border-destructive/30 bg-destructive/10 text-destructive rounded-lg border px-4 py-3 text-sm"
          >
            Accesso negato. Questo account non è abilitato.
          </p>
        ) : null}

        <form
          action={async () => {
            "use server";
            // `redirectTo` viene sanificato sopra: accettare un URL arbitrario
            // dalla query string trasformerebbe il login in un open redirect,
            // utile a chi vuole far atterrare qualcuno su un sito che somiglia
            // a questo dopo un login vero.
            await signIn("google", { redirectTo: next });
          }}
        >
          <button
            type="submit"
            className="border-input bg-background hover:bg-accent focus-visible:ring-ring flex h-11 w-full items-center justify-center gap-3 rounded-lg border text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
          >
            <GoogleMark />
            Continua con Google
          </button>
        </form>

        <p className="text-muted-foreground text-xs leading-relaxed">
          Il sito conserva il tuo CV e i tuoi dati personali su un database in Unione Europea, e
          può inviare candidature a tuo nome.
        </p>
      </div>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"
      />
    </svg>
  );
}
