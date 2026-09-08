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
                                          retry ONCE -- but ONLY when this page's own nonce
                                          is missing or older than the 60s window (see
                                          RETRY_AFTER_MS below).
     429 {"error": "slow down"}            30 beacon calls in a rolling minute. Give up.

   WHY THE RETRY IS CONDITIONAL (2026-09-07, refining the same day's ruling). A double-fired
   click is TWO posts carrying ONE nonce: the first spends it, the second is refused 403 as
   consumed. That 403 looks exactly like an idle tab's, and retrying it fetched a fresh nonce
   and sent the gesture again -- which the server's 150ms debounce only swallows if the whole
   refresh+retry round trip lands inside 150ms. Over LAN or a phone's wifi it often does not,
   and then one physical click counts twice: the debounce and this retry were cancelling each
   other out. An idle tab's nonce is minutes old and a twin's is milliseconds old, which is
   the difference the age check reads. A young nonce that was refused has been spent by its
   own twin, and there is nothing to recover: give up silently, exactly like a 429.

   These feats ANNOUNCE; they never gate capability, and every one of them is still earnable
   on the next gesture. A user who just poked a narrator avatar does not need to be told
   about a nonce, so a give-up here is silent by design -- the same fail-soft contract the
   callers already had against the 2026-08-26 LOCALHOST 403. */
import { apiGet, apiPost } from "../api.js";

// Read MG_BOOT lazily, not at module scope: the boot script runs before app.js, but a test
// harness (and any future SSR-less mount) has no window at import time.
let current = null;

// _ACH_NONCE_TTL_S on the server. A nonce this old is certainly spent-or-expired, so a 403
// on it is the idle tab the retry exists for; anything younger was killed by its own twin.
const RETRY_AFTER_MS = 60000;
// When the nonce we are holding was minted. The boot nonce was minted with the page, so it
// dates from module load -- NOT from the first take(), which can be many minutes later on
// the very tab (idle, one late poke) whose age this has to get right.
const BOOT_AT = now();
let adoptedAt = 0;

function now() {
  return (typeof Date !== "undefined" && Date.now) ? Date.now() : 0;
}

function seed() {
  if (current === null) {
    current = (typeof window !== "undefined" && window.MG_BOOT
               && window.MG_BOOT.ach_nonce) || "";
    adoptedAt = BOOT_AT;
  }
  return current;
}

/* How long we have been holding the nonce take() would send. Infinity when there is none --
   nothing to lose by asking for one. */
function heldForMs() {
  return seed() ? (now() - adoptedAt) : Infinity;
}

/* The nonce this page would send right now (the boot mint until an event rotates it). */
export function take() {
  return seed();
}

/* Adopt the server's next_nonce. A falsy value is ignored -- a refusal must never blank
   the page's working nonce, or one 429 would cost the rest of the session. */
export function set(next) {
  if (next) {
    current = next;
    adoptedAt = now();
  }
}

/* Top up from /api/ach-nonce when this page's own has gone stale. Returns the new nonce,
   or "" when the ask itself was refused (a 429, or a logged-out tab). */
export async function refresh() {
  const d = await apiGet("/api/ach-nonce");
  if (d && d.nonce) {
    current = d.nonce;
    adoptedAt = now();
    return current;
  }
  return "";
}

/* Post one feat event. Answers the server's body exactly as api.js hands it over -- the
   narrator caller reads .pokes/.snapped off it, and every caller branches on .error once. */
export async function sendAchEvent(event) {
  // Read the age BEFORE the await: by the time the 403 lands, the twin that beat us may
  // already have adopted its own next_nonce and reset the clock this decision reads.
  const stale = heldForMs() >= RETRY_AFTER_MS;
  let res = await apiPost("/api/ach-event", { event, nonce: take() });
  if (res && res.error && res.http_status === 403 && stale) {
    const fresh = await refresh();
    if (!fresh) return res;
    res = await apiPost("/api/ach-event", { event, nonce: fresh });
  }
  set(res && res.next_nonce);
  return res;
}
