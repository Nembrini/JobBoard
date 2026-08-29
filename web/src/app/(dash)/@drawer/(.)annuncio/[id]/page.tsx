import { DrawerShell } from "@/components/drawer-shell";
import { MatchDetail } from "@/components/match-detail";
import { requireSession } from "@/lib/dal";

/**
 * L'annuncio aperto dalla lista: stessa rotta, disegnata come pannello.
 *
 * Il `(.)` intercetta `/annuncio/<id>` quando ci si arriva da dentro
 * l'applicazione. La lista sotto resta com'e' — non viene rinavigata e le sue
 * query non si rieseguono — e il tasto "indietro" chiude il pannello perche'
 * l'apertura e' stata una navigazione vera.
 */
export default async function AnnuncioInDrawer({ params }: PageProps<"/annuncio/[id]">) {
  await requireSession();
  const { id } = await params;

  return (
    <DrawerShell>
      <MatchDetail matchId={Number.parseInt(id, 10)} />
    </DrawerShell>
  );
}
