import { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import { peek, put, invalidate } from "./swrStore.js";

/* THE CLIENT READ CACHE -- the React half. The store's own rules (what is refused, what
   an invalidation removes, why an error and a csrf are never written) live in
   hooks/swrStore.js, which imports nothing so a node test can drive them; this file adds
   the one hook and re-exports the three verbs so a consumer has a single import.

   THE SHAPE, and it is useHealth.js's own, generalized (that file has carried a one-value
   version since 2026-08-06): seed the state from the store, fetch on mount behind the
   standard dead-flag, write through on success. A reopen therefore paints last-known data
   in the first frame and swaps in the fresh answer when it lands -- the first open of a
   session still waits, which is what the server-side memos attack instead.

   WHAT MUST NOT RIDE THIS. Three kinds of read are deliberately left uncached, and the
   rule is "would a stale answer be wrong, not just old":
     - every csrf token (the store drops the field outright; see swrStore.js),
     - GET /api/next/detail/<mid> in Publish -- a stale artwork_id re-enables a Publish
       button for a piece that is already published,
     - GET /api/panel/status (the live-job resume check) and GET /api/ping (the
       restart watch): both exist to answer "what is true RIGHT NOW". */

export { peek, put, invalidate };

/** Stale-while-revalidate GET. Returns {data, err}: `data` is the cached payload on the
    first frame of a reopen and the fresh one once it lands; `err` is set ONLY when there
    is nothing cached to keep showing -- a failed refresh must not blank out (or paint an
    error banner over) numbers that are merely a few seconds old. */
export function useSwrGet(path) {
  const [data, setData] = useState(() => peek(path));
  const [err, setErr] = useState(null);

  useEffect(() => {
    let dead = false;
    // Re-seed here as well as in the initializer so a CHANGING path still paints from the
    // store; peek hands back the same object the state already holds on a plain mount, so
    // React bails out of this one rather than rendering twice.
    const cached = peek(path);
    if (cached != null) setData(cached);
    apiGet(path).then((d) => {
      if (dead) return;
      if (d && d.error) {
        if (peek(path) == null) setErr(d.error);
        return;
      }
      put(path, d);
      setData(d);
      setErr(null);
    });
    return () => { dead = true; };
  }, [path]);

  return { data, err };
}
