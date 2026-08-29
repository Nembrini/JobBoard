import { requireApiSession, unauthorized } from "@/lib/dal";
import { enqueueReparse } from "@/lib/profile";
import { removeObject, uploadCv } from "@/lib/storage";

/**
 * Caricamento di un CV nuovo.
 *
 * Un route handler e non una Server Action: le azioni serializzano gli
 * argomenti nel payload della richiesta, mentre qui passa un PDF di qualche
 * megabyte, che va spedito come `multipart/form-data` e mai tenuto tutto in
 * memoria più del necessario.
 *
 * Il file **non viene elaborato qui**. Estrarre il testo da un PDF, farlo
 * strutturare a un LLM e ricalcolare l'embedding sono le tre cose che il piano
 * mette sul PC di casa: su una funzione serverless non ci starebbero né come
 * dipendenze né come tempo. La dashboard fa le due cose che sa fare — mette il
 * file al sicuro e accoda il lavoro — e l'esito lo mostra la pagina.
 */

/** Oltre questa soglia non è più un CV: è un CV con dentro delle immagini. */
const MAX_BYTE = 10 * 1024 * 1024;

const TIPI = new Map<string, string>([
  ["application/pdf", ".pdf"],
  ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"],
]);

export async function POST(request: Request) {
  if (!(await requireApiSession())) return unauthorized();

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ errore: "richiesta malformata" }, { status: 400 });
  }

  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return Response.json({ errore: "nessun file" }, { status: 400 });
  }

  if (file.size > MAX_BYTE) {
    return Response.json(
      { errore: `il file supera ${Math.round(MAX_BYTE / 1024 / 1024)} MB` },
      { status: 413 },
    );
  }

  // Si controllano tipo dichiarato **e** estensione. Il tipo lo sceglie il
  // browser e si può falsificare; l'estensione la sceglie chi carica. Nessuno
  // dei due è una garanzia, ma il file finisce in un bucket privato e a
  // interpretarlo sarà un parser PDF che rifiuta ciò che non riconosce: qui
  // basta fermare gli sbagli, non gli attacchi.
  const atteso = TIPI.get(file.type);
  const nome = file.name.toLowerCase();
  if (!atteso || !(nome.endsWith(".pdf") || nome.endsWith(".docx"))) {
    return Response.json({ errore: "sono ammessi solo PDF e DOCX" }, { status: 415 });
  }

  // Il motivo vero del fallimento torna al browser, non solo ai log del server.
  // Di solito e' una scelta da evitare, ma qui l'unico destinatario e' l'unico
  // account in allowlist, e la lezione e' gia' stata pagata una volta: un
  // "caricamento fallito" generico manda a cercare il problema nel file, nella
  // rete e nel browser prima di arrivare al bucket. Il passo che ha ceduto vale
  // piu' di qualunque diagnosi a posteriori.
  let percorso: string;
  try {
    percorso = await uploadCv(file);
  } catch (errore) {
    console.error("caricamento CV su Supabase Storage fallito", errore);
    return Response.json({ errore: `archiviazione: ${messaggio(errore)}` }, { status: 502 });
  }

  try {
    const taskId = await enqueueReparse(percorso, file.name);
    return Response.json({ taskId, percorso }, { status: 202 });
  } catch (errore) {
    console.error("accodamento reparse_profile fallito", errore);
    // Il file e' gia' nel bucket ma nessuno verra' a prenderlo: senza questa
    // riga ogni tentativo fallito lascerebbe un PDF che nessuna riga del
    // database nomina, quindi che nessuno cancellera' mai piu'.
    await removeObject(percorso).catch(() => false);
    return Response.json({ errore: `coda: ${messaggio(errore)}` }, { status: 502 });
  }
}

function messaggio(errore: unknown): string {
  return errore instanceof Error ? errore.message : String(errore);
}
