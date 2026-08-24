/* THE ONE PRICE TRANSPORT (2026-08-23).

   Every `POST /api/price` in this app goes through requestPrice -- the gallery's probe
   (gen/usePriceProbe.js) and the Loom's own priceBody/priceShot alike. It is the ONLY file
   under gallery/src that names /api/price, pinned by loom/test/price-probe-structure.test.js.

   WHY THIS IS NOT api.js. api.js is the one request module and its ONE error rule is "the
   parsed body wins, HTTP 200 included" -- a transport failure is flattened into
   {error: "network error: …"}, which is a BODY. Pricing is the one place that distinction
   cannot be collapsed: an HTTP-200 {error} body is a real ANSWER from the pricing endpoint
   (the badge paints it, the Loom's confirm reads it), whereas a dropped socket, an abort or a
   25s stall is the could-not-verify road -- red badge, "may spend", fail-closed-but-live. Read
   through api.js the two are the same {error} object and the spend gate loses the difference.
   So this file keeps its own fetch and is named as one of api.js's three exemptions; it took
   gen/usePriceProbe.js's place on that list when the hook stopped fetching for itself.

   THE CONTRACT -- two roads, never both:

     requestPrice(payload, { timeoutMs = PRICE_FETCH_TIMEOUT_MS, signal }) -> Promise

       {response}       any parsed body, whatever the HTTP status was. An HTTP-200 {error}
                        body is a RESPONSE: this module does not judge it, the badge and the
                        Loom's confirm decide what it means.
       {failed: true}   nothing was learned. A transport failure, an abort, the timeout, or a
                        body that will not parse -- the caller was promised an answer about
                        the price and did not get one.

   It never throws, never retries (one POST per call, exactly as the spend-safety rules
   require of anything on a paid road), and never decides anything about the money. Callers
   branch once, on `failed`.

   TIMEOUT AND ABORT. A hung request fires neither road, and a verdict that never settles is a
   spend control stuck shut with no message (review 2026-08-16) -- so the timeout is
   unconditional, whoever owns the controller. With no `signal` this module makes its own
   AbortController; with one, it still makes its own for the timeout and links the caller's to
   it, so the probe's stop()/teardown abort still lands. */
import { PRICE_FETCH_TIMEOUT_MS } from "./priceProbeCore.js";

export async function requestPrice(payload, { timeoutMs = PRICE_FETCH_TIMEOUT_MS, signal } = {}) {
  const ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  const timer = (ctrl && timeoutMs > 0) ? setTimeout(() => ctrl.abort(), timeoutMs) : 0;
  let unlink = null;
  if (ctrl && signal) {
    // The caller's abort (a tab left, a component unmounted) has to reach the request this
    // module actually issued.
    if (signal.aborted) ctrl.abort();
    else {
      const onAbort = () => ctrl.abort();
      signal.addEventListener("abort", onAbort);
      unlink = () => signal.removeEventListener("abort", onAbort);
    }
  }
  try {
    const r = await fetch("/api/price", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl ? ctrl.signal : undefined,
    });
    // The parse is INSIDE the try on purpose: an HTML error page or a cut stream is not an
    // answer about the price, so it takes the could-not-verify road rather than arriving as a
    // response nobody can read. Same road the probe's own .catch() gave it before.
    return { response: await r.json() };
  } catch {
    return { failed: true };
  } finally {
    if (timer) clearTimeout(timer);
    if (unlink) unlink();
  }
}
