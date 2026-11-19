import { test, describe } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { loadComponent, renderElement, query, one } from "../test-support/render.mjs";
import {
  SPEND_ASK_KEY, UNPRICED_LINE, CHECKING_LINE, ASK_MAX,
  askThreshold, parseAskInput, spendView, needsAsk, askText, pressAction,
  quoteFromPrice, quoteFromEntry,
} from "../../gallery/src/gen/spendButtonCore.js";
import { prefKeyProblem } from "../../gallery/src/hooks/accountPrefsStore.js";

/* THE PRICE ON THE BUTTON THAT SPENDS (3.21.x look pick round 2, topic 1 option B; the board is
   moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html #price). Two lines in the
   button -- the action, then the price or "Free · uses 1 card" -- dim until priced, and the
   one-time ask above the account's own amount. The words are spendButtonCore's (driven here as
   plain functions); what the button DRAWS is the real <SpendButton> rendered statically. */

const fmt = (n) => Number(n).toLocaleString();

describe("spendView: the button's second line, and whether it may be pressed", () => {
  test("a settled price is the button's price, and the button is live", () => {
    const v = spendView({ state: "paid", cost: 2400, raw: { cost: 2400 } });
    assert.deepEqual([v.priced, v.free, v.total, v.sub], [true, false, 2400, "≈ " + fmt(2400) + " credits"]);
  });
  test("a free card is \"Free · uses 1 card\" (the board's words), or the job's ticket count", () => {
    assert.equal(spendView({ state: "free", raw: {} }).sub, "Free · uses 1 card");
    assert.equal(spendView({ state: "free", raw: { cards_needed: 3 } }).sub, "Free · uses 3 cards");
    assert.equal(spendView({ state: "free", raw: {} }, { sends: 2 }).sub, "Free · uses 2 cards", "a Matrix cell takes its own card");
    const v = spendView({ state: "free", raw: {} });
    assert.deepEqual([v.priced, v.free, v.total], [true, true, 0]);
  });
  test("Unlimited Mode is free by the entitlement, never by a card", () => {
    const v = spendView({ state: "free", unlimited: true, raw: { unlimited: true } });
    assert.deepEqual([v.sub, v.lane, v.free], ["Free", true, true], "the lane's \"Free ∞\": the button draws the ∞");
  });
  test("a Matrix says the total it sends", () => {
    const v = spendView({ state: "paid", cost: 3400, raw: {} }, { sends: 3 });
    assert.deepEqual([v.total, v.sub], [10200, "≈ " + fmt(10200) + " credits"]);
  });
  test("not priced yet, checking, a failed check and a server note are all DIM, each with its reason", () => {
    const idle = spendView(null, { idle: "pick a model first" });
    assert.deepEqual([idle.priced, idle.sub], [false, "pick a model first"]);
    assert.deepEqual([spendView({ state: "checking" }).priced, spendView({ state: "checking" }).sub], [false, CHECKING_LINE]);
    const err = spendView({ state: "error", raw: { error: "model not found" } });
    assert.deepEqual([err.priced, err.sub, err.title], [false, UNPRICED_LINE, "model not found"]);
    assert.equal(UNPRICED_LINE, "Couldn't check the price", "the board's own words");
    const note = spendView({ state: "idle", raw: { note: "Both upscale methods at once" } }, { idle: "pick a model first" });
    assert.deepEqual([note.priced, note.sub], [false, "Both upscale methods at once"], "the server's reason wins over the host's hint");
    const hint = spendView({ state: "idle", text: "Pick a source image to see the cost.", raw: null });
    assert.equal(hint.sub, "Pick a source image to see the cost.", "with no host words, the badge's own hint");
  });
  test("a paid answer with no number is never a price", () => {
    const v = spendView({ state: "paid", cost: null, raw: {} });
    assert.deepEqual([v.priced, v.sub], [false, UNPRICED_LINE]);
  });
  test("no unpriced line ever reads as a number", () => {
    for (const q of [null, { state: "idle" }, { state: "checking" }, { state: "error", raw: {} }]) {
      assert.doesNotMatch(spendView(q).sub, /\d/);
    }
  });
});

describe("the one-time ask", () => {
  test("it lives on the account, under a key the store accepts", () => {
    assert.equal(SPEND_ASK_KEY, "spend.ask_above");
    assert.equal(prefKeyProblem(SPEND_ASK_KEY), "");
  });
  test("the stored amount reads back as a whole number of credits, else OFF", () => {
    assert.equal(askThreshold(10000), 10000);
    for (const bad of [0, -5, 1.5, "10000", null, undefined, NaN, Infinity, ASK_MAX + 1, {}]) assert.equal(askThreshold(bad), 0, String(bad));
  });
  test("the Panel's field: empty is off, separators are fine, anything else says why", () => {
    assert.deepEqual(parseAskInput(""), { value: null, error: "" });
    assert.deepEqual(parseAskInput("0"), { value: null, error: "" });
    assert.deepEqual(parseAskInput("10,000"), { value: 10000, error: "" });
    assert.deepEqual(parseAskInput(" 27 500 "), { value: 27500, error: "" });
    assert.match(parseAskInput("ten").error, /whole number/);
    assert.match(parseAskInput("-5").error, /whole number/);
    assert.match(parseAskInput(String(ASK_MAX * 10)).error, /more than/);
  });
  test("only a priced PAID send above the amount asks; a free card never does", () => {
    const paid = spendView({ state: "paid", cost: 27500, raw: {} });
    assert.equal(needsAsk(paid, 10000), true);
    assert.equal(needsAsk(paid, 27500), false, "at the amount is not above it");
    assert.equal(needsAsk(paid, 0), false, "off until set");
    assert.equal(needsAsk(spendView({ state: "free", raw: { cost: 27500 } }), 10000), false);
    assert.equal(needsAsk(spendView({ state: "checking" }), 10000), false);
    assert.equal(askText(paid), "Confirm — spend ≈ " + fmt(27500), "the board's armed words");
  });
  test("a press: arm first above the amount, send on the second; never anything while dim", () => {
    const paid = spendView({ state: "paid", cost: 27500, raw: {} });
    assert.equal(pressAction(paid, 10000, false), "arm");
    assert.equal(pressAction(paid, 10000, true), "send");
    assert.equal(pressAction(paid, 0, false), "send");
    assert.equal(pressAction(spendView({ state: "free", raw: {} }), 10, false), "send");
    assert.equal(pressAction(spendView(null), 0, false), "none");
    assert.equal(pressAction(spendView({ state: "error", raw: {} }), 0, true), "none", "an armed button that went dim sends nothing");
  });
});

describe("a surface that holds the answer itself reads it the badge's way", () => {
  test("quoteFromPrice is the badge's classify: server decides free / short / failed", () => {
    assert.equal(quoteFromPrice(null).state, "error", "a failed check");
    assert.equal(quoteFromPrice({ free: true, cost: 900 }).state, "free");
    const short = quoteFromPrice({ free: false, cost: 900, card_short: true });
    assert.deepEqual([short.state, short.cost, short.card_short], ["paid", 900, true]);
    assert.equal(quoteFromPrice({ cost: null, note: "nothing to price" }).state, "idle");
    assert.equal(quoteFromPrice({ error: "refused" }).state, "error");
  });
  test("quoteFromEntry: the Loom's {loading, pr} entries", () => {
    assert.equal(quoteFromEntry(undefined), null);
    assert.equal(quoteFromEntry({}), null, "never asked is not priced");
    assert.deepEqual(quoteFromEntry({ loading: true }), { state: "checking" });
    assert.equal(quoteFromEntry({ noInput: true, pr: null }), null);
    assert.equal(quoteFromEntry({ offPicture: true, pr: null }), null);
    assert.equal(quoteFromEntry({ loading: false, pr: null }).state, "error");
    assert.equal(spendView(quoteFromEntry({ loading: false, pr: { cost: 400, free: false } })).sub, "≈ 400 credits");
  });
});

describe("<SpendButton> draws two lines in the host's own button, dim until priced", () => {
  let SpendButton;
  const draw = async (props) => {
    if (!SpendButton) SpendButton = await loadComponent("gallery/src/components/SpendButton.jsx");
    return query(renderElement(React.createElement(SpendButton, { ask: false, ...props })));
  };
  test("priced: the action, then the price, on the host's class; live", async () => {
    const $ = await draw({ className: "mgdock-gen", label: "✦ Generate", quote: { state: "paid", cost: 2400, raw: {} } });
    const b = one($.byTag("button"));
    assert.match(b.attr("class"), /\bmgdock-gen\b/);
    assert.match(b.attr("class"), /\bmgspend\b/);
    assert.equal(b.attr("disabled") == null, true);
    assert.equal(b.attr("data-priced"), "1");
    assert.equal(one(b.byClass("mgspend-a")).text, "✦ Generate");
    assert.equal(one(b.byClass("mgspend-s")).text, "≈ " + fmt(2400) + " credits");
  });
  test("free: \"Free · uses 1 card\" and the emerald ring's class", async () => {
    const b = one((await draw({ className: "cm-generate", label: "✦ Generate", quote: { state: "free", raw: {} } })).byTag("button"));
    assert.equal(one(b.byClass("mgspend-s")).text, "Free · uses 1 card");
    assert.match(b.attr("class"), /\bfree\b/);
  });
  test("not priced: dim with the host's dim class and its reason -- even with every host gate open", async () => {
    const b = one((await draw({ className: "mgdock-gen", label: "✦ Generate", idle: "pick a model first", quote: null })).byTag("button"));
    assert.equal(b.attr("disabled") != null, true);
    assert.match(b.attr("class"), /\boff\b/);
    assert.equal(one(b.byClass("mgspend-s")).text, "pick a model first");
    const failed = one((await draw({ className: "mgd-go", offClass: "", label: "Generate video", quote: { state: "error", raw: {} } })).byTag("button"));
    assert.equal(failed.attr("disabled") != null, true);
    assert.equal(one(failed.byClass("mgspend-s")).text, "Couldn't check the price");
  });
  test("the host's own gate still dims a priced button, and busy shows the host's busy words", async () => {
    const off = one((await draw({ className: "mgdock-gen", label: "✦ Edit", disabled: true, quote: { state: "paid", cost: 5, raw: {} } })).byTag("button"));
    assert.equal(off.attr("disabled") != null, true);
    const busy = one((await draw({ className: "mgu-go", label: "Upscale", busy: true, busyLabel: "Submitting…", quote: { state: "paid", cost: 5, raw: {} } })).byTag("button"));
    assert.equal(busy.attr("disabled") != null, true);
    assert.equal(one(busy.byClass("mgspend-a")).text, "Submitting…");
  });
  test("a button that may ask renders too (the account store is read, nothing is sent)", async () => {
    const $ = await draw({ ask: true, className: "mgdock-gen", label: "✦ Generate", quote: { state: "paid", cost: 1, raw: {} } });
    assert.equal(one($.byClass("mgspend-s")).text, "≈ 1 credits");
  });
});
