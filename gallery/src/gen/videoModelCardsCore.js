/* videoModelCardsCore -- the Video tab's model cards, as pure functions (3.21.x look pick round
   2, topic 4 option C: "a card for each model"; moonglade-internal/design/board/
   LOOK_BOARD_2026-11-19_round2.html #video). One card per engine the picker offers: its name
   and "in use" / "Use this", its tags (videoDrawerCore.modelCaps -- the chips the engine
   slab already drew), the shot modes it takes (and the fields it does not), the price at every
   length for THIS picture, and what the free card does.

   The board's rule for the prices: "Prices come from the same price check the button uses, for
   the picture you have chosen, and fill in as they come back. With no picture chosen the
   prices read 'pick a picture'." So each card's price at each length is a real /api/price
   answer for the drawer's own payload with only the engine and the length changed -- built by
   videoDrawerCore's own gating and payload functions, never a per-second guess. Asking is the
   drawer's (VideoDrawer.jsx, through gen/priceRequest.js, the one transport); this file says
   what to ask and how to word the answers. Nothing here sends or decides a spend: "Use this"
   only picks the engine, exactly as the chip grid it replaces did.

   No React, no DOM, no network -- pinned by loom/test/video-model-cards-core.test.js. */
import {
  MODEL_CARD, MODEL_VMODES, SHOT_LABEL, applyModelGating, buildPayload, durationAllowed,
  flfMissingStart, hasAnyRef, modelCaps, modelTakes, pickerModels,
} from "./videoDrawerCore.js";
import { priceKey } from "./priceProbeCore.js";

// The lengths a card prices (the board's "5s · 10s · 15s"); an engine shows the ones it takes.
export const CARD_LENGTHS = [5, 10, 15];

function fmt(n) { return Number(n).toLocaleString(); }

export function cardLengths(model) {
  return CARD_LENGTHS.filter((d) => durationAllowed(model, d));
}

/* "First Frame · First & Last · Multi-Reference · no negative, no camera" */
export function cardModes(model) {
  const modes = (MODEL_VMODES[model] || ["i2v", "flf", "r2v"]).map((m) => SHOT_LABEL[m] || m);
  const no = [];
  if (!modelTakes(model, "negative")) no.push("no negative");
  if (!modelTakes(model, "camera")) no.push("no camera");
  return modes.join(" · ") + (no.length ? " · " + no.join(", ") : "");
}

/* The drawer's own state, on another engine at another length: the SAME gating the engine pick
   runs (applyModelGating -- the mode an engine lacks falls to one it has, the length clamps and
   snaps), on a copy, so the drawer is never touched. */
function onEngine(s, model, duration) {
  const c = { ...s, model, duration,
    slots: (s.slots || []).slice(), imgSlots: (s.imgSlots || []).slice(),
    vidSlots: (s.vidSlots || []).slice(), modeNote: "" };
  applyModelGating(c, false);
  return c;
}

/* What to price for one card at one length -> {payload} or {why}:
     why "pick"   no picture chosen (the board's "pick a picture") -- or a First & Last with an
                  End Frame and no Start Frame, which the drawer itself refuses to price;
     why "mode"   this engine has no <the drawer's shot mode>: what it would price is a
                  different shot, so it is not priced at all. */
export function cardPayload(s, model, duration, promptText = "") {
  const c = onEngine(s, model, duration);
  if (c.mode !== s.mode) return { why: "mode" };
  const p = buildPayload(c, promptText);
  if (!hasAnyRef(p) || flfMissingStart(c)) return { why: "pick" };
  return { payload: p };
}

/* Every card the picker offers, with the requests its prices need. `price(key)` looks up an
   answer the drawer already has: undefined = not asked / not back yet, null = the check
   failed, else the parsed /api/price body. `s` is the drawer's state, `prompt` its text. */
export function modelCards(s, { prompt = "", price = () => undefined, now } = {}) {
  return pickerModels(now).map((m) => {
    const lengths = cardLengths(m.value);
    const cells = lengths.map((d) => {
      const r = cardPayload(s, m.value, d, prompt);
      if (!r.payload) return { d, why: r.why, key: "" };
      const key = priceKey(r.payload);
      return { d, key, payload: r.payload, answer: price(key) };
    });
    return {
      value: m.value, label: m.label, inUse: m.value === s.model,
      caps: modelCaps(m.value), modes: cardModes(m.value),
      cells,
      line: priceLine(cells, SHOT_LABEL[s.mode] || s.mode),
      cover: coverLine(m.value, cells, s.duration),
    };
  });
}

/* The card's price line: "5s 27,500 · 10s 55,000 · 15s 82,500", each length as its answer
   arrives ("5s …" while it is out). One answer per cell: the length's price (a card that covers
   it is said on the card line, as the board does), "free" only for a covered answer with no
   number, and "?" for a failed or empty check. */
export function priceLine(cells, modeLabel) {
  if (!cells.length) return "";
  if (cells.every((c) => c.why === "pick")) return "pick a picture";
  if (cells.every((c) => c.why === "mode")) return "no " + modeLabel + " on this model";
  return cells.map((c) => c.d + "s " + cellText(c)).join(" · ");
}

export function cellText(c) {
  if (c.why === "pick") return "pick a picture";
  if (c.why === "mode") return "—";
  const a = c.answer;
  if (a === undefined) return "…";
  if (!a || a.error) return "?";
  // The price of the length, as the board writes it ("5s 27,500"), whether or not a card covers
  // it -- the card line below says what the card does. "free" only when no number came back.
  if (a.cost != null && isFinite(Number(a.cost))) return fmt(a.cost);
  if (a.free) return "free";
  return "?";
}

/* What the free card does on this engine, at the drawer's own length when the card prices it
   (else the first length that has an answer):
     a settled free answer       -> "Your free card covers this"           (emerald)
     a card matched, not enough  -> "Your cards don't cover this length"
     an engine cards never cover -> "Never card-covered"
     a settled paid answer       -> "No free card covers this"
     nothing back yet            -> "Card coverage checked when priced"
   -> {text, ok} (ok = the emerald line). */
export function coverLine(model, cells, duration) {
  if (MODEL_CARD[model] === false) return { text: "Never card-covered", ok: false };
  const pick = cells.find((c) => c.d === Number(duration) && c.answer)
    || cells.find((c) => c.answer);
  const a = pick ? pick.answer : null;
  if (!a || a.error) return { text: "Card coverage checked when priced", ok: false };
  if (a.free) return { text: "Your free card covers this", ok: true };
  if (a.card_short) return { text: "Your cards don't cover this length", ok: false };
  return { text: "No free card covers this", ok: false };
}

/* The requests still to make, in the order the cards are read: the engine in use first, then
   the list top to bottom; within a card the drawer's own length first. Each key once. */
export function pendingPrices(cards, duration, have = () => false) {
  const seen = new Set();
  const out = [];
  const ordered = cards.slice().sort((a, b) => (b.inUse ? 1 : 0) - (a.inUse ? 1 : 0));
  for (const card of ordered) {
    const cells = card.cells.slice().sort((a, b) => (b.d === Number(duration) ? 1 : 0) - (a.d === Number(duration) ? 1 : 0));
    for (const c of cells) {
      if (!c.key || seen.has(c.key) || have(c.key)) continue;
      seen.add(c.key);
      out.push({ key: c.key, payload: c.payload });
    }
  }
  return out;
}
