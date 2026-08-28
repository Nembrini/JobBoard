import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

// Modulo SOLO server. Non deve mai finire in un client component: la connection
// string contiene la password del database.
import "server-only";

import { SUPABASE_ROOT_CA } from "./supabase-ca";

/**
 * Il client Postgres della dashboard.
 *
 * **Perché `pg` e non `postgres` (postgres-js).** Il secondo, che era la scelta
 * iniziale, sotto Next.js 16 serve *una sola richiesta* e poi smette: la prima
 * query risponde in 150 ms, dalla seconda in poi la connessione riutilizzata
 * non restituisce più niente. Nessun errore, nessun timeout — la richiesta si
 * chiude solo quando è il browser a rinunciare, e da fuori sembra un database
 * lento. Succede identico in sviluppo e nella build di produzione, quindi non
 * era un problema del solo dev server. Fuori da Next lo stesso client fa
 * quattro query a distanza di secondi senza un intoppo, e `pg` dentro Next
 * regge il riutilizzo: 164 ms la prima, 18 ms le successive.
 *
 * Il singleton è **di modulo e non su `globalThis`**, che è il rimedio che si
 * trova ovunque per l'accumulo di connessioni in sviluppo. Next valuta i moduli
 * in più contesti e `globalThis` è condiviso fra questi, il socket TCP no: il
 * primo contesto a chiamare la funzione deposita lì il suo client, e se non è
 * quello che serve le richieste il risultato è di nuovo una query che non
 * torna. Con un singleton di modulo una rivalutazione produce un client nuovo e
 * il vecchio chiude la connessione da solo per inattività.
 */

let pool: Pool | undefined;
let orm: ReturnType<typeof drizzle> | undefined;

function createPool() {
  const connectionString = process.env.POSTGRES_URL;
  if (!connectionString) {
    throw new Error("POSTGRES_URL non impostata (pooler Supavisor di Supabase).");
  }

  return new Pool({
    connectionString,
    // Le funzioni serverless sono effimere e concorrenti: una connessione
    // ciascuna, altrimenti si esaurisce il pool lato Supabase.
    max: 1,
    idleTimeoutMillis: 20_000,
    connectionTimeoutMillis: 10_000,
    ssl: {
      // Senza questo blocco `pg` si collega **in chiaro**, perché la connection
      // string di Supabase non porta `sslmode`. Con la sola
      // `rejectUnauthorized` fallisce, perché la catena si chiude su una CA
      // privata: serve fissarla.
      ca: SUPABASE_ROOT_CA,
      rejectUnauthorized: true,
      // Il certificato è emesso per *.pooler.supabase.com, che è l'host a cui ci
      // si collega: la verifica del nome resta attiva.
    },
  });
}

/** Il pool grezzo, per le rare query che non passano da Drizzle. */
export function getPool() {
  pool ??= createPool();
  return pool;
}

/**
 * Drizzle, con lo schema generato da `jobboard gen-web-schema` dai modelli
 * SQLAlchemy — che restano l'unica fonte di verità dello schema.
 *
 * Nota su Supavisor in transaction mode: non si usano prepared statement con
 * nome, che il pooler reindirizzerebbe a sessioni diverse facendo fallire query
 * perfettamente valide. È il motivo per cui il codice non chiama `.prepare()`.
 */
export function getDb() {
  orm ??= drizzle(getPool(), { casing: "snake_case" });
  return orm;
}
