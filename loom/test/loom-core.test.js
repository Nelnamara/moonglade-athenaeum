import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  CONNECT, CONTINUITY_PHRASE, actLetter,
  maxTagNum, nextTag, frameLinked, connectMeta, continuityLinked,
  flat, shotText, castMissingImages, shotPayload, durOf, reelStats, effectivePrompt,
  priceFingerprint, tallyPrices, tallyPricesDetailed, priceIsShort, shortSpendLine,
  formatCostEstimate, costTooltip,
} from "../src/loom-core.js";

/* ---------- fixtures ---------- */

function makeCard(overrides = {}) {
  return {
    id: overrides.id || "c1",
    title: "untitled",
    mode: "R2V",
    duration: 8,
    connect: "new",
    prompt: "",
    cast: [],
    refs: [],
    camera: "",
    lighting: "",
    audioCue: "",
    transIn: "",
    transOut: "",
    notes: "",
    openFrame: { thumbId: "", source: "", desc: "", tag: "" },
    closeFrame: { thumbId: "", source: "", desc: "", tag: "" },
    ...overrides,
  };
}

function makeProject(acts, assets = []) {
  return { name: "Test", target: 60, assets, acts };
}

/* ---------- maxTagNum / nextTag ---------- */

describe("maxTagNum / nextTag", () => {
  test("empty list starts at prefix 1", () => {
    assert.equal(maxTagNum([], "@image"), 0);
    assert.equal(nextTag([], "@image"), "@image1");
  });

  test("finds the highest existing number regardless of order", () => {
    const items = [{ tag: "@image3" }, { tag: "@image1" }, { tag: "@image7" }];
    assert.equal(maxTagNum(items, "@image"), 7);
    assert.equal(nextTag(items, "@image"), "@image8");
  });

  test("ignores tags for a different prefix", () => {
    const items = [{ tag: "@video5" }, { tag: "@image2" }];
    assert.equal(maxTagNum(items, "@image"), 2);
    assert.equal(nextTag(items, "@image"), "@image3");
  });

  test("tag renumbering after a mid-list deletion does not collide with a surviving tag", () => {
    // Start with @image1, @image2, @image3; delete the middle one (@image2).
    let items = [{ tag: "@image1" }, { tag: "@image2" }, { tag: "@image3" }];
    items = items.filter((x) => x.tag !== "@image2");   // simulate deletion
    assert.deepEqual(items.map((x) => x.tag), ["@image1", "@image3"]);
    // The next tag must be beyond the surviving max (@image3 -> @image4), NOT
    // a reuse of the freed @image2 slot -- reusing a gap risks colliding with
    // anything else in the document that still refers to the deleted tag by
    // name (shot text, refs, exports already written with "@image2" in them).
    const next = nextTag(items, "@image");
    assert.equal(next, "@image4");
    assert.ok(!items.some((x) => x.tag === next), "new tag must not collide with a surviving tag");
  });
});

/* ---------- frameLinked ---------- */

describe("frameLinked", () => {
  test("null/undefined frames are never linked", () => {
    assert.equal(frameLinked(null, { mediaId: "1" }), false);
    assert.equal(frameLinked({ mediaId: "1" }, undefined), false);
  });

  test("matches on mediaId alone", () => {
    const a = { mediaId: "med-1", thumbId: "" };
    const b = { mediaId: "med-1", thumbId: "" };
    assert.equal(frameLinked(a, b), true);
  });

  test("matches on thumbId alone", () => {
    const a = { mediaId: "", thumbId: "thumb-9" };
    const b = { mediaId: "", thumbId: "thumb-9" };
    assert.equal(frameLinked(a, b), true);
  });

  test("does not match when identity fields differ", () => {
    const a = { mediaId: "med-1", thumbId: "thumb-1" };
    const b = { mediaId: "med-2", thumbId: "thumb-2" };
    assert.equal(frameLinked(a, b), false);
  });

  test("does not match when both sides are empty strings", () => {
    const a = { mediaId: "", thumbId: "" };
    const b = { mediaId: "", thumbId: "" };
    assert.equal(frameLinked(a, b), false);
  });
});

/* ---------- connectMeta ---------- */

describe("connectMeta", () => {
  test("known keys resolve to their real metadata", () => {
    assert.equal(connectMeta("flf"), CONNECT.flf);
    assert.equal(connectMeta("extend").label, "Extend prev");
  });

  test("missing/undefined connect value falls back to 'new' without throwing", () => {
    assert.doesNotThrow(() => connectMeta(undefined));
    assert.equal(connectMeta(undefined), CONNECT.new);
  });

  test("a legacy/stale connect value that no longer exists in CONNECT falls back safely", () => {
    assert.doesNotThrow(() => connectMeta("some-removed-legacy-mode"));
    assert.equal(connectMeta("some-removed-legacy-mode"), CONNECT.new);
  });

  test("empty string falls back to 'new'", () => {
    assert.equal(connectMeta(""), CONNECT.new);
  });
});

/* ---------- continuityLinked ---------- */
// The board's continuity indicator: is a given shot's OPENING frame already frameLinked
// to the immediately-preceding shot's CLOSING frame? `entries` is always the project's full,
// flattened, cross-act list (flat(project)) -- continuity is a timeline concept, not an
// act-scoped one, same convention the frame-handoff button's own "previous shot" lookup
// already follows (entries.findIndex + idx-1, see master-storyboard.jsx's prevEntry/
// weavePrevEntry) -- so a test below deliberately puts the two shots in DIFFERENT acts to
// prove the act boundary is irrelevant.

describe("continuityLinked", () => {
  test("the first shot in the project has no predecessor, so it is never linked", () => {
    const entries = [
      { c: makeCard({ id: "c1", closeFrame: { mediaId: "med-1", thumbId: "", desc: "", tag: "" } }) },
    ];
    assert.equal(continuityLinked(entries, "c1"), false);
  });

  test("an id not present in entries has no predecessor either", () => {
    const entries = [{ c: makeCard({ id: "c1" }) }];
    assert.equal(continuityLinked(entries, "does-not-exist"), false);
  });

  test("an empty/absent entries list is safe and never linked", () => {
    assert.equal(continuityLinked([], "c1"), false);
    assert.equal(continuityLinked(undefined, "c1"), false);
  });

  test("true when this shot's openFrame shares mediaId with the previous shot's closeFrame", () => {
    const entries = [
      { c: makeCard({ id: "c1", closeFrame: { mediaId: "med-9", thumbId: "", desc: "", tag: "" } }) },
      { c: makeCard({ id: "c2", openFrame: { mediaId: "med-9", thumbId: "", desc: "", tag: "" } }) },
    ];
    assert.equal(continuityLinked(entries, "c2"), true);
  });

  test("true when this shot's openFrame shares thumbId with the previous shot's closeFrame (locally uploaded frames)", () => {
    const entries = [
      { c: makeCard({ id: "c1", closeFrame: { mediaId: "", thumbId: "thumb-4", desc: "", tag: "" } }) },
      { c: makeCard({ id: "c2", openFrame: { mediaId: "", thumbId: "thumb-4", desc: "", tag: "" } }) },
    ];
    assert.equal(continuityLinked(entries, "c2"), true);
  });

  test("false when the previous shot's closeFrame and this shot's openFrame are different frames", () => {
    const entries = [
      { c: makeCard({ id: "c1", closeFrame: { mediaId: "med-1", thumbId: "", desc: "", tag: "" } }) },
      { c: makeCard({ id: "c2", openFrame: { mediaId: "med-2", thumbId: "", desc: "", tag: "" } }) },
    ];
    assert.equal(continuityLinked(entries, "c2"), false);
  });

  test("false when neither shot's relevant frame has any identity set yet (both blank)", () => {
    const entries = [
      { c: makeCard({ id: "c1" }) },
      { c: makeCard({ id: "c2" }) },
    ];
    assert.equal(continuityLinked(entries, "c2"), false);
  });

  test("act boundaries are irrelevant -- continuity is checked against the previous entry in the FLATTENED list regardless of which act either shot is in", () => {
    const entries = [
      { c: makeCard({ id: "c1", closeFrame: { mediaId: "med-7", thumbId: "", desc: "", tag: "" } }), ai: 0 },
      { c: makeCard({ id: "c2", openFrame: { mediaId: "med-7", thumbId: "", desc: "", tag: "" } }), ai: 1 },
    ];
    assert.equal(continuityLinked(entries, "c2"), true);
  });
});

/* ---------- actLetter ---------- */

describe("actLetter", () => {
  test("first 26 acts are A-Z", () => {
    assert.equal(actLetter(0), "A");
    assert.equal(actLetter(25), "Z");
  });

  test("beyond 26 falls back to A<index>", () => {
    assert.equal(actLetter(26), "A26");
  });
});

/* ---------- flat ---------- */

describe("flat", () => {
  test("assigns act-letter/shot-number codes across multiple acts", () => {
    const project = makeProject([
      { id: "a1", name: "Act One", cards: [makeCard({ id: "c1" }), makeCard({ id: "c2" })] },
      { id: "a2", name: "Act Two", cards: [makeCard({ id: "c3" })] },
    ]);
    const entries = flat(project);
    assert.deepEqual(entries.map((e) => e.code), ["A·01", "A·02", "B·01"]);
    assert.deepEqual(entries.map((e) => e.c.id), ["c1", "c2", "c3"]);
  });

  test("empty acts produce an empty flat list", () => {
    assert.deepEqual(flat(makeProject([])), []);
  });
});

/* ---------- shotText ---------- */

describe("shotText", () => {
  test("assembles a basic shot with mode/duration/connect header", () => {
    const project = makeProject([{ id: "a1", name: "Act", cards: [makeCard({ title: "Opener", mode: "I2V", duration: 5, prompt: "a hero walks in" })] }]);
    const entries = flat(project);
    const text = shotText(entries[0], project);
    assert.match(text, /\[A·01 — "Opener"\] {2}\(I2V, ~5s, New scene\)/);
    assert.match(text, /a hero walks in/);
  });

  test("'extend' connect references the previous shot's code and appends the continuity phrase", () => {
    const project = makeProject([{ id: "a1", name: "Act", cards: [
      makeCard({ id: "c1", title: "First" }),
      makeCard({ id: "c2", title: "Second", connect: "extend" }),
    ] }]);
    const entries = flat(project);
    const text = shotText(entries[1], project);
    assert.match(text, /Continue seamlessly from the previous clip A·01/);
    assert.ok(text.includes(CONTINUITY_PHRASE));
  });

  test("FLF MODE includes open/close frame descriptions", () => {
    // Gated on mode, not connect: shotImageRefs() reserves the frame slots by
    // `c.mode === "FLF"`, so describing them by `c.connect` let the two disagree -- an
    // FLF-mode shot had both frames attached and sent with nothing saying what they were.
    const card = makeCard({
      mode: "FLF",
      connect: "flf",
      openFrame: { thumbId: "", source: "", desc: "sunrise over the ridge", tag: "@image8" },
      closeFrame: { thumbId: "", source: "", desc: "sun fully up", tag: "@image9" },
    });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    const text = shotText(flat(project)[0], project);
    assert.match(text, /Opening frame @image8: sunrise over the ridge/);
    assert.match(text, /Closing frame @image9: sun fully up/);
  });

  test("cast references list with lock-appearance phrasing", () => {
    // kind+mediaId so the shot actually HAS a picture for Nel -- a cast member with no image
    // is deliberately left out of the prompt now (see the test below).
    const asset = { id: "as1", name: "Nel", tag: "@image1", lock: true, kind: "image", mediaId: "m1" };
    const card = makeCard({ cast: ["as1"] });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }], [asset]);
    const text = shotText(flat(project)[0], project);
    assert.match(text, /Nel — maintain exact appearance from @image1/);
  });

  test("a cast member with no picture on this shot is left OUT of the prompt", () => {
    // Citing them fell back to their project-GLOBAL tag -- "Greg — reference @image4" when no
    // @image4 is attached, and the drawer numbers purely by position so it calls something
    // else that. Exactly the two-numbering-systems corruption positionTag() exists to stop.
    // The board card surfaces it instead (castMissingImages), where it can be fixed.
    const withPic = { id: "as1", name: "Nel", tag: "@image1", kind: "image", mediaId: "m1" };
    const noPic = { id: "as4", name: "Greg", tag: "@image4", kind: "image" };
    const card = makeCard({ cast: ["as1", "as4"] });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }], [withPic, noPic]);
    const entry = flat(project)[0];
    const text = shotText(entry, project);
    assert.match(text, /Nel — reference @image1/, "a cast member WITH a picture is still cited");
    assert.doesNotMatch(text, /Greg/, "a cast member with no picture must not be cited");
    assert.doesNotMatch(text, /@image4/, "and its global tag must not reach the prompt");
    assert.deepStrictEqual(castMissingImages(entry, project), ["Greg"],
      "but the board card must be able to say so");
  });

  test("project 'look' appends a film-wide style line to every shot", () => {
    const project = makeProject([{ id: "a1", name: "Act", cards: [makeCard({ prompt: "a hero walks in" })] }]);
    project.look = "muted teal grade, 35mm grain, anamorphic flares";
    const text = shotText(flat(project)[0], project);
    assert.match(text, /Look \(consistent across the film\): muted teal grade, 35mm grain, anamorphic flares/);
  });

  test("no 'look' line when the project look is empty", () => {
    const project = makeProject([{ id: "a1", name: "Act", cards: [makeCard({})] }]);
    assert.ok(!shotText(flat(project)[0], project).includes("Look (consistent"));
  });

  test("a promptOverride returns VERBATIM, ignoring camera/lighting/cast/notes entirely", () => {
    const asset = { id: "as1", name: "Nel", tag: "@image1", lock: true };
    const card = makeCard({
      cast: ["as1"], camera: "slow push in", lighting: "golden hour", notes: "important beat",
      promptOverride: true, promptOverrideText: "exactly this and nothing else",
    });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }], [asset]);
    const text = shotText(flat(project)[0], project);
    assert.equal(text, "exactly this and nothing else");
  });

  test("promptOverride survives a second shotText() call unchanged (no compounding)", () => {
    const card = makeCard({ camera: "dolly out", promptOverride: true, promptOverrideText: "static override text" });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    const entry = flat(project)[0];
    const first = shotText(entry, project);
    const second = shotText(entry, project);
    assert.equal(first, "static override text");
    assert.equal(second, first);   // repeated calls must not append camera/lighting on each cycle
  });
});

describe("effectivePrompt", () => {
  test("returns promptOverrideText when promptOverride is set", () => {
    const card = makeCard({ prompt: "raw prompt", promptOverride: true, promptOverrideText: "override wins" });
    assert.equal(effectivePrompt(card), "override wins");
  });
  test("falls back to raw prompt when no override is active", () => {
    const card = makeCard({ prompt: "raw prompt", promptOverride: false });
    assert.equal(effectivePrompt(card), "raw prompt");
  });
  test("never returns null/undefined even with missing fields", () => {
    assert.equal(effectivePrompt({}), "");
    assert.equal(effectivePrompt({ promptOverride: true }), "");
  });
});

describe("priceFingerprint / tallyPrices / formatCostEstimate", () => {
  test("fingerprint is stable for identical priceable fields", () => {
    const a = { mode: "R2V", images: ["1"], video_refs: [], duration: 5, quality: "basic", generate_audio: false, audio_language: "english", prompt: "A" };
    const b = { ...a, prompt: "totally different text" };   // prompt is NOT a priceable field
    assert.equal(priceFingerprint(a), priceFingerprint(b));
  });
  test("fingerprint changes when a priceable field changes", () => {
    const a = { mode: "R2V", images: ["1"], video_refs: [], duration: 5, quality: "basic", generate_audio: false, audio_language: "english" };
    const b = { ...a, duration: 10 };
    assert.notEqual(priceFingerprint(a), priceFingerprint(b));
  });
  test("tallyPrices buckets free/paid/unknown and sums credits, failing closed on null", () => {
    const t = tallyPrices([{ free: true }, { free: false, cost: 500 }, { free: false, cost: 250 }, null]);
    assert.deepEqual(t, { free: 1, paid: 2, credits: 750, unknown: 1 });
  });
  test("formatCostEstimate never shows a bare 0/free for an unsettled or unpriced result", () => {
    assert.equal(formatCostEstimate({ pending: 3 }), "…");
    assert.equal(formatCostEstimate({ unknown: 2, pending: 0 }), "2 unpriced");
    assert.notEqual(formatCostEstimate({ unknown: 2 }), "0 cr");
  });
  test("formatCostEstimate distinguishes a settled zero-cost paid shot from 'nothing settled'", () => {
    assert.equal(formatCostEstimate({ paid: 1, credits: 0 }), "0 cr");
    assert.equal(formatCostEstimate({}), "…");
  });
});

// issue #15: multi-ticket free cards. A 15s i2vPro shot costs 3 tickets; /api/price's `free`
// is the server's card_covers() (held >= needed) for ONE job priced alone, and it also
// reports card_short / cards_held / cards_needed / card_name / card_template. OWNER RULING:
// short still spends (like the site) -- the client's whole duty is honesty: say nothing
// attaches and the FULL price is charged, and count the batch's tickets against the held
// pool BEFORE the confirm so a "will spend" shot never surprises anyone.
describe("multi-ticket cards: priceIsShort / shortSpendLine / tallyPricesDetailed", () => {
  const short15 = { free: false, cost: 1200, card_short: true, cards_held: 2, cards_needed: 3,
    card_name: "Video Pro", card_template: "tpl-video" };
  test("priceIsShort: only a matched-but-short result; never a covered or unmatched one, never null", () => {
    assert.equal(priceIsShort(short15), true);
    assert.equal(priceIsShort({ free: true, cards_held: 5, cards_needed: 3 }), false, "covered is never short");
    assert.equal(priceIsShort({ free: false, cost: 900 }), false, "no card matched at all -- the plain 'no free card' case");
    assert.equal(priceIsShort(null), false);
    // fallback for a response carrying counts but predating the flag -- still gated on free:false
    assert.equal(priceIsShort({ free: false, cost: 900, cards_held: 1, cards_needed: 3 }), true);
    assert.equal(priceIsShort({ free: true, cards_held: 1, cards_needed: 3 }), false, "free stays authoritative");
  });
  test("shortSpendLine says exactly what happens: no card is used, the FULL price is charged", () => {
    const line = shortSpendLine(short15, "this 15s shot");
    assert.equal(line,
      "You hold 2 of the 3 free Video Pro cards this 15s shot needs — not enough, so no card is used. It will spend the full ~1,200 credits.");
    // never partial application, never "covers 2 of 3"
    assert.doesNotMatch(line, /covers 2/);
    assert.doesNotMatch(line, /rest|remaining/);
    // unknown price still says FULL price, and an unnamed card still reads as a sentence
    assert.equal(shortSpendLine({ free: false, card_short: true, cards_held: 0, cards_needed: 2 }, "this"),
      "You hold 0 of the 2 free cards this needs — not enough, so no card is used. It will spend the full credit price.");
  });
  test("tally: 5 held, three 15s shots x 3 needed -> 1 free, 2 paid at full price (pool spent in submission order)", () => {
    const pr = (i) => ({ free: true, cost: 1200, cards_held: 5, cards_needed: 3, card_name: "Video Pro", card_template: "tpl-video", i });
    const t = tallyPricesDetailed([pr(1), pr(2), pr(3)]);
    assert.equal(t.free, 1);
    assert.equal(t.paid, 2);
    assert.equal(t.credits, 2400, "overflow shots are counted at their FULL price, never a partial one");
    assert.equal(t.unknown, 0);
    assert.equal(t.overflow, 2);
    assert.deepEqual(t.pools, { "tpl-video": { name: "Video Pro", held: 5, needed: 9 } });
    // the four-bucket tallyPrices every existing caller reads gives the SAME answer
    assert.deepEqual(tallyPrices([pr(1), pr(2), pr(3)]), { free: 1, paid: 2, credits: 2400, unknown: 0 });
  });
  test("tally: pools are per template -- another template's tickets are not drawn down", () => {
    const vid = { free: true, cost: 1200, cards_held: 3, cards_needed: 3, card_template: "tpl-video", card_name: "Video Pro" };
    const img = { free: true, cost: 100, cards_held: 1, cards_needed: 1, card_template: "tpl-image", card_name: "Image" };
    const t = tallyPricesDetailed([vid, img, vid]);
    assert.equal(t.free, 2);
    assert.equal(t.paid, 1);
    assert.equal(t.credits, 1200);
    assert.equal(t.overflow, 1);
  });
  test("tally: a leftover ticket still funds a later 1-ticket shot after a 3-ticket one is refused (submission order, not greedy re-sort)", () => {
    const big = { free: true, cost: 1200, cards_held: 4, cards_needed: 3, card_template: "tpl-video" };
    const small = { free: true, cost: 400, cards_held: 4, cards_needed: 1, card_template: "tpl-video" };
    const t = tallyPricesDetailed([big, big, small]);
    assert.deepEqual([t.free, t.paid, t.credits, t.overflow], [2, 1, 1200, 1]);
  });
  test("tally: falls back to card_name as the pool key when card_template is absent", () => {
    const pr = { free: true, cost: 1200, cards_held: 3, cards_needed: 3, card_name: "Video Pro" };
    const t = tallyPricesDetailed([pr, pr]);
    assert.deepEqual([t.free, t.paid, t.overflow], [1, 1, 1]);
    assert.deepEqual(t.pools, { "Video Pro": { name: "Video Pro", held: 3, needed: 6 } });
  });
  test("tally: a free result with no pool info (older server / unknown balance) keeps the server's verdict", () => {
    const t = tallyPricesDetailed([{ free: true }, { free: true, cost: 50 }]);
    assert.deepEqual([t.free, t.paid, t.overflow], [2, 0, 0]);
    assert.deepEqual(t.pools, {});
  });
  test("tally: server-flagged short shots are plain paid (they never draw from the pool) and nulls stay unknown", () => {
    const t = tallyPricesDetailed([short15, null, { free: false, cost: 900 }]);
    assert.deepEqual(t, { free: 0, paid: 2, credits: 2100, unknown: 1, overflow: 0, pools: {} });
  });
  test("tally: an overflow shot whose cost is unknown buckets as unknown, never as free", () => {
    const pr = (cost) => ({ free: true, cost, cards_held: 1, cards_needed: 1, card_template: "t" });
    const t = tallyPricesDetailed([pr(100), pr(null)]);
    assert.deepEqual([t.free, t.paid, t.unknown, t.overflow], [1, 0, 1, 1]);
  });
});

describe("costTooltip", () => {
  // Same hard rule as formatCostEstimate (see the shared comment above it in
  // loom-core.js): a "0 cr"/"free" reading must only ever mean a genuinely settled,
  // zero-cost result -- never merely unpriced or still-pricing. costTooltip's long
  // form spells out every bucket by name, so the failure mode isn't a bare wrong
  // word -- it's the `pending` count going missing from the sentence, which would
  // leave "0 free-card, 0 paid (≈0 credits), 0 unpriced." standing on its own and
  // reading exactly like a fully-settled, nothing-to-pay result.
  test("genuinely free/settled result", () => {
    const text = costTooltip({ free: 2, paid: 0, credits: 0, unknown: 0, pending: 0 });
    assert.equal(text, "Cost to finish: 2 free-card, 0 paid (≈0 credits), 0 unpriced.");
  });

  test("paid/settled result shows the real credit total", () => {
    const text = costTooltip({ free: 0, paid: 3, credits: 1500, unknown: 0, pending: 0 });
    assert.equal(text, "Cost to finish: 0 free-card, 3 paid (≈1,500 credits), 0 unpriced.");
  });

  test("unpriced/pending state names the pending count instead of reading as settled-free", () => {
    const text = costTooltip({ free: 0, paid: 0, credits: 0, unknown: 0, pending: 4 });
    assert.equal(text, "Cost to finish: 0 free-card, 0 paid (≈0 credits), 0 unpriced, 4 still estimating.");
    // The specific conflation this guards against: with pending dropped from the
    // sentence, an all-zeros tooltip would be indistinguishable from a real free result.
    assert.notEqual(text, "Cost to finish: 0 free-card, 0 paid (≈0 credits), 0 unpriced.");
  });

  test("pending is additive alongside real settled figures, not a replacement for them", () => {
    const text = costTooltip({ free: 1, paid: 2, credits: 900, unknown: 1, pending: 3 });
    assert.equal(text, "Cost to finish: 1 free-card, 2 paid (≈900 credits), 1 unpriced, 3 still estimating.");
  });

  test("no pending omits 'still estimating' entirely (only settled figures shown)", () => {
    const text = costTooltip({ free: 0, paid: 1, credits: 250, unknown: 0, pending: 0 });
    assert.doesNotMatch(text, /estimating/);
  });
});

/* ---------- shotPayload (FLF frame-tag fallback) ---------- */

describe("shotPayload", () => {
  // A fake imgSrc: any thumbId/source that isn't empty resolves to a fake data value.
  const fakeImgSrc = (thumbId, source) => thumbId || source || null;

  test("quality follows the project draft flag (basic when draft, else professional)", () => {
    const card = makeCard({ cast: [], openFrame: { thumbId: "t", source: "", desc: "", tag: "@image8" } });
    const proj = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    assert.equal(shotPayload(flat(proj)[0], proj, fakeImgSrc).quality, "professional");
    proj.draft = true;
    assert.equal(shotPayload(flat(proj)[0], proj, fakeImgSrc).quality, "basic");
  });

  test("carries the shot's audio request (generate_audio/audio_language) onto the payload", () => {
    const base = { cast: [], openFrame: { thumbId: "t", source: "", desc: "", tag: "@image8" } };
    const off = makeCard(base);
    const proj1 = makeProject([{ id: "a1", name: "Act", cards: [off] }]);
    const p1 = shotPayload(flat(proj1)[0], proj1, fakeImgSrc);
    assert.equal(p1.generate_audio, false);
    assert.equal(p1.audio_language, "english");   // default even when off, matches the server's own default

    const on = makeCard({ ...base, audioGen: true, audioLanguage: "none" });   // "none" = SE-only, not silence
    const proj2 = makeProject([{ id: "a1", name: "Act", cards: [on] }]);
    const p2 = shotPayload(flat(proj2)[0], proj2, fakeImgSrc);
    assert.equal(p2.generate_audio, true);
    assert.equal(p2.audio_language, "none");
  });

  test("carries the shot's Channel (is_private) onto the payload -- Normal by default, Enhanced when set", () => {
    // 2026-08-06 owner correction: the Normal/Enhanced channel is the REAL field
    // mg-generate-drawer has always submitted and the server's shared
    // build_shot_video_params has always accepted on this route -- the Loom client
    // just never sent it (an earlier audit wrongly recorded the field as nonexistent).
    const base = { cast: [], openFrame: { thumbId: "t", source: "", desc: "", tag: "@image8" } };
    const normal = makeCard(base);
    const proj1 = makeProject([{ id: "a1", name: "Act", cards: [normal] }]);
    assert.equal(shotPayload(flat(proj1)[0], proj1, fakeImgSrc).is_private, false,
      "absent isPrivate must read as the drawer's own Normal default");
    const enhanced = makeCard({ ...base, isPrivate: true });
    const proj2 = makeProject([{ id: "a1", name: "Act", cards: [enhanced] }]);
    assert.equal(shotPayload(flat(proj2)[0], proj2, fakeImgSrc).is_private, true);
  });

  test("FLF shot with two UNTAGGED frames gets DISTINCT fallback tags (never the same one)", () => {
    const card = makeCard({
      mode: "FLF",
      openFrame: { thumbId: "thumb-open", source: "", desc: "", tag: "" },
      closeFrame: { thumbId: "thumb-close", source: "", desc: "", tag: "" },
    });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, fakeImgSrc);
    // Both frames resolved to image data (2 images total: no cast, no refs) --
    // if open/close had collided on the same fallback tag, the second push
    // would still happen (shotPayload doesn't dedupe by tag), but ordering
    // downstream would be ambiguous. The real guarantee is the next test,
    // which pins down which physical frame ends up in which position.
    assert.equal(payload.images.length, 2);
  });

  test("FLF fallback tags are truly distinct end-to-end (dedup check)", () => {
    // Build a project where BOTH frames are untagged; if the implementation
    // regressed to using the SAME fallback tag for both, this test — which
    // inspects the tags that end up sorted into `images` order via a probe
    // image list — would show a collision because sort-by-tag-number would
    // put them adjacent with an identical extracted number.
    const card = makeCard({
      mode: "FLF",
      openFrame: { thumbId: "open-data", source: "", desc: "", tag: "" },
      closeFrame: { thumbId: "close-data", source: "", desc: "", tag: "" },
    });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, fakeImgSrc);
    assert.equal(payload.images.length, 2);
    // Both frames must be present (order-independent check first)...
    assert.deepEqual([...payload.images].sort(), ["close-data", "open-data"].sort());
    // ...and the open frame (fallback @image8) must sort ahead of the close
    // frame (fallback @image9) -- proving the two fallback tags are DISTINCT
    // and correctly ordered, not both collapsed onto the same literal.
    assert.equal(payload.images[0], "open-data");
    assert.equal(payload.images[1], "close-data");
  });

  test("I2V ignores the close frame entirely (no phantom second image)", () => {
    // Was titled "non-FLF mode ignores the close frame" -- no longer true as a class:
    // CLOSE_FRAME_MODES (loom-core.js) now includes R2V and V2V, whose generations really
    // do consume an end frame (med3-close-frame-joins-numbering.test.js). I2V is the one
    // mode that still ignores it, and must keep doing so.
    const card = makeCard({
      mode: "I2V",
      openFrame: { thumbId: "open-data", source: "", desc: "", tag: "" },
      closeFrame: { thumbId: "close-data", source: "", desc: "", tag: "" },
    });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, fakeImgSrc);
    assert.deepEqual(payload.images, ["open-data"]);
  });

  test("tagged frames keep their own tag instead of the fallback", () => {
    const card = makeCard({
      mode: "FLF",
      openFrame: { thumbId: "open-data", source: "", desc: "", tag: "@image2" },
      closeFrame: { thumbId: "close-data", source: "", desc: "", tag: "@image3" },
    });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }]);
    const entry = flat(project)[0];
    const payload = shotPayload(entry, project, fakeImgSrc);
    // Sorted by tag number: @image2 (open) before @image3 (close).
    assert.deepEqual(payload.images, ["open-data", "close-data"]);
  });

  test("hasInput is false with no cast/frames/refs, true once something resolves", () => {
    const empty = makeCard({ mode: "I2V" });
    const project = makeProject([{ id: "a1", name: "Act", cards: [empty] }]);
    const payload = shotPayload(flat(project)[0], project, () => null);
    assert.equal(payload.hasInput, false);

    const withFrame = makeCard({ mode: "I2V", openFrame: { thumbId: "x", source: "", desc: "", tag: "" } });
    const project2 = makeProject([{ id: "a1", name: "Act", cards: [withFrame] }]);
    const payload2 = shotPayload(flat(project2)[0], project2, fakeImgSrc);
    assert.equal(payload2.hasInput, true);
  });
});

/* ---------- durOf / reelStats ---------- */

describe("durOf / reelStats", () => {
  test("durOf prefers actualDur over planned duration", () => {
    assert.equal(durOf({ duration: 8, actualDur: 6 }), 6);
    assert.equal(durOf({ duration: 8 }), 8);
    assert.equal(durOf({}), 0);
  });

  test("reelStats sums durations and computes scale/over vs target", () => {
    const entries = [
      { c: { duration: 8 } },
      { c: { duration: 10, actualDur: 12 } },
    ];
    const { total, scale, over } = reelStats(entries, 15);
    assert.equal(total, 20);          // 8 + 12 (actualDur wins for the second)
    assert.equal(scale, 20);          // max(total, target)
    assert.equal(over, 5);            // 20 - 15
  });

  test("reelStats under target: scale follows target, over is negative", () => {
    const entries = [{ c: { duration: 5 } }];
    const { total, scale, over } = reelStats(entries, 30);
    assert.equal(total, 5);
    assert.equal(scale, 30);
    assert.equal(over, -25);
  });

  test("reelStats with zero total and zero target falls back to scale 1 (no div-by-zero)", () => {
    const { total, scale, over } = reelStats([], 0);
    assert.equal(total, 0);
    assert.equal(scale, 1);
    assert.equal(over, 0);
  });
});
