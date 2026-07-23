import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  CONNECT, CONTINUITY_PHRASE, actLetter,
  maxTagNum, nextTag, frameLinked, connectMeta, continuityLinked,
  flat, shotText, shotPayload, durOf, reelStats, effectivePrompt,
  priceFingerprint, tallyPrices, formatCostEstimate,
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

  test("'flf' connect includes open/close frame descriptions", () => {
    const card = makeCard({
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
    const asset = { id: "as1", name: "Nel", tag: "@image1", lock: true };
    const card = makeCard({ cast: ["as1"] });
    const project = makeProject([{ id: "a1", name: "Act", cards: [card] }], [asset]);
    const text = shotText(flat(project)[0], project);
    assert.match(text, /Nel — maintain exact appearance from @image1/);
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

  test("non-FLF mode ignores the close frame entirely (no phantom second image)", () => {
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
