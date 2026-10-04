/* THE APP'S THREE DATA ROUTES -- the one place their paths are written.

   The library listing, one picture's details record and the Generate dock's History feed are
   the reads nearly every surface shares (the grid, Details and the Lightbox, Publish, My Art,
   the job cards, Train, the Loom's gallery picker). Before this file each call site wrote the
   path out by hand; now they import it, so a rename is one line here.

   The read cache (hooks/swrStore.js) is keyed by request path and invalidated by PREFIX, so a
   write's invalidate([...]) list must name the route exactly as its reads do. Both sides import
   these constants, which is what keeps them in step (loom/test/api-routes.test.js).

   HISTORY OF THE NAMES. Until 3.17.0 they lived under /api/next/, the React app's pilot
   codename (#51 retired the /next page route and left these for their own change). The server
   answered the old /api/next/ paths for one release (3.17.0), on the same views, so a tab
   running an older cached bundle kept working; they are gone now, and such a tab needs a reload.
   Nothing in the front end may read the old paths -- loom/test/no-next-api-name.test.js allows
   them in this comment only. The /next/assets/ static prefix is a different thing and stays for
   good: installed phone apps read their icons from it. */

/** The paged library listing. Query parameters ride after it: LIBRARY + "?page=2". */
export const LIBRARY = "/api/library";

/** The prefix every per-picture details read starts with -- what an invalidation passes. */
export const DETAIL_PREFIX = "/api/detail/";

/** One picture's details record: its row, personal layer, neighbours and run. */
export function detail(mediaId) {
  return DETAIL_PREFIX + encodeURIComponent(mediaId);
}

/** The Generate dock's History feed. Query parameters ride after it: HISTORY + "?days=7". */
export const HISTORY = "/api/history";
