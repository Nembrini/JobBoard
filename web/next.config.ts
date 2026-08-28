import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `pg` parla il protocollo di Postgres su socket TCP: va caricato con il
  // `require` di Node e non impacchettato insieme al resto del server.
  serverExternalPackages: ["pg"],
};

export default nextConfig;
