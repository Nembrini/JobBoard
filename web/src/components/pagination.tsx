import Link from "next/link";

/**
 * Paginazione a link, non a bottoni.
 *
 * Sono `<a>` veri con un href: funzionano senza JavaScript, si aprono in una
 * scheda nuova con il tasto centrale e il browser li prefetcha. Un `onClick`
 * che chiama `router.push` non fa nessuna di queste tre cose.
 */
export function Pagination({
  page,
  pageCount,
  total,
  searchParams,
}: {
  page: number;
  pageCount: number;
  total: number;
  searchParams: URLSearchParams;
}) {
  if (pageCount <= 1) return null;

  function href(n: number): string {
    const p = new URLSearchParams(searchParams);
    if (n <= 1) p.delete("page");
    else p.set("page", String(n));
    const query = p.toString();
    return query ? `/?${query}` : "/";
  }

  return (
    <nav className="flex items-center justify-between gap-4 pt-2" aria-label="Paginazione">
      <p className="text-muted-foreground text-sm">
        Pagina {page} di {pageCount} · {total} annunci
      </p>
      <div className="flex gap-2">
        {page > 1 ? (
          <Link href={href(page - 1)} scroll className="border-input hover:bg-accent inline-flex h-9 items-center rounded-lg border px-3 text-sm">
            Precedente
          </Link>
        ) : null}
        {page < pageCount ? (
          <Link href={href(page + 1)} scroll className="border-input hover:bg-accent inline-flex h-9 items-center rounded-lg border px-3 text-sm">
            Successiva
          </Link>
        ) : null}
      </div>
    </nav>
  );
}
