import { drizzle } from "drizzle-orm/postgres-js";
import postgres from "postgres";

// Modulo SOLO server. Non deve mai finire in un client component: la connection
// string contiene la password del database.
import "server-only";

const connectionString = process.env.POSTGRES_URL;
if (!connectionString) {
  throw new Error("POSTGRES_URL non impostata (pooler Supavisor di Supabase).");
}

declare global {
  // eslint-disable-next-line no-var
  var __jobboardSql: ReturnType<typeof postgres> | undefined;
}

function createClient() {
  return postgres(connectionString!, {
    // Obbligatorio con il pooler Supavisor in transaction mode: i prepared statement
    // sopravvivono alla connessione fisica e il pooler li reindirizza a sessioni
    // diverse, facendo fallire query che in locale funzionano.
    prepare: false,
    // Le funzioni serverless sono effimere e concorrenti: una connessione ciascuna,
    // altrimenti si esaurisce il pool lato Supabase.
    max: 1,
    idle_timeout: 20,
    connect_timeout: 10,
  });
}

// In dev Next ricarica i moduli a ogni salvataggio: senza cache globale si
// accumulerebbero connessioni fino a saturare il pool.
const sql = globalThis.__jobboardSql ?? createClient();
if (process.env.NODE_ENV !== "production") {
  globalThis.__jobboardSql = sql;
}

// Lo schema arriva da `npx drizzle-kit pull`, che lo genera dal database reale.
// Fonte di verita': i modelli SQLAlchemy in worker/jobboard/models/.
export const db = drizzle(sql, { casing: "snake_case" });
export { sql };
