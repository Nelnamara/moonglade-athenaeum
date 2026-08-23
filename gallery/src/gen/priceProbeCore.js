/* priceProbeCore -- the price probe's PURE half: the identity of a priced payload, the verdict
   state machine that decides whether a spend control may be live, and the two timing constants.
   No React, no DOM, no fetch -- everything here is a plain function the node suite drives
   directly (loom/test/price-probe-core.test.js), which is the point: every rule the six cost
   lines used to carry as prose in one host's comments is a named, testable function here.

   ONE PROBE, SIX HOSTS (2026-08-22). Image gen, mobile edit, desktop Edit, the Fixer, Upscale
   and the video drawer each hand-rolled the same debounce -> POST /api/price -> sequence guard
   -> push into <CostBadge> loop, and only the video drawer carried the payload-identity spend
   gate written after issue #15. The gate is not an optimisation, it is the thing that stops a
   settled quote from carrying a DIFFERENT submit, so it belongs to every spend surface, not to
   whichever one was reviewed last. gen/usePriceProbe.js is the React half; this file is what it
   is made of. */

/* ---- price identity: the settled quote must be FOR the payload Go would submit ------------
   State alone cannot gate a spend: the badge can hold a settled FREE for a 5s payload while
   the form already says 15s (a 250ms debounce + one RTT of stale FREE), or hold a price for a
   payload whose quality/camera has since changed with NO re-price pending at all. So the probe
   records the priceKey of the payload it actually priced, and Go compares it against the
   priceKey of the payload it is about to submit -- identity, not timing.

   priceKey drops ONLY the fields that never price. Everything else rides the priced request
   (the whole i2vPro/referenceVideo/chat block is a _PRICE_NESTED field of moonglade_backup's
   price_task, and modelId a _PRICE_SCALARS one), so a field that does not really move the
   price (channel, camera) still lives in the key: the cost of over-including is a re-price the
   change handler already schedules; the cost of under-including is a spend against the wrong
   quote. Prompt text is excluded because it is edited without a repaint (the video drawer's
   imperative contenteditable) and it never prices -- see loom-core.js's PRICE_FIELDS for the
   same call. `seed` joins it for image generation, where it is a free-text field on the same
   footing; video and edit payloads carry no seed, so it is inert there. A host whose text
   field is named something else (Edit's `instruction`) passes its own skip list -- see
   editCore.js's EDIT_PRICE_KEY_SKIP. */
export const PRICE_KEY_SKIP = ["prompt", "negative", "seed"];

export function priceKey(payload, skipKeys = PRICE_KEY_SKIP) {
  if (!payload || typeof payload !== "object") return "";
  const skip = skipKeys || [];
  const keys = Object.keys(payload).filter((k) => skip.indexOf(k) === -1).sort();
  return JSON.stringify(keys.map((k) => [k, payload[k]]));
}

/* ---- the verdict: {settled, pricedKey, pendingTimer} --------------------------------------
   settled      = the badge shows the probe's verdict for pricedKey (a price, a card, a red
                  could-not-verify, or an idle hint -- all four are verdicts);
   pricedKey    = priceKey() of the payload that verdict was reached on;
   pendingTimer = a re-price is scheduled but has not fired, so whatever is on the badge is
                  already known-stale by definition.
   The four constructors below are the ONLY shapes the probe ever writes. */

// Never priced. Fail-closed: a spend control stays off until a real verdict lands, which is
// what stops an un-priced payload from riding a control that happened to render enabled.
export function initialVerdict() { return { settled: false, pricedKey: null, pendingTimer: false }; }

// A re-price has been scheduled. Dropping the identity HERE is what disables Go the instant a
// priced field changes -- before this the badge kept a settled FREE for the debounce plus one
// whole RTT after the user picked a different duration (the issue #15 shape, review 2026-08-16).
export function scheduled() { return { settled: false, pricedKey: null, pendingTimer: true }; }

// The timer has FIRED and the answer is not back. Written BEFORE anything in the fire step can
// bail, or an early return (no badge mounted) leaves pendingTimer true forever and the gate
// never opens again.
export function fired() { return { settled: false, pricedKey: null, pendingTimer: false }; }

// A verdict was reached for `key`. Every exit of the fire step settles -- including a FAILED
// check (the badge's red "couldn't verify -- may spend" IS this payload's verdict) and the idle
// hints ("nothing to price" keeps Go live so the host's own refusal message stays reachable).
export function settledFor(key) { return { settled: true, pricedKey: key, pendingTimer: false }; }

/* The Go gate. True only when a settled verdict exists AND nothing is pending AND that verdict
   was priced off THIS payload. Hosts AND it with whatever gate they already have. */
export function canSubmit(verdict, payload, skipKeys = PRICE_KEY_SKIP) {
  return !!(verdict && verdict.settled && !verdict.pendingTimer && verdict.pricedKey != null
    && verdict.pricedKey === priceKey(payload, skipKeys));
}

/* SHORT-CIRCUIT when nothing that prices has changed: if the payload's price identity equals
   the SETTLED key, the quote on the badge is still exactly right, so leave it (and Go) alone.
   This is what makes a prompt/negative keystroke harmless -- those fields are outside priceKey
   ("never prices"), yet their handlers refresh the probe, and before this every typing pause
   blanked the badge, disabled the submit control for 250ms + RTT, discarded any in-flight quote
   and re-POSTed /api/price (three PixAI calls) for a byte-identical payload (review 2026-08-16).
   Fixing it at the MECHANISM covers every non-pricing caller, present and future, instead of
   auditing handlers one by one. Un-settled/pending states still fall through, so a genuine
   re-price is never suppressed.

   `force` bypasses it for the ONE case where the payload is identical but the verdict is stale
   anyway: right after a submit debited the tickets. Identity-by-payload cannot see a balance
   change, so the post-submit re-price must not be swallowed here. (The same bypass re-primes a
   badge that remounted idle -- a tab that became visible again shows nothing, whatever the
   verdict says.) */
export function shouldShortCircuit(verdict, payload, force, skipKeys = PRICE_KEY_SKIP) {
  if (force) return false;
  return !!(verdict && verdict.settled && verdict.pricedKey != null && !verdict.pendingTimer
    && verdict.pricedKey === priceKey(payload, skipKeys));
}

/* ---- timing ------------------------------------------------------------------------------- */
// The pause after the last change before the probe actually asks. One number for every cost
// line -- they all shipped 250 independently, and a second copy is a second thing to drift.
export const PRICE_DEBOUNCE_MS = 250;
// How long the probe waits on /api/price before aborting into the "couldn't verify" verdict.
// Go is gated on the fetch settling, so an UNBOUNDED fetch that hangs (browser<->server stall)
// would leave Go disabled forever with no message. The server's own upstream PixAI calls are
// bounded at 30s/60s, so 25s here only ever fires on a transport stall, not a slow price.
export const PRICE_FETCH_TIMEOUT_MS = 25000;
