import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { TYPE_HUES, fmtBytes, storageBars, storageFilterPatch } from "../../gallery/src/curation/storageCore.js";

/* Session N6, the client half of the storage bars: the payload's `storage` block (built and
   pinned by dev/tests/test_aspect_and_storage.py) turned into segments, and a segment's click turned
   into the filter that opens the gallery. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

const seg = (name, bytes, count, extra) => ({ name, bytes, h: bytes + " B", count, ...extra });
const STORAGE = {
  total_bytes: 1000, total_h: "1000 B", files: 6,
  by_type: [seg("Images", 600, 4, { key: "image" }), seg("Videos", 0, 0, { key: "video" }), seg("Loom renders", 400, 2, { key: "loom" })],
  by_model: [seg("Tsubaki.3", 700, 4, { other: false }), seg("Other", 300, 2, { other: true })],
  by_collection: { sum_bytes: 1500, segments: [seg("Druid", 900, 3, { other: false }), seg("Faves", 400, 2, { other: false }), seg("Other", 200, 1, { other: true })] },
};

describe("the bars", () => {
  const bars = storageBars(STORAGE);
  test("three bars, in the page's order", () => {
    assert.deepEqual(bars.map((b) => b.id), ["type", "model", "collection"]);
    assert.deepEqual(bars.map((b) => b.label), ["BY TYPE", "BY MODEL", "BY COLLECTION"]);
  });
  test("the collection bar says it can overlap; the others do not", () => {
    assert.equal(bars[2].note, "can overlap");
    assert.equal(bars[0].note, undefined);
    assert.equal(bars[1].note, undefined);
  });
  test("a segment with no bytes is not drawn (it would open an empty page)", () => {
    assert.deepEqual(bars[0].segments.map((s) => s.label), ["Images", "Loom renders"]);
  });
  test("type and model are shares of the library; collections are shares of their own sum", () => {
    assert.deepEqual(bars[0].segments.map((s) => s.pct), [60, 40]);
    assert.deepEqual(bars[1].segments.map((s) => s.pct), [70, 30]);
    assert.deepEqual(bars[2].segments.map((s) => Math.round(s.pct)), [60, 27, 13]);
    for (const b of bars) assert.ok(Math.abs(b.segments.reduce((a, s) => a + s.pct, 0) - 100) < 1e-9);
  });
  test("the type hues follow the skin: accent image, an accent-derived video, the Loom's own cyan for renders", () => {
    // the owner's colour ruling, 2026-09-29
    assert.equal(TYPE_HUES.image, "var(--accent)");
    assert.match(TYPE_HUES.video, /^color-mix\(in oklab, var\(--accent\) \d+%, var\(--base\)\)$/);
    assert.notEqual(TYPE_HUES.video, TYPE_HUES.image, "video is a second tone, not the image tone");
    assert.equal(TYPE_HUES.loom, "var(--loomc)");
    assert.equal(bars[0].segments[0].hue, TYPE_HUES.image);
    assert.equal(bars[0].segments[1].hue, "var(--loomc)");
  });
  test("gold is billing only: no hue on any bar reads --gold", () => {
    const wide = storageBars({ ...STORAGE, by_type: [seg("Images", 500, 1, { key: "image" }), seg("Videos", 300, 1, { key: "video" }), seg("Loom renders", 200, 1, { key: "loom" })],
      by_collection: { sum_bytes: 900, segments: [1, 2, 3, 4, 5, 6].map((i) => seg("C" + i, 150, 1, { other: false })) } });
    for (const b of wide) for (const s of b.segments) assert.doesNotMatch(s.hue, /--gold/, s.title);
    assert.doesNotMatch(src("curation/storageCore.js").replace(/\/\*[\s\S]*?\*\//g, ""), /--gold/);
    assert.doesNotMatch(src("components/StorageBars.jsx").replace(/\/\*[\s\S]*?\*\//g, ""), /--gold/);
  });
  test("no skin redefines --loomc (cyan means the Loom in every skin), and every skin redefines --accent", () => {
    const tokens = readFileSync(path.join(here, "..", "..", "static", "design-tokens.css"), "utf8").replace(/\r\n/g, "\n");
    const skins = [...tokens.matchAll(/html\[data-skin="(\w+)"\]\s*\{([^}]*)\}/g)];
    assert.deepEqual(skins.map((m) => m[1]).sort(), ["ember", "moonlit", "nightfallen", "verdant"]);
    for (const [, name, body] of skins) {
      assert.doesNotMatch(body, /--loomc\s*:/, name + " must not change the Loom's cyan");
      assert.match(body, /--accent\s*:/, name + " sets the accent the bars follow");
    }
  });
  test("every hue is a token, never a hex", () => {
    for (const b of bars) for (const s of b.segments) assert.ok(!/#[0-9a-f]{3,8}/i.test(s.hue), s.hue);
  });
  test("a title says the name, the size and how many pictures", () => {
    assert.equal(bars[0].segments[0].title, "Images · 600 B · 4 pictures");
    assert.equal(storageBars({ ...STORAGE, by_type: [seg("Videos", 1000, 1, { key: "video" })] })[0].segments[0].title,
      "Videos · 1000 B · 1 picture");
  });
  test("no payload, or nothing on disk, is no bars", () => {
    assert.deepEqual(storageBars(null), []);
    assert.deepEqual(storageBars(undefined), []);
    assert.deepEqual(storageBars({ total_bytes: 0, by_type: [], by_model: [], by_collection: { segments: [] } }), []);
  });
  test("a library with no hand-picked collections draws two bars", () => {
    const b = storageBars({ ...STORAGE, by_collection: { sum_bytes: 0, segments: [] } });
    assert.deepEqual(b.map((x) => x.id), ["type", "model"]);
  });
});

describe("what a click opens", () => {
  const bars = storageBars(STORAGE);
  test("a type is the type: operator", () => {
    assert.deepEqual(storageFilterPatch(bars[0].segments[1].filter),
      { q: "type:loom", model: "", shelf: "", media: "" });
  });
  test("a model is the Model filter, a collection is the shelf", () => {
    assert.deepEqual(storageFilterPatch(bars[1].segments[0].filter),
      { q: "", model: "Tsubaki.3", shelf: "", media: "" });
    assert.deepEqual(storageFilterPatch(bars[2].segments[0].filter),
      { q: "", model: "", shelf: "Druid", media: "" });
  });
  test("Other opens nothing: it is everything not named", () => {
    assert.equal(bars[1].segments[1].filter, null);
    assert.equal(storageFilterPatch(bars[1].segments[1].filter), null);
    assert.equal(storageFilterPatch(undefined), null);
  });
});

describe("bytes in words", () => {
  test("scales", () => {
    assert.equal(fmtBytes(0), "0 B");
    assert.equal(fmtBytes(1536), "1.5 KB");
    assert.equal(fmtBytes(5 * 1024 * 1024), "5.0 MB");
    assert.equal(fmtBytes(3.5 * 1024 ** 3), "3.5 GB");
    assert.equal(fmtBytes(-4), "0 B");
  });
});

describe("the screens use it", () => {
  test("desktop and phone Health both draw the same bars from the same hook", () => {
    assert.match(src("components/HealthOverlay.jsx"), /<StorageBars storage=\{storage\}/);
    assert.match(src("components/HealthMobile.jsx"), /<StorageBars storage=\{storage\}[^>]*compact/);
    assert.match(src("components/StorageBars.jsx"), /storageBars\(storage\)/);
    assert.match(src("hooks/useHealth.js"), /h\.storage/);
  });
  test("the single Storage used tile is gone from Health's tiles", () => {
    const hook = src("hooks/useHealth.js");
    const stats = hook.slice(hook.indexOf("const stats = h ? ["), hook.indexOf("] : [];"));
    assert.doesNotMatch(stats, /Storage used/);
  });
  test("the Folio's Statistics tab keeps its Storage used figure, from the bars' own total", () => {
    assert.match(src("hooks/useHealth.js"), /const storageStat = h \? \{ label: "Storage used", value: \(storage && storage\.total_h\)/);
    const folio = src("components/FolioOverlay.jsx");
    assert.match(folio, /storageStat/);
    assert.match(folio, /\[\s*healthStats\.find\(\(s\) => s\.label === "Images on disk"\), storageStat,/);
  });
});
