import Link from "next/link";

import { CandidatureTable } from "@/components/candidature-table";
import { CheckEmailBar } from "@/components/check-email-bar";
import { ResponseMetrics } from "@/components/response-metrics";
import { SiteHeader } from "@/components/site-header";
import { getCandidature, getResponseMetrics } from "@/lib/candidature";
import { requireSession } from "@/lib/dal";
import { getWorkerStatus } from "@/lib/queries";
import { getLatestTask } from "@/lib/tasks";

export const metadata = { title: "Candidature" };

/**
 * La pagina Candidature (Fase 9): tracking post-invio.
 *
 * Diversa dalla pagina dell'annuncio, che segue **una** candidatura mentre si
 * prepara — CV, approvazione, invio. Questa segue **tutte** quelle già
 * partite, dopo: cosa ha risposto chi, e con quale tasso. Gli stati qui sono
 * aggiornabili a mano perché una mail può sfuggire alla correlazione IMAP
 * (§`imap_reader.looks_related`) — meglio poterla correggere in dieci secondi
 * che aspettare che il worker la riconosca da solo.
 */
export default async function CandidaturePage(props: PageProps<"/candidature">) {
  await requireSession();
  const { page: pageParam } = await props.searchParams;
  const page = Math.max(1, Number(pageParam) || 1);

  const [candidature, metriche, worker, controllo] = await Promise.all([
    getCandidature(page),
    getResponseMetrics(),
    getWorkerStatus(),
    getLatestTask("check_email"),
  ]);

  return (
    <>
      <SiteHeader current="candidature" />

      <main className="mx-auto w-full max-w-5xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Candidature</h1>
          <p className="text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
            Cosa succede dopo l&apos;invio: stati aggiornati dalle risposte lette in posta, o corretti
            a mano quando una mail sfugge. Il controllo email va acceso nelle{" "}
            <Link href="/impostazioni" className="underline underline-offset-2">
              Impostazioni
            </Link>
            .
          </p>
        </div>

        <CheckEmailBar taskIniziale={controllo} workerOnline={worker.online} />

        <ResponseMetrics metriche={metriche} />

        <CandidatureTable righe={candidature.righe} />

        {candidature.pageCount > 1 ? (
          <nav className="flex items-center justify-between gap-4 pt-2" aria-label="Paginazione">
            <p className="text-muted-foreground text-sm">
              Pagina <span className="num">{candidature.page}</span> di{" "}
              <span className="num">{candidature.pageCount}</span> ·{" "}
              <span className="num">{candidature.totale}</span> candidature
            </p>
            <div className="flex gap-2">
              {candidature.page > 1 ? (
                <Link
                  href={`/candidature?page=${candidature.page - 1}`}
                  className="border-input hover:bg-accent inline-flex h-10 items-center rounded-lg border px-4 text-sm font-medium"
                >
                  Precedente
                </Link>
              ) : null}
              {candidature.page < candidature.pageCount ? (
                <Link
                  href={`/candidature?page=${candidature.page + 1}`}
                  className="border-input hover:bg-accent inline-flex h-10 items-center rounded-lg border px-4 text-sm font-medium"
                >
                  Successiva
                </Link>
              ) : null}
            </div>
          </nav>
        ) : null}
      </main>
    </>
  );
}
