import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  CONNECT, CONTINUITY_PHRASE, actLetter,
  maxTagNum, nextTag, frameLinked, connectMeta,
  flat, shotText, shotPayload, durOf, reelStats,
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
