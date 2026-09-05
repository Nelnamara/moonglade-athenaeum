/* THE CLIENT READ CACHE -- the store half, and it imports NOTHING on purpose.

   Same reason hooks/contestSyncFlow.js imports nothing: the behaviour worth pinning here
   is not React's, it is the STORE's -- what gets written, what is refused, and what an
   invalidation actually removes. Extracted, every one of those is a plain assertion a
   node test can make with no renderer, no DOM and no fetch (loom/test/swr-cache.test.js).
   hooks/swrCache.js is the React-facing half: it re-exports these three verbs and adds
   useSwrGet, which is the only place any of this touches a component.

   WHAT THIS IS. useHealth.js has carried a one-value version of this since 2026-08-06
   (its own `_lastHealth`, and its comment is the rationale in full): the last payload
   survives across opens for the whole page session, so a REOPEN paints last-known numbers
   instantly while the refetch replaces them in place. Every nav overlay wants exactly
   that and each was re-deciding it, or not doing it at all -- so it lives here once,
   keyed by request path, and useHealth's own module-level variable is now this map.

   TWO REFUSALS, and they are the whole safety story:

     1. AN ERROR IS NEVER CACHED. api.js's one rule is that a body carrying {error} is the
        failure answer whatever the HTTP status said -- including a 200. Storing one would
        pin an offline blip (or a refusal) as this session's "last known good" and serve it
        to every later reopen, which is worse than the slow paint this cache exists to
        remove. put() refuses anything that is not a plain object, and anything carrying a
        truthy `error`.
     2. A CSRF TOKEN IS NEVER CACHED. /api/myart/items answers with `csrf` alongside its
        items, and that token is a moving value (see api.js's "CSRF IS NOT DONE HERE"
        note -- LoginPage's rotates on every failed attempt). A cached token would be
        handed to a POST that can only be refused, so put() drops any top-level `csrf`
        from what it stores. Callers that need a token read it from the LIVE answer; this
        is structural, not a convention each call site has to remember.

   WHAT COMES BACK IS READ-ONLY. peek() hands out the stored object itself (not a copy),
   exactly as `_lastHealth` did -- the identity is stable, so seeding a useState from it
   and then setting the same object again is a no-op React bails out of. Treat it as
   frozen: build a new object rather than mutating one you peeked. */

const _store = new Map();

const _isPlainPayload = (d) => !!d && typeof d === "object" && !Array.isArray(d);

/** The last successful payload for `path`, or null if there has never been one. */
export function peek(path) {
  if (!path) return null;
  const hit = _store.get(String(path));
  return hit === undefined ? null : hit;
}

/** Write-through after a SUCCESSFUL read. Returns true if it was actually stored.
    Refuses errors and strips any csrf -- see the two refusals above. */
export function put(path, data) {
  if (!path || !_isPlainPayload(data) || data.error) return false;
  let keep = data;
  if ("csrf" in data) {
    keep = { ...data };
    delete keep.csrf;
  }
  _store.set(String(path), keep);
  return true;
}

/** Drop every cached path that STARTS WITH `prefix` (a string, or an array of them).
    Prefix, not equality, because one mutation invalidates a family: "/api/next/detail/"
    covers every per-image record without the caller knowing which ids are cached, and
    "/api/next/library" covers every page/filter querystring built on it.
    A falsy prefix removes NOTHING -- a mistyped call must not silently empty the cache.
    Returns how many entries were removed. */
export function invalidate(prefix) {
  const list = (Array.isArray(prefix) ? prefix : [prefix]).filter(Boolean).map(String);
  if (!list.length) return 0;
  let n = 0;
  for (const key of [..._store.keys()]) {
    if (list.some((p) => key.startsWith(p))) { _store.delete(key); n += 1; }
  }
  return n;
}

/** Tests only: an empty store, with no prefix-shaped foot-gun in the shipped API. */
export function _reset() {
  _store.clear();
}
