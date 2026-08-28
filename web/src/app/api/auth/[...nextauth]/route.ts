import { handlers } from "@/auth";

// Auth.js gestisce da sé tutte le rotte sotto /api/auth: login, callback,
// signout, sessione. Il filtro su chi può entrare sta nel callback `signIn`
// definito in src/auth.ts.
export const { GET, POST } = handlers;
