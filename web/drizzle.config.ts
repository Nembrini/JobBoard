import { defineConfig } from "drizzle-kit";

// Le migration NON si fanno da qui: lo schema e' definito dai modelli SQLAlchemy nel
// worker e applicato con Alembic. Drizzle serve solo in *introspezione*
// (`npx drizzle-kit pull`) per generare i tipi TypeScript dal database reale, cosi'
// non esiste una seconda definizione dello schema che possa divergere dalla prima.
//
// Flusso corretto quando cambia una colonna:
//   1. modifica il modello in  worker/jobboard/models/
//   2. worker>  alembic revision --autogenerate -m "..."  &&  alembic upgrade head
//   3. web>     npx drizzle-kit pull

try {
  // Next.js legge .env.local a runtime, drizzle-kit no: va caricato a mano.
  process.loadEnvFile(".env.local");
} catch {
  // Assente in CI o su Vercel, dove le variabili arrivano dall'ambiente.
}

const url = process.env.POSTGRES_URL;
if (!url) {
  throw new Error(
    "POSTGRES_URL non impostata. Serve la connection string del pooler Supavisor " +
      "di Supabase, in web/.env.local (vedi .env.example nella root).",
  );
}

export default defineConfig({
  dialect: "postgresql",
  out: "./src/db",
  schema: "./src/db/schema.ts",
  dbCredentials: { url },
  casing: "snake_case",
  // Il worker non tocca lo schema `auth`/`storage` gestito da Supabase: introspettarli
  // genererebbe centinaia di tipi inutili.
  schemaFilter: ["public"],
  verbose: true,
  strict: true,
});
