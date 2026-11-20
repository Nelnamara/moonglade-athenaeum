import "./fixtures/pin-video-clock.js";
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  CARD_LENGTHS, cardLengths, cardModes, cardPayload, modelCards, priceLine, cellText, coverLine, pendingPrices,
} from "../../gallery/src/gen/videoModelCardsCore.js";
import { buildPayload, pickerModels, modelCaps, DEFAULT_MODEL } from "../../gallery/src/gen/videoDrawerCore.js";
import { priceKey } from "../../gallery/src/gen/priceProbeCore.js";

/* CHOOSING A VIDEO MODEL: A CARD PER MODEL (3.21.x look pick round 2, topic 4 option C; the board
   is moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html #video). Each card: the
   engine's tags, the shot modes it takes, the price at every length FOR THIS PICTURE (real price
   answers, filling in as they come back -- "pick a picture" with none chosen) and what the free
   card does. These pin the pure half; the drawer asks, one request at a time. */

const fmt = (n) => Number(n).toLocaleString();
// The drawer's state, as VideoDrawer keeps it: a First Frame shot on the default engine.
const drawer = (o = {}) => ({
  mode: "i2v", slots: [{ media_id: "111", thumb: "/t/111.jpg" }], imgSlots: [null], vidSlots: [null], audSlot: null,
  model: DEFAULT_MODEL, duration: 5, camera: "unset", quality: "professional", channel: "normal",
  audioGen: false, audioLanguage: "english", videoHelper: false, negative: "", modeNote: "", ratio: "adaptive",
  ...o,
});

describe("what a card says about its engine", () => {
  test("the lengths it prices are the board's 5 / 10 / 15 s, as the engine takes them", () => {
    assert.deepEqual(CARD_LENGTHS, [5, 10, 15]);
    assert.deepEqual(cardLengths("v4.0.1"), [5, 10, 15]);
    assert.deepEqual(cardLengths("v2.7"), [5, 10], "a 10 s engine has no 15 s price");
  });
  test("the shot modes it takes, and the fields it does not (the board's Tsubaki line)", () => {
    assert.equal(cardModes("v4.0.1"), "First Frame · First & Last · Multi-Reference");
    assert.equal(cardModes("tbkv1.0"), "First Frame · First & Last · Multi-Reference · no negative, no camera");
    assert.equal(cardModes("v2.7"), "First Frame");
  });
  test("one card per engine the picker offers, its tags the engine slab's own chips, the one in use marked", () => {
    const cards = modelCards(drawer());
    assert.deepEqual(cards.map((c) => c.value), pickerModels().map((m) => m.value));
    const cur = cards.filter((c) => c.inUse);
    assert.deepEqual(cur.map((c) => c.value), [DEFAULT_MODEL]);
    for (const c of cards) assert.deepEqual(c.caps, modelCaps(c.value));
  });
});

describe("what a card prices: this drawer's payload with only the engine and the length changed", () => {
  test("the engine in use at the drawer's own length prices exactly what Go would send", () => {
    const s = drawer({ duration: 10 });
    const r = cardPayload(s, s.model, 10, "a walk");
    assert.deepEqual(r.payload, buildPayload(s, "a walk"));
  });
  test("another engine is gated as a pick would gate it -- and never priced as a different shot", () => {
    const r2v = drawer({ mode: "r2v", slots: [null], imgSlots: [{ media_id: "222" }] });
    assert.equal(cardPayload(r2v, "v2.7", 5).why, "mode", "V2.7 has no Multi-Reference: not priced at all");
    const ok = cardPayload(r2v, "tbkv1.0", 10);
    assert.deepEqual([ok.payload.video_model, ok.payload.duration, ok.payload.mode], ["tbkv1.0", 10, "R2V"]);
    assert.equal(ok.payload.negative, "", "an engine without a negative is priced without one, as it sends");
  });
  test("no picture: nothing to price, and the line says \"pick a picture\"", () => {
    const s = drawer({ slots: [null] });
    assert.equal(cardPayload(s, s.model, 5).why, "pick");
    for (const c of modelCards(s)) {
      if (c.line.startsWith("no ")) continue;   // an engine without this shot mode says so instead
      assert.equal(c.line, "pick a picture", c.value);
    }
  });
  test("the drawer is never touched: the gating runs on a copy", () => {
    const s = drawer({ mode: "r2v", slots: [null], imgSlots: [{ media_id: "222" }], duration: 15 });
    const before = JSON.stringify(s);
    modelCards(s);
    assert.equal(JSON.stringify(s), before);
  });
});

describe("the price line and the card line", () => {
  test("each length as its answer arrives: a number, free, still out, or ?", () => {
    const answers = new Map();
    const s = drawer();
    const first = modelCards(s, { price: (k) => answers.get(k) }).find((c) => c.inUse);
    assert.equal(first.line, "5s … · 10s … · 15s …");
    answers.set(first.cells[0].key, { cost: 27500, free: false });
    answers.set(first.cells[1].key, { cost: 55000, free: false, card_short: true });
    answers.set(first.cells[2].key, null);
    const card = modelCards(s, { price: (k) => (answers.has(k) ? answers.get(k) : undefined) }).find((c) => c.inUse);
    assert.equal(card.line, "5s " + fmt(27500) + " · 10s " + fmt(55000) + " · 15s ?");
    assert.equal(cellText({ d: 5, answer: { free: true, cost: 27500 } }), fmt(27500), "the price, covered or not (the card line says the card)");
    assert.equal(cellText({ d: 5, answer: { free: true } }), "free");
    assert.equal(cellText({ d: 5, answer: { error: "x" } }), "?");
  });
  test("an engine with none of the drawer's shot mode says so", () => {
    assert.equal(priceLine([{ d: 5, why: "mode" }, { d: 10, why: "mode" }], "Multi-Reference"), "no Multi-Reference on this model");
  });
  test("the card line: covered (emerald), short, never, paid, or not known yet", () => {
    const at = (answer, d = 5) => [{ d, answer }];
    assert.deepEqual(coverLine("v4.0.1", at({ free: true }), 5), { text: "Your free card covers this", ok: true });
    assert.deepEqual(coverLine("v4.0.1", at({ free: false, cost: 1, card_short: true }), 5), { text: "Your cards don't cover this length", ok: false });
    assert.deepEqual(coverLine("v4.0.1", at({ free: false, cost: 1 }), 5), { text: "No free card covers this", ok: false });
    assert.deepEqual(coverLine("v2.7", at({ free: true }), 5), { text: "Never card-covered", ok: false }, "a no-card engine says so whatever comes back");
    assert.deepEqual(coverLine("tbkv1.0", [{ d: 5 }], 5), { text: "Card coverage checked when priced", ok: false });
    assert.deepEqual(coverLine("v4.0.1", [{ d: 5, answer: { free: false, cost: 1 } }, { d: 10, answer: { free: true } }], 10).text,
      "Your free card covers this", "read at the drawer's own length first");
  });
});

describe("what the drawer asks next", () => {
  test("the engine in use first, its own length first, every payload once, nothing already answered", () => {
    const s = drawer({ duration: 10 });
    const cards = modelCards(s);
    const all = pendingPrices(cards, 10);
    const inUse = cards.find((c) => c.inUse);
    assert.equal(all[0].key, inUse.cells.find((c) => c.d === 10).key);
    assert.equal(new Set(all.map((p) => p.key)).size, all.length, "no payload twice");
    for (const p of all) assert.equal(p.key, priceKey(p.payload), "keyed the probe's way: a prompt keystroke asks nothing");
    const have = new Set(all.slice(0, 3).map((p) => p.key));
    assert.deepEqual(pendingPrices(cards, 10, (k) => have.has(k)).map((p) => p.key), all.slice(3).map((p) => p.key));
    assert.deepEqual(pendingPrices(modelCards(drawer({ slots: [null] })), 5), [], "no picture: nothing is asked");
  });
});
