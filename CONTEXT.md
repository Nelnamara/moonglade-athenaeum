# CONTEXT.md — the project's domain vocabulary

The words this codebase uses for its own ideas, defined once. Glossary only: no status, no
plans, no arguments. **Why** a thing was decided the way it was lives in
`../moonglade-internal/DECISIONS.md`; how it works lives in the code and in
`../moonglade-internal/architecture.md`.

---

**Price probe** — the one module every cost line rides to find out what a generation would
cost: `gallery/src/gen/priceProbeCore.js` (pure) plus `gallery/src/gen/usePriceProbe.js`
(the React hook that owns the debounce, the `POST /api/price`, the sequence guard and the
abort). A host supplies a payload builder and a `CostBadge` ref; it supplies everything else.

**Price identity (`priceKey`)** — the fingerprint of a payload, computed over every field
except the ones that never price (prompt, negative, seed; Edit skips `instruction` instead).
Two payloads with the same price identity are the same job as far as cost is concerned.

**Verdict** — what the probe currently knows, as `{settled, pricedKey, pendingTimer}`.
*Scheduled*: a re-price is queued but has not fired, so whatever is on the badge is
known-stale. *Fired*: the timer went off and the answer is not back. *Settled*: a real
answer — a price, a free card, a failed check, or an idle hint — was reached for
`pricedKey`. A submit control is live only when a settled verdict's key matches the payload
the click would send.

**Fail-closed-but-live** — the rule for a price check that could not be verified. The badge
turns red and says generating may spend, the verdict settles anyway, and the button stays
pressable: the app refuses to *imply* free, and equally refuses to strand the user behind a
dead control with no message.

**Short-circuit** — a refresh that returns without doing anything because the payload's price
identity already equals the settled one. What makes typing in a prompt free: no badge blank,
no disabled button, no `/api/price` call.

**Forced re-price** — a refresh that ignores the short-circuit. Used where the payload is
byte-identical but the verdict is stale anyway: right after a submit debited credits or
tickets, and when a badge remounts idle on returning to a tab.

**Idle hint** — the badge's "nothing to price yet" label ("Pick a source image to see the
cost."). It is a verdict, not a gap: it settles, so the host's own pre-submit refusal
message stays reachable instead of the control going quietly dead.

**Free card (kaisuuken)** — PixAI's prepaid generation ticket. A matching card is attached
automatically at submit and the generation costs 0 credits. A video card is a *book* of
tickets and a clip spends one per 5 seconds; holding fewer tickets than a job needs attaches
no card at all and charges the full price ("short").

**CostBadge host contract** — `gallery/src/components/CostBadge.jsx` never fetches. The host
pushes state in through its imperative handle — `setPrice(response)`, `setChecking()`,
`clear(hint)` — and the badge owns every state's wording and colour, so a displayed "free"
or "0 credits" can only ever mean a settled zero-cost result.
