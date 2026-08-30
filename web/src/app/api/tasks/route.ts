import type { NextRequest } from "next/server";

import type { TaskType } from "@/db/schema";
import { unauthorized } from "@/lib/dal";
import { getLatestTask, getTask, NotAuthorized } from "@/lib/tasks";

/**
 * Lo stato di un task, per il componente di avanzamento.
 *
 * Esiste per non far ricaricare la pagina intera ogni tre secondi. La
 * dashboard fa tre query e il drawer altre due: rifarle a ogni giro per
 * aggiornare una barra sarebbe un carico ricorrente su Supabase per un dato
 * che sta in una riga sola.
 *
 * `?id=` quando si sta seguendo un lavoro preciso — è il caso normale, perché
 * chi preme il bottone sa quale ha accodato. `?type=` al primo caricamento,
 * per ritrovare un lavoro accodato da un altro dispositivo.
 */

const TIPI: TaskType[] = [
  "run_pipeline",
  "generate_cv",
  "apply",
  "reparse_profile",
  "check_email",
];

export async function GET(request: NextRequest) {
  const parametri = request.nextUrl.searchParams;
  const id = parametri.get("id");
  const tipo = parametri.get("type");

  try {
    if (id !== null) {
      const numero = Number.parseInt(id, 10);
      if (!Number.isFinite(numero)) {
        return Response.json({ error: "id non valido" }, { status: 400 });
      }
      return Response.json({ task: await getTask(numero) });
    }

    if (tipo === null || !TIPI.includes(tipo as TaskType)) {
      return Response.json({ error: `type richiesto: ${TIPI.join(", ")}` }, { status: 400 });
    }
    return Response.json({ task: await getLatestTask(tipo as TaskType) });
  } catch (error) {
    if (error instanceof NotAuthorized) return unauthorized();
    throw error;
  }
}
