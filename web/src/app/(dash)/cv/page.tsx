import { CircleAlert } from "lucide-react";

import { ConfirmBanner } from "@/components/cv/confirm-banner";
import { CvFileCard, CvVuoto } from "@/components/cv/cv-file-card";
import { ProfileEditor } from "@/components/cv/profile-editor";
import { SiteHeader } from "@/components/site-header";
import { requireSession } from "@/lib/dal";
import { getProfile, getReparseTask } from "@/lib/profile";
import { getWorkerStatus } from "@/lib/queries";
import { signedUrl } from "@/lib/storage";

export const metadata = { title: "CV" };

/**
 * La sezione CV.
 *
 * Mostra **il profilo come lo legge la macchina**, non un'anteprima del PDF: il
 * PDF si può già aprire, mentre quello che decide ogni punteggio e ogni frase
 * di ogni CV generato è il JSON strutturato che sta sotto. Un'estrazione
 * sbagliata qui non si vede da nessun'altra parte — si vede solo nei punteggi,
 * mesi dopo, come una compatibilità che non torna.
 *
 * L'ordine delle sezioni è quello dell'importanza a valle: prima il file, poi i
 * recapiti che finiscono nei form ATS, poi le esperienze con i loro punti, che
 * sono la materia prima del CV su misura.
 */
export default async function CvPage() {
  await requireSession();

  const [profilo, task, worker] = await Promise.all([
    getProfile(),
    getReparseTask(),
    getWorkerStatus(),
  ]);

  const download = profilo?.sourceStoragePath ? await signedUrl(profilo.sourceStoragePath) : null;

  return (
    <>
      <SiteHeader current="cv" />

      <main className="mx-auto w-full max-w-4xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Il tuo CV</h1>
          <p className="text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
            Quello che il sistema legge quando calcola una compatibilità, e l&apos;unica fonte da
            cui un CV su misura potrà attingere. Correggere un errore qui vale più di qualsiasi
            taratura dei pesi.
          </p>
        </div>

        {profilo === null ? (
          <CvVuoto />
        ) : (
          <>
            <CvFileCard
              fileName={profilo.sourceFileName}
              caricatoIl={dataIt(profilo.createdAt)}
              reviewed={profilo.reviewed}
              embeddingModel={profilo.embeddingModel}
              embeddingDim={profilo.embeddingDim}
              downloadUrl={download}
              workerOnline={worker.online}
              taskInCorso={task}
            />

            {!profilo.reviewed ? <ConfirmBanner /> : null}

            {profilo.sourceStoragePath === null ? (
              <Avviso>
                Il file originale non è in archivio: questo profilo è stato importato da riga di
                comando, che legge il PDF dal disco e non lo carica. Il prossimo CV caricato da qui
                resterà scaricabile.
              </Avviso>
            ) : null}

            {profilo.embeddingObsoleto ? (
              <Avviso>
                Il profilo è cambiato dopo l&apos;ultimo calcolo del vettore. Finché il worker non
                lo ricalcola, i punteggi in elenco restano quelli di prima:{" "}
                <span className="num">.\jb profile embed</span> lo aggiorna subito, altrimenti
                succede alla prossima run.
              </Avviso>
            ) : null}

            {profilo.invalido ? (
              <Avviso grave>
                Il profilo salvato non supera più la validazione ({profilo.invalido}). Va
                ricaricato o corretto da riga di comando: modificarlo da qui riscriverebbe sopra un
                dato che non si riesce a leggere per intero.
              </Avviso>
            ) : profilo.masterProfile ? (
              <ProfileEditor iniziale={profilo.masterProfile} />
            ) : null}
          </>
        )}
      </main>
    </>
  );
}

function Avviso({ grave = false, children }: { grave?: boolean; children: React.ReactNode }) {
  return (
    <p
      className={`flex gap-3 rounded-xl border p-4 text-sm leading-relaxed ${
        grave ? "border-destructive/40 bg-destructive/5" : "bg-muted/40"
      }`}
    >
      <CircleAlert
        className={`mt-0.5 size-4 shrink-0 ${grave ? "text-destructive" : "text-amber-500"}`}
      />
      <span>{children}</span>
    </p>
  );
}

function dataIt(d: Date): string {
  return new Intl.DateTimeFormat("it-IT", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(d);
}
