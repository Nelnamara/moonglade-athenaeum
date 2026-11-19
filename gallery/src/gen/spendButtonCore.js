/* spendButtonCore -- what a button that spends says, as pure functions (3.21.x look pick, round 2,
   topic 1 option B: "two lines in the button" -- the action, then the price or "Free · uses 1
   card"). Look board: moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html #price.

   The button reads the SAME verdict its cost badge reads -- <CostBadge>'s onCost detail, one
   push per state -- so the price on the button can never be a second opinion about the money.
   Nothing here prices, sends or decides a spend: the spend gates (gen/priceProbeCore.js's
   payload identity, expect_free, the "may have started" hold) stay exactly where they were. The
   one rule this adds is the board's "the button stays dim until it knows": a button is live only
   on a settled price (paid) or a settled free answer (a card, or Unlimited Mode). Not priced
   yet, checking, a failed check and a "nothing to price" note all leave it dim, with the reason
   on its second line.

   THE ONE-TIME ASK (same board, "The same in every choice"): an amount the account sets in the
   Control Panel's PixAI account tile ("Ask before spending more than [ 10,000 ] credits", off
   until set). A paid send above it turns the button into "Confirm — spend ≈ N" on the first
   press and sends on the second -- the Panel's own Delete / Undo two-step. A free card never
   asks. Stored on the account (/api/account/prefs) under SPEND_ASK_KEY.

   No React, no DOM, no network -- pinned by loom/test/spend-button-core.test.js. */
import { classify, isShort } from "./costBadgeCore.js";

export const SPEND_ASK_KEY = "spend.ask_above";
// The board's own words for the failed check, and the dim line while a check is out.
export const UNPRICED_LINE = "Couldn't check the price";
export const CHECKING_LINE = "checking the price…";
export const DEFAULT_IDLE = "nothing to price yet";
// How long an armed "Confirm — spend" waits for its second press before it stands down.
export const ASK_ARM_MS = 6000;
// The largest amount the setting takes (a typo of extra zeros is refused, not stored).
export const ASK_MAX = 100000000;

function fmt(n) { return Number(n).toLocaleString(); }
function count(v) {
  const n = Number(v);
  return (v != null && v !== "" && isFinite(n) && n >= 1) ? Math.floor(n) : 1;
}

/* The stored threshold, read back: a whole number of credits from 1 to ASK_MAX, else 0 (off).
   A value of the wrong type is OFF, never repaired into an amount the owner did not set. */
export function askThreshold(v) {
  if (typeof v !== "number" || !isFinite(v)) return 0;
  if (v < 1 || v > ASK_MAX || Math.floor(v) !== v) return 0;
  return v;
}

/* What the Control Panel's field holds -> what is stored. "" (or 0) turns the ask off (null:
   the key is removed); a whole positive number up to ASK_MAX is stored; anything else is
   refused with a plain sentence. Separators people type ("10,000", "10 000") are allowed. */
export function parseAskInput(text) {
  const t = String(text == null ? "" : text).replace(/[\s,._']/g, "");
  if (!t || /^0+$/.test(t)) return { value: null, error: "" };
  if (!/^\d+$/.test(t)) return { value: null, error: "Type a whole number of credits, or leave it empty to turn the ask off." };
  const n = Number(t);
  if (n > ASK_MAX) return { value: null, error: "That is more than " + fmt(ASK_MAX) + " credits." };
  return { value: n, error: "" };
}

/* The button's view of one quote.
     quote  <CostBadge>'s onCost detail ({state, cost, free, unlimited, raw, text}) or null
            (never pushed yet = not priced).
     idle   the host's short "not priced yet" words ("pick a model first"). A note the SERVER
            sent (a builder refusal, `raw.note`) wins over it: that is the real reason.
     sends  how many times the priced request goes out (a Matrix's cells): the total is said.
   -> {state, priced, free, total, sub, title}
     priced  true only on a settled paid or free answer -- the button is live on nothing else;
     free    a card or Unlimited Mode covers it (the emerald ring);
     total   credits the press spends (0 when free);
     sub     the button's second line;
     title   extra words for the button's tooltip (the server's own error), or "". */
export function spendView(quote, { idle = "", sends = 1 } = {}) {
  const q = quote && typeof quote === "object" ? quote : null;
  const state = q && q.state ? q.state : "idle";
  const raw = (q && q.raw && typeof q.raw === "object") ? q.raw : {};
  const n = count(sends);
  if (state === "free") {
    // Unlimited Mode: "Free" with the lane's ∞ after it (SCOPE_2026-09-26_unlimited-mode C5 -- every
    // form reads "Free ∞"); `lane` tells the button to draw the ∞ in the lane's fixed green.
    if (q.unlimited) return { state, priced: true, free: true, lane: true, total: 0, sub: "Free", title: "" };
    // A multi-ticket job (a long video) uses that many of the held cards; one ticket per job
    // otherwise. A Matrix sends the request once per cell, so each cell takes its own card.
    const k = count(raw.cards_needed) * n;
    return { state, priced: true, free: true, total: 0,
      sub: "Free · uses " + fmt(k) + (k === 1 ? " card" : " cards"), title: "" };
  }
  if (state === "paid") {
    const c = (q.cost == null || q.cost === "") ? NaN : Number(q.cost);
    if (!isFinite(c)) return { state: "error", priced: false, free: false, total: 0, sub: UNPRICED_LINE, title: "" };
    const total = c * n;
    return { state, priced: true, free: false, total,
      sub: total === 0 ? "0 credits" : "≈ " + fmt(total) + " credits", title: "" };
  }
  if (state === "checking") return { state, priced: false, free: false, total: 0, sub: CHECKING_LINE, title: "" };
  if (state === "error") {
    const why = raw.error ? String(raw.error) : "";
    return { state, priced: false, free: false, total: 0, sub: UNPRICED_LINE, title: why };
  }
  const note = raw.note ? String(raw.note) : "";
  const hint = (q && typeof q.text === "string") ? q.text : "";
  return { state: "idle", priced: false, free: false, total: 0,
    sub: note || String(idle || "").trim() || hint || DEFAULT_IDLE, title: "" };
}

/* Does this press ask first? Only a priced, PAID send whose total is above the account's
   amount. A free answer never asks; an unpriced button cannot be pressed at all. */
export function needsAsk(view, threshold) {
  const t = askThreshold(threshold);
  return !!(view && view.priced && !view.free && t > 0 && Number(view.total) > t);
}

/* The armed button's words (the board's "Confirm — spend ≈ 27,500"). */
export function askText(view) {
  return "Confirm — spend ≈ " + fmt(view && view.total ? view.total : 0);
}

/* What one press does, given whether the button is already armed:
     "send"  go -- the press is the spend (or the confirming second press);
     "arm"   turn into the confirm and wait for a second press;
     "none"  the button is dim: nothing. */
export function pressAction(view, threshold, armed) {
  if (!view || !view.priced) return "none";
  if (armed) return "send";
  return needsAsk(view, threshold) ? "arm" : "send";
}

/* A parsed /api/price answer (null = the check itself failed) in the shape spendView reads --
   for a surface that holds the answer itself instead of a <CostBadge> (the Loom's phone
   screens, its Fixer). The verdict is costBadgeCore.classify's, the badge's own rule, so the
   button and a badge can never read the same answer two ways. */
export function quoteFromPrice(pr) {
  const v = classify(pr);
  const d = v.raw || {};
  return {
    state: v.state,
    cost: (d.cost != null && isFinite(Number(d.cost))) ? Number(d.cost) : null,
    free: v.state === "free",
    unlimited: v.state === "free" && d.unlimited === true,
    card_short: v.state === "paid" && isShort(d),
    raw: v.raw,
    text: v.note || "",
  };
}

/* The Loom's price entries ({loading, pr} per shot, `pr` null when the check failed) as a
   quote: no entry, or one that was never asked (no `pr` yet), or one the host marks as having
   nothing to price (`noInput`, a Fix's `offPicture`) is not priced -- the host's idle words
   say why; a request out is "checking"; anything else is the answer. */
export function quoteFromEntry(e) {
  if (!e || typeof e !== "object") return null;
  if (e.loading) return { state: "checking" };
  if (e.noInput || e.offPicture || !Object.prototype.hasOwnProperty.call(e, "pr")) return null;
  return quoteFromPrice(e.pr);
}
