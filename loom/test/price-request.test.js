import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { requestPrice } from "../../gallery/src/gen/priceRequest.js";

/* THE ONE PRICE TRANSPORT'S OWN BEHAVIOUR (2026-08-23).

   gen/priceRequest.js exists for exactly one distinction, and it is a spend-safety one:

     {response}      the pricing endpoint ANSWERED. Whatever the body says -- a cost, a free
                     card, or an HTTP-200 {error} refusal -- something was learned, and the
                     badge / the Loom's confirm decide what it means.
     {failed: true}  nothing was learned. A dropped socket, an abort, the timeout, or a body
                     that will not parse. This is the could-not-verify road: the red badge,
                     "may spend", and a confirm that still ASKS.

   api.js's one error rule ("the parsed body wins, HTTP 200 included") deliberately collapses
   those two into the same {error} object, which is why this module keeps its own fetch and
   holds one of api.js's three named exemptions. These tests drive the module directly with a
   stubbed global fetch -- the only place in the suite where that road can be walked without a
   browser -- because the whole point is what it does when the transport fails.

   The "never a second fetch" assertion on every case is not tidiness: this is a paid road, and
   the repo's standing rule is that a spend-adjacent request is never re-issued (a re-POST after
   a lost response is how you pay for a second generation). One call, one POST, either way. */

const realFetch = globalThis.fetch;
let calls;

/** Install a stub and record every call. `impl(url, init)` returns/throws whatever the case wants. */
function stubFetch(impl) {
  calls = [];
  globalThis.fetch = (url, init) => {
    calls.push({ url, init });
    return impl(url, init);
  };
}
const jsonResponse = (body) => ({ json: async () => body });
/** A request that never answers on its own -- it settles only when its signal aborts. */
const hangUntilAbort = () => (url, init) => new Promise((_res, rej) => {
  const sig = init && init.signal;
  if (!sig) return;                       // no signal: genuinely hangs (test must not use this)
  if (sig.aborted) { rej(new Error("aborted")); return; }
  sig.addEventListener("abort", () => rej(new Error("aborted")));
});

beforeEach(() => { calls = []; });
afterEach(() => { globalThis.fetch = realFetch; });

describe("requestPrice: a parsed body is a RESPONSE, whatever it says", () => {
  test("an ordinary price body comes back as {response}, with no `failed`", async () => {
    stubFetch(async () => jsonResponse({ cost: 1200, free: false }));
    const out = await requestPrice({ mode: "image" });
    assert.deepEqual(out.response, { cost: 1200, free: false });
    assert.ok(!out.failed, "a real answer must never carry `failed`");
    assert.equal(calls.length, 1, "one call, one POST");
  });

  test("an HTTP-200 {error} body is a RESPONSE, not a failure", async () => {
    // The pricing endpoint refuses with HTTP 200 {error} (the same convention every spend
    // route here uses). That is the server ANSWERING -- the badge paints it, the Loom's
    // confirm reads it. Reporting it as `failed` would send a real refusal down the
    // could-not-verify road and change what the user is told about their money.
    stubFetch(async () => jsonResponse({ error: "read-only mode" }));
    const out = await requestPrice({ mode: "video" });
    assert.deepEqual(out.response, { error: "read-only mode" });
    assert.ok(!out.failed, "an {error} BODY is an answer -- only the transport can fail");
    assert.equal(calls.length, 1);
  });

  test("it POSTs /api/price once, as JSON, with the payload it was handed", async () => {
    stubFetch(async () => jsonResponse({ cost: 0, free: true }));
    await requestPrice({ mode: "fix", source: "m1", boxes: [{ x: 1 }] });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/price");
    assert.equal(calls[0].init.method, "POST");
    assert.equal(calls[0].init.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(calls[0].init.body), { mode: "fix", source: "m1", boxes: [{ x: 1 }] });
  });
});

describe("requestPrice: the could-not-verify road", () => {
  test("a rejected fetch (offline, dropped socket) resolves {failed} -- it never throws", async () => {
    stubFetch(async () => { throw new TypeError("Failed to fetch"); });
    const out = await requestPrice({ mode: "image" });
    assert.equal(out.failed, true);
    assert.equal(out.response, undefined, "nothing was learned about the price");
    assert.equal(calls.length, 1, "a transport failure is never retried -- this is a paid road");
  });

  test("a body that will not parse takes the same road", async () => {
    // An HTML error page or a cut stream is not an answer about the price. Before the transport
    // was shared this landed in the probe's own .catch(); it must keep landing there.
    stubFetch(async () => ({ json: async () => { throw new SyntaxError("Unexpected token <"); } }));
    const out = await requestPrice({ mode: "image" });
    assert.equal(out.failed, true);
    assert.equal(calls.length, 1);
  });

  test("the caller's abort resolves {failed}, and the abort reaches the request", async () => {
    // The probe's stop()/teardown owns its own controller (leaving a tab must kill the request
    // in flight, issue #27). requestPrice has to link that signal to the request it issued.
    stubFetch(hangUntilAbort());
    const c = new AbortController();
    const p = requestPrice({ mode: "image" }, { signal: c.signal });
    c.abort();
    const out = await p;
    assert.equal(out.failed, true);
    assert.equal(calls.length, 1, "an abort is not a reason to try again");
    assert.ok(calls[0].init.signal, "the fetch must carry a signal, or the abort cannot land");
  });

  test("a signal already aborted before the call still resolves {failed} without hanging", async () => {
    stubFetch(hangUntilAbort());
    const c = new AbortController();
    c.abort();
    const out = await requestPrice({ mode: "image" }, { signal: c.signal });
    assert.equal(out.failed, true);
  });

  test("a hung request times out and resolves {failed} -- the verdict always settles", async () => {
    // The bug this bounds (review 2026-08-16): an unbounded price fetch fired neither road, so
    // the verdict never settled, the spend control stayed shut and the badge sat on a muted
    // "Checking cost…" with no error and no way out. Fail-silent-closed is worse than the red
    // could-not-verify badge, which at least says what happened and leaves the button live.
    stubFetch(hangUntilAbort());
    const out = await requestPrice({ mode: "image" }, { timeoutMs: 20 });
    assert.equal(out.failed, true);
    assert.equal(calls.length, 1, "a timeout is not a retry trigger");
  });

  test("the timeout applies even when the CALLER supplied the signal", async () => {
    // The probe passes its own signal (it needs stop() to abort). If the timeout only existed
    // on the no-signal path, the hang bug would come straight back for the one caller that
    // most needs the bound.
    stubFetch(hangUntilAbort());
    const c = new AbortController();          // never aborted by us
    const out = await requestPrice({ mode: "image" }, { timeoutMs: 20, signal: c.signal });
    assert.equal(out.failed, true);
    assert.equal(calls.length, 1);
  });
});
