import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { MatchDetail } from "@/components/match-detail";
import { SiteHeader } from "@/components/site-header";
import { requireSession } from "@/lib/dal";

export const metadata = { title: "Annuncio" };

/**
 * L'annuncio come pagina intera.
 *
 * E' la versione che si vede ricaricando, arrivando da un link condiviso o da
 * una notifica: casi in cui non c'e' nessuna lista sotto da lasciare aperta, e
 * un pannello sospeso sul vuoto sarebbe solo una pagina con i bordi arrotondati.
 */
export default async function AnnuncioPage({ params }: PageProps<"/annuncio/[id]">) {
  await requireSession();
  const { id } = await params;

  return (
    <>
      <SiteHeader current="annunci" />
      <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground mb-2 inline-flex items-center gap-2 text-sm"
        >
          <ArrowLeft className="size-4" />
          Tutti gli annunci
        </Link>
        <MatchDetail matchId={Number.parseInt(id, 10)} />
      </main>
    </>
  );
}
