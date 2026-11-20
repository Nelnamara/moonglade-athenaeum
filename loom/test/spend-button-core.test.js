import { test, describe } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { loadComponent, renderElement, query, one } from "../test-support/render.mjs";
import {
  UNPRICED_LINE, CHECKING_LINE,
  spendView, quoteFromPrice, quoteFromEntry,
} from "../../gallery/src/gen/spendButtonCore.js";

/* THE PRICE ON THE BUTTON THAT SPENDS (3.21.x look pick round 2, topic 1 option B; the board is
   moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html #price). Two lines in the
   button -- the action, then the price or "Free · uses 1 card" -- dim until priced. The words are spendButtonCore's (driven here as
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
    return query(renderElement(React.createElement(SpendButton, props)));
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
});
