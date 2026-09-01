import { AutoWorkerForm } from "@/components/settings/auto-worker-form";
import { NotificationsForm } from "@/components/settings/notifications-form";
import { TrackingForm } from "@/components/settings/tracking-form";
import { SiteHeader } from "@/components/site-header";
import { getAutoWorkerSettings } from "@/lib/auto-worker-settings";
import { requireSession } from "@/lib/dal";
import { getNotificationSettings } from "@/lib/notifications";
import { getTrackingSettings } from "@/lib/tracking-settings";

export const metadata = { title: "Impostazioni" };

/**
 * La pagina Impostazioni: avvio automatico, digest email, tracciamento.
 *
 * Separata dalla pagina CV perché risponde a una domanda diversa — non "cosa
 * sa il sistema di te" ma "cosa deve fare da solo, e quando disturbarti" — e
 * perché crescerà: soglia e criteri di matching (`pipeline.criteria`), oggi
 * modificabili solo da `worker/.env`, sono il prossimo candidato naturale.
 */
export default async function ImpostazioniPage() {
  await requireSession();
  const [avvioAutomatico, notifiche, tracciamento] = await Promise.all([
    getAutoWorkerSettings(),
    getNotificationSettings(),
    getTrackingSettings(),
  ]);

  return (
    <>
      <SiteHeader current="impostazioni" />

      <main className="mx-auto w-full max-w-4xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
        <div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Impostazioni</h1>
          <p className="text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
            Preferenze che il worker legge a ogni run, senza bisogno di riavviarlo.
          </p>
        </div>

        <AutoWorkerForm iniziale={avvioAutomatico} />
        <NotificationsForm iniziale={notifiche} />
        <TrackingForm iniziale={tracciamento} />
      </main>
    </>
  );
}
