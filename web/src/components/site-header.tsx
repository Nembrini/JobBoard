import Link from "next/link";
import { Suspense } from "react";

import { signOut } from "@/auth";
import { WorkerStatus } from "@/components/worker-status";

/**
 * La testata, condivisa da tutte le sezioni.
 *
 * Restano poche voci in una barra piatta, non un menu: un menu a tendina per
 * quattro destinazioni nasconde la navigazione dietro un click senza far
 * risparmiare spazio davvero.
 *
 * `LinkTab` decide l'aspetto dal `current` che riceve dal server, non da
 * `usePathname`: la voce attiva e' gia' giusta nell'HTML, senza un componente
 * client che deve prima idratarsi per colorare una scheda.
 */
export function SiteHeader({
  current,
  subtitle,
}: {
  current: "annunci" | "cv" | "impostazioni" | "cronologia";
  subtitle?: React.ReactNode;
}) {
  return (
    <header className="border-b">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-baseline gap-4">
          <span className="font-heading text-lg font-semibold tracking-tight">Job Board</span>
          <nav aria-label="Sezioni" className="flex items-center gap-1">
            <LinkTab href="/" active={current === "annunci"}>
              Annunci
            </LinkTab>
            <LinkTab href="/cv" active={current === "cv"}>
              CV
            </LinkTab>
            <LinkTab href="/cronologia" active={current === "cronologia"}>
              Cronologia
            </LinkTab>
            <LinkTab href="/impostazioni" active={current === "impostazioni"}>
              Impostazioni
            </LinkTab>
          </nav>
        </div>

        <div className="ml-auto flex items-center gap-5">
          {/* L'heartbeat e' una query in piu': se e' lenta non deve trattenere
              il contenuto, che e' il motivo per cui si apre la pagina. */}
          <Suspense fallback={<span className="text-muted-foreground text-sm">worker …</span>}>
            <WorkerStatus />
          </Suspense>
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/login" });
            }}
          >
            <button
              type="submit"
              className="text-muted-foreground hover:text-foreground rounded-md text-sm underline-offset-4 hover:underline"
            >
              Esci
            </button>
          </form>
        </div>

        {subtitle ? (
          <p className="text-muted-foreground w-full text-sm">{subtitle}</p>
        ) : null}
      </div>
    </header>
  );
}

function LinkTab({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
        active ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </Link>
  );
}
