/* THE FEAT BEACON'S NONCE (2026-09-07).

   /api/ach-event went back to LOGIN on the owner's ruling -- "I feel like triggered should
   be obtainable easily on a phone just like desktop. For sure build the nonce." -- and the
   nonce is what makes LOGIN honest. The server mints one into every render
   (window.MG_BOOT.ach_nonce), accepts it for exactly ONE event inside 60 seconds, refuses
   it from any other session, and hands back a `next_nonce` with each acceptance. So the
   page has to CARRY a value between events, which is the whole reason this module exists
   rather than each caller posting on its own: Triggered needs five pokes in a row, and a
   caller that forgot to adopt next_nonce would earn exactly one of them.

   Every /api/ach-event caller under gallery/src goes through sendAchEvent(). That is a
   structural rule, pinned by loom/test/ach-nonce-callers.test.js, not a convention.

   THE TWO REFUSALS, and why neither is a toast:
     403 {"error": "stale page — reload"}  the nonce was missing, spent, expired, or another
                                          session's. Ask /api/ach-nonce for a fresh one and
                                          retry ONCE -- an idle tab is the ordinary cause.
     429 {"error": "slow down"}            30 beacon calls in a rolling minute. Give up.
   These feats ANNOUNCE; they never gate capability, and every one of them is still earnable
   on the next gesture. A user who just poked a narrator avatar does not need to be told
   about a nonce, so a give-up here is silent by design -- the same fail-soft contract the
   callers already had against the 2026-08-26 LOCALHOST 403. */
import { apiGet, apiPost } from "../api.js";

// Read MG_BOOT lazily, not at module scope: the boot script runs before app.js, but a test
// harness (and any future SSR-less mount) has no window at import time.
let current = null;

function seed() {
  if (current === null) {
    current = (typeof window !== "undefined" && window.MG_BOOT
               && window.MG_BOOT.ach_nonce) || "";
  }
  return current;
}

/* The nonce this page would send right now (the boot mint until an event rotates it). */
export function take() {
  return seed();
}

/* Adopt the server's next_nonce. A falsy value is ignored -- a refusal must never blank
   the page's working nonce, or one 429 would cost the rest of the session. */
export function set(next) {
  if (next) current = next;
}

/* Top up from /api/ach-nonce when this page's own has gone stale. Returns the new nonce,
   or "" when the ask itself was refused (a 429, or a logged-out tab). */
export async function refresh() {
  const d = await apiGet("/api/ach-nonce");
  if (d && d.nonce) {
    current = d.nonce;
    return current;
  }
  return "";
}

/* Post one feat event. Answers the server's body exactly as api.js hands it over -- the
   narrator caller reads .pokes/.snapped off it, and every caller branches on .error once. */
export async function sendAchEvent(event) {
  let res = await apiPost("/api/ach-event", { event, nonce: take() });
  if (res && res.error && res.http_status === 403) {
    const fresh = await refresh();
    if (!fresh) return res;
    res = await apiPost("/api/ach-event", { event, nonce: fresh });
  }
  set(res && res.next_nonce);
  return res;
}
