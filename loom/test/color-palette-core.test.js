import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* The Generate drawer's colour palette (Session H decision 4, Tsubaki3 Generate Handoff frame D;
   the Library tab to PixAI's own pattern). gallery/src/gen/colorPaletteCore.js holds every
   rule the editor and the request follow; these pin them without a DOM. */

import {
  GROUPS, MAX_COLORS, MINE_MAX, UNTITLED, cleanColors, editorFromPalette, evenShares,
  extractColors, fillGroup, focusBand, groupLocked, groupTotal, moveColor, newEditor,
  normalizeMine, normalizePreset, paletteForPayload, paletteRowState, paletteSummary,
  previewOf, removeColor, removeMine, rename, replaceFromLibrary, setCount, setDivider,
  dividerShareAt, setHex, stepShare, toPalette, toPercents, toggleGroup, upsertMine, validate,
} from "../../gallery/src/gen/colorPaletteCore.js";

const sums = (ed) => GROUPS.filter((k) => ed.on[k]).map((k) => groupTotal(ed.groups[k]));
const WISTERIA = {
  overall: { colors: [{ hex: "#b0c7e8", ratio: 30 }, { hex: "#DCF0F9", ratio: 20 }, { hex: "#5564A5", ratio: 15 },
    { hex: "#DAD1D8", ratio: 15 }, { hex: "#4F70F1", ratio: 10 }, { hex: "#E4B3C6", ratio: 10 }] },
  background: { colors: [{ hex: "#FEF9F7", ratio: 60 }, { hex: "#ADC2DF", ratio: 40 }] },
};

describe("shares", () => {
  test("even shares put the remainder first: six is 17/17/17/17/16/16", () => {
    assert.deepEqual(evenShares(6), [17, 17, 17, 17, 16, 16]);
    assert.deepEqual(evenShares(1), [100]);
    assert.deepEqual(evenShares(12).reduce((a, b) => a + b, 0), 100);
  });
  test("whole percents that already sum to 100 come back unchanged", () => {
    assert.deepEqual(toPercents([30, 20, 15, 15, 10, 10]), [30, 20, 15, 15, 10, 10]);
  });
  test("any weights become whole percents summing to 100, none under 1", () => {
    const p = toPercents([1000, 1, 1]);
    assert.equal(p.reduce((a, b) => a + b, 0), 100);
    assert.ok(p.every((x) => x >= 1));
    assert.deepEqual(toPercents([0, 0]), [50, 50]);
  });
});

describe("the editor", () => {
  test("a new palette opens on overall with six even colours; the others are off", () => {
    const ed = newEditor();
    assert.equal(ed.name, UNTITLED);
    assert.deepEqual(ed.on, { overall: true, background: false, character: false });
    assert.deepEqual(ed.groups.overall.map((c) => c.ratio), [17, 17, 17, 17, 16, 16]);
    assert.deepEqual(validate(ed), []);
  });

  test("overall or background must stay on: the last of the two is locked", () => {
    let ed = newEditor();
    assert.equal(groupLocked(ed, "overall"), true);
    assert.equal(toggleGroup(ed, "overall"), ed);                 // refused, same state
    ed = toggleGroup(ed, "background");
    assert.equal(ed.on.background, true);
    assert.deepEqual(ed.groups.background.map((c) => c.ratio), [17, 17, 17, 17, 16, 16]);
    assert.equal(groupLocked(ed, "overall"), false);
    ed = toggleGroup(ed, "overall");
    assert.equal(ed.on.overall, false);
    assert.equal(groupLocked(ed, "background"), true);
  });

  test("turning a group off holds its colours; turning it back on restores them", () => {
    let ed = toggleGroup(newEditor(), "character");
    ed = setHex(ed, "character", 0, "#123456");
    ed = toggleGroup(ed, "character");
    assert.equal(ed.on.character, false);
    assert.equal(toPalette(ed).character, undefined);            // not sent while off
    ed = toggleGroup(ed, "character");
    assert.equal(ed.groups.character[0].hex, "#123456");
  });

  test("turning off the focused group moves the focus", () => {
    let ed = toggleGroup(newEditor(), "character");
    assert.deepEqual(ed.focus, { group: "character", index: 0 });
    ed = toggleGroup(ed, "character");
    assert.equal(ed.focus.group, "overall");
  });

  test("the count stepper runs 1-12, keeps the colours it has and re-evens", () => {
    let ed = setHex(newEditor(), "overall", 0, "#010203");
    ed = setCount(ed, "overall", 3);
    assert.equal(ed.groups.overall.length, 3);
    assert.equal(ed.groups.overall[0].hex, "#010203");
    assert.deepEqual(ed.groups.overall.map((c) => c.ratio), [34, 33, 33]);
    ed = setCount(ed, "overall", 99);
    assert.equal(ed.groups.overall.length, MAX_COLORS);
    assert.equal(new Set(ed.groups.overall.map((c) => c.hex)).size, MAX_COLORS);
    ed = setCount(ed, "overall", 0);
    assert.equal(ed.groups.overall.length, 1);
    assert.deepEqual(sums(ed), [100]);
  });

  test("a share step trades with ONE neighbour and never drops a colour under 1", () => {
    let ed = setCount(newEditor(), "overall", 3);                   // 34/33/33
    ed = stepShare(ed, "overall", 0, +1);
    assert.deepEqual(ed.groups.overall.map((c) => c.ratio), [35, 32, 33]);
    ed = stepShare(ed, "overall", 2, +1);                           // the last trades left
    assert.deepEqual(ed.groups.overall.map((c) => c.ratio), [35, 31, 34]);
    ed = stepShare(ed, "overall", 0, -1);
    assert.deepEqual(ed.groups.overall.map((c) => c.ratio), [34, 32, 34]);
    let two = setCount(newEditor(), "overall", 2);                  // 50/50
    for (let i = 0; i < 60; i++) two = stepShare(two, "overall", 0, +1);
    assert.deepEqual(two.groups.overall.map((c) => c.ratio), [99, 1]);
    const one = setCount(newEditor(), "overall", 1);
    assert.equal(stepShare(one, "overall", 0, +1), one);           // 100%, nothing to trade
  });

  test("a divider sets the pair's split, clamped to 1 each, and leaves the rest", () => {
    let ed = editorFromPalette(WISTERIA, { name: "W" });
    ed = setDivider(ed, "overall", 0, 45);                          // pair 30+20 = 50
    assert.deepEqual(ed.groups.overall.map((c) => c.ratio), [45, 5, 15, 15, 10, 10]);
    ed = setDivider(ed, "overall", 0, 80);
    assert.deepEqual(ed.groups.overall.slice(0, 2).map((c) => c.ratio), [49, 1]);
    assert.deepEqual(sums(ed), [100, 100]);
    // the pointer maths: 60% across the whole bar with 30 before the pair -> 30 for colour 1
    assert.equal(dividerShareAt(ed.groups.overall, 1, 0.6), 60 - 49);
  });

  test("reorder swaps and the focus follows; remove gives the share to one neighbour", () => {
    let ed = focusBand(editorFromPalette(WISTERIA, {}), "overall", 1);
    ed = moveColor(ed, "overall", 1, -1);
    assert.equal(ed.groups.overall[0].hex, "#DCF0F9");
    assert.equal(ed.focus.index, 0);
    assert.equal(moveColor(ed, "overall", 0, -1), ed);             // already first
    ed = removeColor(ed, "overall", 0);
    assert.equal(ed.groups.overall.length, 5);
    assert.equal(ed.groups.overall[0].ratio, 50);                   // 20 joined the next (30)
    assert.deepEqual(sums(ed), [100, 100]);
    let one = setCount(newEditor(), "overall", 1);
    assert.equal(removeColor(one, "overall", 0), one);             // never empty a group
  });

  test("hexes are checked and upper-cased; names are held to 50", () => {
    const ed = newEditor();
    assert.equal(setHex(ed, "overall", 0, "not-a-hex"), ed);
    assert.equal(setHex(ed, "overall", 0, "#abcdef").groups.overall[0].hex, "#ABCDEF");
    assert.equal(rename(ed, "x".repeat(80)).name.length, 50);
    assert.deepEqual(validate(rename(ed, "  ")), ["Give the palette a name"]);
  });

  test("replace from the Library keeps the name and id, takes the colours and switches", () => {
    let ed = { ...newEditor("Mine"), id: "m1" };
    ed = replaceFromLibrary(ed, { name: "Wisteria Whisper", palette: WISTERIA });
    assert.equal(ed.name, "Mine");
    assert.equal(ed.id, "m1");
    assert.equal(ed.from, "Wisteria Whisper");
    assert.deepEqual(ed.on, { overall: true, background: true, character: false });
    assert.equal(ed.groups.overall[0].hex, "#B0C7E8");
  });

  test("extract fills the focused group and turns it on", () => {
    let ed = fillGroup(newEditor(), "background", [{ hex: "#000000", ratio: 3 }, { hex: "#ffffff", ratio: 1 }]);
    assert.equal(ed.on.background, true);
    assert.deepEqual(ed.groups.background, [{ hex: "#000000", ratio: 75 }, { hex: "#FFFFFF", ratio: 25 }]);
    assert.deepEqual(ed.focus, { group: "background", index: 0 });
  });
});

describe("the request", () => {
  const applied = { name: "W", palette: toPalette(editorFromPalette(WISTERIA, {})), source: "library", id: "1" };
  const t3 = { version_id: "v", color_palette: true };

  test("only the groups that are on go out, in PixAI's {colors:[{hex, ratio}]} shape", () => {
    const p = toPalette(editorFromPalette(WISTERIA, {}));
    assert.deepEqual(Object.keys(p), ["overall", "background"]);
    assert.deepEqual(p.background, { colors: [{ hex: "#FEF9F7", ratio: 60 }, { hex: "#ADC2DF", ratio: 40 }] });
  });

  test("sent only with a palette, a model that takes one, and no context image", () => {
    assert.deepEqual(paletteForPayload({ palette: applied, model: t3 }, false),
      { name: "W", palette: applied.palette });
    assert.equal(paletteForPayload({ palette: applied, model: t3 }, true), null);
    assert.equal(paletteForPayload({ palette: applied, model: { color_palette: false } }, false), null);
    assert.equal(paletteForPayload({ palette: applied, model: { version_id: "v" } }, false), null);
    assert.equal(paletteForPayload({ palette: null, model: t3 }, false), null);
    assert.equal(paletteForPayload({ palette: { name: "x", palette: { character: { colors: [] } } }, model: t3 }, false), null);
  });

  test("the row says held, never drops the pick", () => {
    assert.equal(paletteRowState({ palette: applied, model: t3 }, false).state, "on");
    assert.equal(paletteRowState({ palette: applied, model: t3 }, true).note, "Held · not sent with context images");
    assert.equal(paletteRowState({ palette: applied, model: { color_palette: false } }, false).state, "held");
    assert.equal(paletteRowState({ palette: null, model: t3 }, false).state, "none");
    assert.equal(paletteSummary(applied), "W · overall + background");
  });

  test("the preview card: background is the field, character or overall the figure", () => {
    const p = previewOf(toPalette(editorFromPalette(WISTERIA, {})));
    assert.equal(p.field, "#FEF9F7");
    assert.equal(p.figure, "#B0C7E8");
    assert.equal(p.strip.length, 6);
  });
});

describe("the Library and mine", () => {
  test("a preset is cleaned and one with no usable colours is dropped", () => {
    const p = normalizePreset({ id: "1", name: "W", cover_url: "https://x/y", palette: WISTERIA });
    assert.equal(p.palette.overall.colors[0].hex, "#B0C7E8");
    assert.equal(normalizePreset({ id: "2", name: "empty", palette: {} }), null);
    assert.deepEqual(cleanColors({ colors: [{ hex: "bad", ratio: 50 }, { hex: "#000000", ratio: 5 }] }),
      [{ hex: "#000000", ratio: 100 }]);
  });

  test("save as mine replaces by id, adds new ones first, and refuses past the cap", () => {
    const ed = rename(newEditor(), "A");
    let r = upsertMine([], ed, "m1");
    assert.equal(r.list.length, 1);
    assert.equal(r.entry.id, "m1");
    r = upsertMine(r.list, { ...rename(newEditor(), "A2"), id: "m1" }, "zz");
    assert.equal(r.list.length, 1);
    assert.equal(r.list[0].name, "A2");
    const many = Array.from({ length: MINE_MAX }, (_, i) => ({ id: "x" + i, name: "n", palette: toPalette(newEditor()) }));
    const full = upsertMine(many, rename(newEditor(), "B"), "new");
    assert.equal(full.full, true);
    assert.equal(full.list.length, MINE_MAX);
    assert.equal(removeMine(r.list, "m1").length, 0);
    assert.deepEqual(normalizeMine([null, { id: "a", palette: {} }, "x"]), []);
  });
});

describe("extract from image", () => {
  test("median cut gives the picture's colours by share, deterministically", () => {
    // 3/4 black, 1/4 white, fully opaque; one transparent pixel is skipped
    const px = [];
    for (let i = 0; i < 12; i++) px.push(0, 0, 0, 255);
    for (let i = 0; i < 4; i++) px.push(255, 255, 255, 255);
    px.push(255, 0, 0, 0);
    const out = extractColors(new Uint8ClampedArray(px), 6);
    assert.deepEqual(out, [{ hex: "#000000", ratio: 75 }, { hex: "#FFFFFF", ratio: 25 }]);
    assert.deepEqual(extractColors(new Uint8ClampedArray(px), 6), out);
    assert.deepEqual(extractColors(new Uint8ClampedArray([0, 0, 0, 0]), 6), []);
  });
});

describe("the drawer's payload (genCore.buildPayload)", () => {
  test("carries color_palette only when it applies; otherwise the key is absent", async () => {
    const { buildPayload, GEN_DEFAULTS } = await import("../../gallery/src/gen/genCore.js");
    const pal = { name: "W", palette: toPalette(editorFromPalette(WISTERIA, {})), source: "library", id: "1" };
    const model = { model_id: "m", version_id: "v", color_palette: true, context_images: true };
    const on = buildPayload({ ...GEN_DEFAULTS, model, prompt: "p", palette: pal });
    assert.deepEqual(on.color_palette, { name: "W", palette: pal.palette });
    const none = buildPayload({ ...GEN_DEFAULTS, model, prompt: "p" });
    assert.ok(!("color_palette" in none));
    const held = buildPayload({ ...GEN_DEFAULTS, model, prompt: "p", palette: pal, ref: { media_id: "9" } });
    assert.ok(!("color_palette" in held), "a context image holds the palette");
    const off = buildPayload({ ...GEN_DEFAULTS, model: { ...model, color_palette: null }, prompt: "p", palette: pal });
    assert.ok(!("color_palette" in off), "unknown support is not sent");
    // the palette is the only difference
    const { color_palette, ...rest } = on;
    assert.deepEqual(rest, none);
  });
});
