import "server-only";

/**
 * Il minimo indispensabile di Supabase Storage, via REST.
 *
 * Niente `@supabase/supabase-js`: di quella libreria servirebbero tre chiamate
 * su una superficie che porta con sé un client Postgres, uno realtime e uno
 * auth. Tre `fetch` sono meno codice di quanto ne servirebbe per configurarla.
 *
 * La service role key **scavalca ogni policy di riga**: vive solo qui, in un
 * modulo `server-only`, e non compare mai in una risposta.
 */

const BUCKET = process.env.SUPABASE_STORAGE_BUCKET || "resumes";

function base(): string {
  const url = process.env.SUPABASE_URL;
  if (!url) throw new Error("SUPABASE_URL non impostata");
  return `${url.replace(/\/+$/, "")}/storage/v1`;
}

function auth(): Record<string, string> {
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) throw new Error("SUPABASE_SERVICE_ROLE_KEY non impostata");
  return { Authorization: `Bearer ${key}`, apikey: key };
}

/**
 * Carica un file e restituisce il percorso dentro il bucket.
 *
 * Il percorso contiene un timestamp perché **caricare un CV nuovo non deve
 * cancellare il precedente**: finché il worker non ha finito di rielaborarlo,
 * il vecchio è ancora quello buono, e se l'estrazione fallisce è l'unica copia
 * rimasta.
 */
export async function uploadCv(file: File): Promise<string> {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const percorso = `cv/${stamp}-${sanitize(file.name)}`;

  const risposta = await fetch(`${base()}/object/${BUCKET}/${percorso}`, {
    method: "POST",
    headers: {
      ...auth(),
      "content-type": file.type || "application/octet-stream",
      "cache-control": "3600",
    },
    body: file,
  });

  if (!risposta.ok) {
    throw new Error(`caricamento fallito (${risposta.status}): ${await risposta.text()}`);
  }
  return percorso;
}

/** Cancella un oggetto. Un errore qui non è fatale: lo si segnala e si prosegue. */
export async function removeObject(percorso: string): Promise<boolean> {
  const risposta = await fetch(`${base()}/object/${BUCKET}/${percorso}`, {
    method: "DELETE",
    headers: auth(),
  });
  return risposta.ok;
}

/**
 * URL temporaneo per scaricare il file originale.
 *
 * Il bucket è privato, e resta privato: mai un URL pubblico, nemmeno con la
 * scusa che tanto non è indicizzato. Cinque minuti bastano a un click.
 */
export async function signedUrl(percorso: string, secondi = 300): Promise<string | null> {
  // `null` anche quando la richiesta non parte affatto. Chi chiama sa gia'
  // gestire l'assenza di URL — mostra la scheda senza il bottone di download,
  // l'anteprima senza il riquadro — mentre un'eccezione qui farebbe cadere
  // l'intera pagina che conteneva il link. Un bucket irraggiungibile non deve
  // poter nascondere il punteggio di un annuncio.
  try {
    const risposta = await fetch(`${base()}/object/sign/${BUCKET}/${percorso}`, {
      method: "POST",
      headers: { ...auth(), "content-type": "application/json" },
      body: JSON.stringify({ expiresIn: secondi }),
    });
    if (!risposta.ok) return null;

    const dati = (await risposta.json()) as { signedURL?: string };
    return dati.signedURL ? `${base()}${dati.signedURL.replace(/^\/storage\/v1/, "")}` : null;
  } catch (errore) {
    console.error("URL firmato non ottenuto per", percorso, errore);
    return null;
  }
}

/** Un nome file che non possa uscire dalla cartella né rompere un URL. */
function sanitize(nome: string): string {
  return (
    nome
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .replace(/^[._]+/, "")
      .slice(-120) || "cv"
  );
}
