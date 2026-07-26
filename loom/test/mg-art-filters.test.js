import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// static/mg-art-filters.js is a plain global IIFE with no build step (same shape as
// mg-cost-badge.js / mg-model-picker.js), so it cannot be `import`ed here. Unlike those
// two, though, almost all of its interesting behaviour lives in PURE functions -- the
// recipe data, the blend-mode mapping, the layer/stop normalizer, the gradient strings --
// so instead of the source-presence-only pattern this whole file loads the module FOR REAL
// through `new Function` against a fake `window`, and calls the exported API. Only the
// canvas/DOM half (which needs a real 2d context and a real layout) falls back to
// source-presence assertions at the bottom.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC_PATH = path.join(__dirname, "../../static/mg-art-filters.js");
const src = readFileSync(SRC_PATH, "utf8");

// A stub `document` is enough because the module must not touch the DOM at load time --
// it only reaches for document.createElement inside the render/composite calls. If a
// future edit moves a style injection to load time, this stub will throw and say so.
function load() {
  const win = {};
  const doc = {
    createElement() { throw new Error("mg-art-filters.js must not touch the DOM at load time"); },
    getElementById() { return null; },
  };
  new Function("window", "document", src)(win, doc);
  assert.ok(win.MgArtFilters, "the IIFE must export window.MgArtFilters");
  return win.MgArtFilters;
}

const AF = load();

// Every value CSS mix-blend-mode accepts (CSS Compositing 1 + 2). A mapping outside this
// list is a typo that would silently render as `normal` in the browser.
const CSS_BLEND_MODES = new Set([
  "normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge",
  "color-burn", "hard-light", "soft-light", "difference", "exclusion", "hue",
  "saturation", "color", "luminosity", "plus-lighter", "plus-darker",
]);
// Every value canvas globalCompositeOperation accepts (Porter-Duff ops + the same blend
// modes). Note `plus-lighter` is NOT here -- canvas spells that operator `lighter`.
const CANVAS_OPS = new Set([
  "source-over", "source-in", "source-out", "source-atop", "destination-over",
  "destination-in", "destination-out", "destination-atop", "lighter", "copy", "xor",
  "multiply", "screen", "overlay", "darken", "lighten", "color-dodge", "color-burn",
  "hard-light", "soft-light", "difference", "exclusion", "hue", "saturation", "color",
  "luminosity",
]);

// The 8 modes PixAI's own imageArtFilters payload actually uses across its 7 filters.
// If PixAI adds a 9th, the "every used mode is mapped" test below fails on the refreshed
// data rather than the module quietly rendering the new layer wrong.
const USED_MODES = [
  "darker-color", "soft-light", "color-burn", "lighter-color", "plus-lighter",
  "saturation", "screen", "overlay",
];

describe("recipe data integrity (baked from PixAI's public imageArtFilters config)", () => {
  test("all 7 filters are present, in order, with unique ids", () => {
    assert.equal(AF.FILTERS.length, 7);
    assert.deepEqual(AF.FILTERS.map((f) => f.id), [
      "filter-v1-m1", "filter-v1-m2", "filter-v1-m3", "filter-v1-m4",
      "filter-v1-m5", "filter-v1-m6", "filter-v1-m7",
    ]);
    // list() spans BOTH sets now -- ours lead. See the Moonglade describe below.
    assert.deepEqual(AF.list().slice(-7), AF.FILTERS.map((f) => f.id));
  });

  test("the baked data names where it came from, so a refresh is a copy-paste", () => {
    assert.match(AF.SOURCE_URL, /^https:\/\/api\.pixai\.art\/config\/imageArtFilters$/);
    assert.match(AF.CAPTURED, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(src, /imageArtFilters/,
      "the endpoint must be named in the file itself, not only in this test");
  });

  test("every layer carries a blend mode, an opacity in [0,1], and at least two stops", () => {
    AF.FILTERS.forEach((f) => {
      assert.ok(Array.isArray(f.filters) && f.filters.length >= 1, f.id + " has no layers");
      f.filters.forEach((L) => {
        assert.equal(typeof L.blendMode, "string", f.id + "/" + L.name + " blendMode");
        assert.ok(L.blendOpacity >= 0 && L.blendOpacity <= 1,
          f.id + "/" + L.name + " blendOpacity out of range: " + L.blendOpacity);
        assert.ok(L.stops.length >= 2, f.id + "/" + L.name + " needs >=2 stops for a gradient");
      });
    });
  });

  test("every stop colour is a recognised form and every position is in [0,1]", () => {
    AF.FILTERS.forEach((f) => f.filters.forEach((L) => L.stops.forEach((s) => {
      assert.match(s.color, /^(#[0-9a-fA-F]{3,8}|rgba?\([\d.,\s%]+\))$/,
        f.id + "/" + L.name + " unrecognised colour: " + s.color);
      assert.ok(s.position >= 0 && s.position <= 1,
        f.id + "/" + L.name + " stop position out of range: " + s.position);
    })));
  });

  test("the distinct blend modes in the data are exactly the 8 that are mapped", () => {
    const used = new Set();
    AF.FILTERS.forEach((f) => f.filters.forEach((L) => used.add(L.blendMode)));
    assert.deepEqual([...used].sort(), [...USED_MODES].sort());
  });

  test("image_parameters, where present, are small signed offsets (not multipliers)", () => {
    const withParams = AF.FILTERS.filter((f) => f.image_parameters);
    assert.equal(withParams.length, 4, "m4/m5/m6/m7 carry image_parameters; m1-m3 do not");
    withParams.forEach((f) => {
      ["brightness", "contrast", "saturation"].forEach((k) => {
        const v = f.image_parameters[k];
        assert.equal(typeof v, "number", f.id + "." + k);
        assert.ok(v > -1 && v < 1, f.id + "." + k + " looks like a multiplier, not an offset");
      });
    });
  });
});

// The five skins these are derived from, and where their palettes live. The default
// ("moonglade") is the `:root` block of DESIGN_TOKENS_CSS; the other four are
// `html[data-skin="..."]` overrides after it. Read straight out of the app so a retinted
// skin fails the cross-check below instead of quietly drifting from its filter.
const APP_PY = readFileSync(path.join(__dirname, "../../pixai_gallery.py"), "utf8");

function skinPalette(skin) {
  const start = skin === "moonglade"
    ? APP_PY.indexOf("DESIGN_TOKENS_CSS")
    : APP_PY.indexOf('html[data-skin="' + skin + '"]');
  assert.ok(start > -1, "no palette block in pixai_gallery.py for skin: " + skin);
  // To the end of that rule only -- `:root {` for the default, the `}` of the override
  // otherwise -- so one skin's colours can never satisfy another skin's filter.
  const open = APP_PY.indexOf("{", start);
  const body = APP_PY.slice(open + 1, APP_PY.indexOf("}", open));
  return new Set((body.match(/#[0-9a-fA-F]{6}\b/g) || []).map((h) => h.toLowerCase()));
}

describe("the Moonglade set (ours, derived from the skins)", () => {
  const MOON_IDS = ["mg-moonglade", "mg-nightfallen", "mg-moonlit", "mg-ember", "mg-verdant"];

  test("all 5 are present in order, and lead list() ahead of PixAI's", () => {
    assert.deepEqual(AF.MOONGLADE_FILTERS.map((f) => f.id), MOON_IDS);
    assert.deepEqual(AF.list(), MOON_IDS.concat(AF.FILTERS.map((f) => f.id)));
    assert.equal(new Set(AF.list()).size, AF.list().length, "duplicate filter id");
  });

  test("the two sets stay separate arrays -- FILTERS must remain a paste of the endpoint", () => {
    // The whole refresh story for FILTERS is "copy the endpoint's `filters` array over it".
    // One hand-written recipe in there and that stops being true, silently.
    const pixaiIds = new Set(AF.FILTERS.map((f) => f.id));
    MOON_IDS.forEach((id) => assert.ok(!pixaiIds.has(id), id + " leaked into FILTERS"));
    AF.FILTERS.forEach((f) => assert.match(f.id, /^filter-v1-m\d+$/));
    assert.equal(AF.FILTERS.length, 7);
  });

  test("groups() names both sets, ours first, and hands back ids rather than recipes", () => {
    const g = AF.groups();
    assert.deepEqual(g.map((x) => x.source), ["moonglade", "pixai"]);
    assert.deepEqual(g.map((x) => x.label), ["Moonglade", "PixAI"]);
    assert.deepEqual(g[0].ids, MOON_IDS);
    assert.deepEqual(g[1].ids, AF.FILTERS.map((f) => f.id));
    g[0].ids.push("mg-tamper");                       // a caller mutating what it got back...
    assert.deepEqual(AF.groups()[0].ids, MOON_IDS);   // ...must not reach the baked data
  });

  test("every layer carries a mode, an opacity in [0,1], and at least two stops", () => {
    AF.MOONGLADE_FILTERS.forEach((f) => {
      assert.ok(Array.isArray(f.filters) && f.filters.length >= 1, f.id + " has no layers");
      f.filters.forEach((L) => {
        assert.equal(typeof L.blendMode, "string", f.id + "/" + L.name + " blendMode");
        assert.ok(L.blendOpacity >= 0 && L.blendOpacity <= 1,
          f.id + "/" + L.name + " blendOpacity out of range: " + L.blendOpacity);
        assert.ok(L.stops.length >= 2, f.id + "/" + L.name + " needs >=2 stops for a gradient");
        L.stops.forEach((s) => {
          assert.match(s.color, /^#[0-9a-fA-F]{6}$/, f.id + "/" + L.name + ": " + s.color);
          assert.ok(s.position >= 0 && s.position <= 1, f.id + "/" + L.name + " stop position");
        });
      });
    });
  });

  test("ours use ONLY blend modes that map exactly -- preview and export are the same pixels", () => {
    // This is the promise the set was designed around, and the reason it does not reach for
    // darker-color/lighter-color the way PixAI's m1/m2/m5/m6 do: those two are Photoshop
    // whole-colour comparisons that CSS/canvas can only approximate, so a filter built on
    // them renders one way on screen and another in the saved PNG. Ours must never.
    AF.MOONGLADE_FILTERS.forEach((f) => f.filters.forEach((L) => {
      const e = AF.BLEND_MODE_MAP[L.blendMode];
      assert.ok(e, f.id + "/" + L.name + " uses an unmapped mode: " + L.blendMode);
      assert.equal(e.exact, true,
        f.id + "/" + L.name + " uses " + L.blendMode + ", which is APPROXIMATE. The " +
        "Moonglade set is exact-only so its export matches its preview.");
    }));
  });

  test("no image_parameters: what shipped is the recipe that was approved as swatches", () => {
    // The five were signed off from gradient-only swatches. A brightness/contrast trim added
    // afterwards would ship a filter nobody reviewed, and it would not be visible in a swatch.
    AF.MOONGLADE_FILTERS.forEach((f) => {
      assert.equal(f.image_parameters, undefined, f.id + " grew image_parameters");
      assert.equal(AF.imageAdjustCss(f.id), "", f.id + " emits an image adjustment");
    });
  });

  test("every recipe normalizes with nothing dropped", () => {
    AF.MOONGLADE_FILTERS.forEach((f) => {
      const n = AF.normalizeLayers(f.id);
      assert.deepEqual(n.warnings, [], f.id + " loses a layer or a stop");
      assert.equal(n.layers.length, f.filters.length, f.id + " layer count");
      n.layers.forEach((L) => assert.match(AF.gradientCss(L), /^linear-gradient\(180deg, #/));
    });
  });

  test("each names a real skin, one filter per skin, no skin twice", () => {
    const skins = AF.MOONGLADE_FILTERS.map((f) => f.skin);
    assert.deepEqual(skins, ["moonglade", "nightfallen", "moonlit", "ember", "verdant"]);
    assert.equal(new Set(skins).size, skins.length);
    AF.MOONGLADE_FILTERS.forEach((f) => {
      assert.ok(f.note && f.note.length > 10, f.id + " needs a one-line description");
    });
  });

  test("every colour is a real token of the skin the filter claims to come from", () => {
    // The cross-file pin. These are DERIVED, not invented: if a skin gets retinted in
    // pixai_gallery.py and its filter is left behind, the set stops being a matched set and
    // this fails by name instead of drifting quietly.
    AF.MOONGLADE_FILTERS.forEach((f) => {
      const palette = skinPalette(f.skin);
      f.filters.forEach((L) => L.stops.forEach((s) => {
        assert.ok(palette.has(s.color.toLowerCase()),
          f.id + "/" + L.name + ": " + s.color + " is not a token of the \"" + f.skin +
          "\" skin. Either it was hand-picked (it should not be) or that skin was " +
          "retinted and this filter needs to move with it.");
      }));
    });
  });
});

describe("blend-mode mapping (Photoshop names -> real CSS/canvas values)", () => {
  test("every mode the data uses maps to a value both renderers accept", () => {
    USED_MODES.forEach((m) => {
      const css = AF.blendModeFor(m, "css");
      const cv = AF.blendModeFor(m, "canvas");
      assert.ok(css, m + " has no CSS mapping");
      assert.ok(cv, m + " has no canvas mapping");
      assert.ok(CSS_BLEND_MODES.has(css), m + " -> " + css + " is not a real mix-blend-mode");
      assert.ok(CANVAS_OPS.has(cv), m + " -> " + cv + " is not a real globalCompositeOperation");
    });
  });

  test("nothing silently falls through to a no-op blend", () => {
    USED_MODES.forEach((m) => {
      assert.notEqual(AF.blendModeFor(m, "css"), "normal",
        m + " maps to `normal` -- that renders the layer as a flat gradient over the image, " +
        "which is not the filter at all. Map it or drop it, don't no-op it.");
      assert.notEqual(AF.blendModeFor(m, "canvas"), "source-over",
        m + " maps to `source-over`, canvas's no-op equivalent of `normal`");
    });
  });

  test("an unknown mode returns null, NOT a silent fallback", () => {
    assert.equal(AF.blendModeFor("linear-burn", "css"), null);
    assert.equal(AF.blendModeFor("linear-burn", "canvas"), null);
    assert.equal(AF.blendModeFor("", "css"), null);
    assert.equal(AF.blendModeFor(undefined, "canvas"), null);
  });

  test("exactly the two Photoshop-only whole-colour modes are flagged approximate", () => {
    const approx = Object.keys(AF.BLEND_MODE_MAP).filter((m) => !AF.BLEND_MODE_MAP[m].exact);
    assert.deepEqual(approx.sort(), ["darker-color", "lighter-color"]);
    approx.forEach((m) => {
      assert.ok(AF.BLEND_MODE_MAP[m].note && AF.BLEND_MODE_MAP[m].note.length > 20,
        m + " is approximate and must say WHY in its note, not just carry a flag");
    });
    assert.equal(AF.BLEND_MODE_MAP["darker-color"].css, "darken");
    assert.equal(AF.BLEND_MODE_MAP["lighter-color"].css, "lighten");
  });

  test("plus-lighter is exact but spelled differently per renderer", () => {
    assert.equal(AF.blendModeFor("plus-lighter", "css"), "plus-lighter");
    assert.equal(AF.blendModeFor("plus-lighter", "canvas"), "lighter");
    assert.equal(AF.BLEND_MODE_MAP["plus-lighter"].exact, true);
  });

  test("an unrecognised target is a caller error, not a guessed default", () => {
    assert.throws(() => AF.blendModeFor("screen", "webgl"), /target/i);
  });
});

describe("layer + stop normalization", () => {
  test("layers keep the recipe's declared order (first declared paints first)", () => {
    const n = AF.normalizeLayers("filter-v1-m2");
    assert.deepEqual(n.layers.map((L) => L.name), ["f1", "f2", "f3"]);
    assert.deepEqual(n.layers.map((L) => L.blendMode),
      ["darker-color", "color-burn", "lighter-color"]);
    assert.deepEqual(n.layers.map((L) => L.canvas), ["darken", "color-burn", "lighten"]);
  });

  test("stops are sorted ascending even when the payload declares them backwards", () => {
    // m1/f1 ships position 1 BEFORE position 0; m2/f3 ships 1 before 0 as well. A
    // linear-gradient with descending stops is invalid CSS (the browser clamps each stop
    // to the previous one, collapsing the gradient to a flat band), so sorting is not
    // cosmetic.
    const m1 = AF.normalizeLayers("filter-v1-m1").layers[0];
    assert.deepEqual(m1.stops.map((s) => s.position), [0, 1]);
    assert.equal(m1.stops[0].color, "#ffffff");
    const m2f3 = AF.normalizeLayers("filter-v1-m2").layers[2];
    assert.deepEqual(m2f3.stops.map((s) => s.position), [0, 1]);
    assert.equal(m2f3.stops[0].color, "rgba(111, 145, 186, 1)");
  });

  test("the sort is STABLE, so m6's two stops at position 1 keep their declared order", () => {
    // filter-v1-m6/f1 really does ship three stops at positions 1, 0.6, 1 -- two colours
    // land on the same offset. An unstable sort would swap #f4e4c1 and the navy and change
    // which one wins at the 100% end of the gradient.
    const f1 = AF.normalizeLayers("filter-v1-m6").layers[0];
    assert.deepEqual(f1.stops.map((s) => s.position), [0.6, 1, 1]);
    assert.deepEqual(f1.stops.map((s) => s.color),
      ["rgba(234, 118, 88, 1)", "#f4e4c1", "rgba(0, 17, 49, 1)"]);
  });

  test("a disabled layer is dropped, not drawn at zero opacity", () => {
    const recipe = {
      id: "x", filters: [
        { name: "a", enabled: false, blendMode: "screen", blendOpacity: 0.5, stops: [{ color: "#000", position: 0 }, { color: "#fff", position: 1 }] },
        { name: "b", enabled: true, blendMode: "overlay", blendOpacity: 0.5, stops: [{ color: "#000", position: 0 }, { color: "#fff", position: 1 }] },
      ],
    };
    const n = AF.normalizeLayers(recipe);
    assert.deepEqual(n.layers.map((L) => L.name), ["b"]);
  });

  test("a layer with an unmappable blend mode is DROPPED and reported, never normalised", () => {
    const recipe = {
      id: "x", filters: [
        { name: "bad", enabled: true, blendMode: "linear-burn", blendOpacity: 1, stops: [{ color: "#000", position: 0 }, { color: "#fff", position: 1 }] },
        { name: "ok", enabled: true, blendMode: "screen", blendOpacity: 1, stops: [{ color: "#000", position: 0 }, { color: "#fff", position: 1 }] },
      ],
    };
    const n = AF.normalizeLayers(recipe);
    assert.deepEqual(n.layers.map((L) => L.name), ["ok"]);
    assert.equal(n.warnings.length, 1);
    assert.match(n.warnings[0], /linear-burn/);
  });

  test("a stop colour that isn't a plain hex/rgb() literal is dropped, not interpolated", () => {
    // The recipes are baked, but normalizeLayers also accepts a freshly re-fetched payload,
    // and every stop colour ends up inside a CSS `linear-gradient(...)` string. Anything
    // that isn't a colour literal is a way into that string.
    const recipe = {
      id: "x", filters: [{
        name: "a", enabled: true, blendMode: "screen", blendOpacity: 1,
        stops: [
          { color: "#000000", position: 0 },
          { color: "red; } body{display:none} .x{color:blue", position: 0.5 },
          { color: "#ffffff", position: 1 },
        ],
      }],
    };
    const n = AF.normalizeLayers(recipe);
    assert.deepEqual(n.layers[0].stops.map((s) => s.color), ["#000000", "#ffffff"]);
    assert.ok(n.warnings.some((w) => /colour|color/i.test(w)));
  });

  test("strength scales every layer's opacity and clamps to [0,1]", () => {
    const full = AF.normalizeLayers("filter-v1-m1").layers.map((L) => L.opacity);
    assert.deepEqual(full, [0.9, 0.7]);
    assert.deepEqual(AF.normalizeLayers("filter-v1-m1", { strength: 0.5 }).layers.map((L) => L.opacity),
      [0.45, 0.35]);
    assert.deepEqual(AF.normalizeLayers("filter-v1-m1", { strength: 0 }).layers.map((L) => L.opacity),
      [0, 0]);
    // strength > 1 must not produce an opacity above 1 (CSS clamps silently; canvas
    // globalAlpha above 1 is ignored outright, so the two renderers would disagree)
    assert.deepEqual(AF.normalizeLayers("filter-v1-m1", { strength: 4 }).layers.map((L) => L.opacity),
      [1, 1]);
  });

  test("an unknown filter id is an error, not an empty no-op filter", () => {
    assert.equal(AF.get("filter-v1-m99"), null);
    assert.throws(() => AF.normalizeLayers("filter-v1-m99"), /filter-v1-m99/);
  });
});

describe("gradient + adjustment CSS", () => {
  test("gradientCss lists the stops ascending, as percentages, at the given angle", () => {
    const L = AF.normalizeLayers("filter-v1-m1").layers[0];
    assert.equal(AF.gradientCss(L),
      "linear-gradient(180deg, #ffffff 0%, rgba(215, 255, 223, 1) 100%)");
    assert.equal(AF.gradientCss(L, 90),
      "linear-gradient(90deg, #ffffff 0%, rgba(215, 255, 223, 1) 100%)");
  });

  test("the default gradient direction is top-to-bottom in BOTH renderers", () => {
    assert.equal(AF.DEFAULT_ANGLE_DEG, 180);
    assert.deepEqual(AF.gradientEndpoints(400, 200, 180), { x0: 200, y0: 0, x1: 200, y1: 200 });
  });

  test("gradientEndpoints follows CSS's gradient-line geometry, not just the four sides", () => {
    // 90deg is "to right", 0deg is "to top" -- the CSS convention, clockwise from up.
    assert.deepEqual(AF.gradientEndpoints(400, 200, 90), { x0: 0, y0: 100, x1: 400, y1: 100 });
    assert.deepEqual(AF.gradientEndpoints(400, 200, 0), { x0: 200, y0: 200, x1: 200, y1: 0 });
    // 45deg on a square: the gradient line runs corner to corner and its length is
    // |w*sin| + |h*cos|, so it overshoots the box's own diagonal -- getting this wrong is
    // how a canvas export ends up visibly different from the CSS preview. Compared with a
    // tolerance because an off-axis angle really does go through Math.sin/cos, whose result
    // lands a few 1e-14 off the whole pixel (and, on this one, yields -0 rather than 0).
    const near = (got, want) =>
      assert.ok(Math.abs(got - want) < 1e-6, "expected ~" + want + ", got " + got);
    const d = AF.gradientEndpoints(100, 100, 45);
    near(d.x0, 0);
    near(d.y0, 100);
    near(d.x1, 100);
    near(d.y1, 0);
  });

  test("image_parameters become filter offsets from 1, with no-ops omitted", () => {
    // m5: brightness +0.02, contrast -0.26, saturation +0.02
    assert.equal(AF.imageAdjustCss("filter-v1-m5"), "brightness(1.02) contrast(0.74) saturate(1.02)");
    // m6: brightness 0, contrast 0, saturation +0.12 -- the two zeroes are no-ops and must
    // not be emitted as brightness(1) contrast(1). A multiplier reading of these numbers
    // would emit brightness(0) here and render the image black.
    assert.equal(AF.imageAdjustCss("filter-v1-m6"), "saturate(1.12)");
    // m1 has no image_parameters at all
    assert.equal(AF.imageAdjustCss("filter-v1-m1"), "");
  });
});

describe("swatch layers", () => {
  test("the swatch is the recipe's own gradients, with the bottom one made opaque", () => {
    // The payload carries no swatch definition, so the tile is built from the recipe
    // itself. The bottom layer has to be forced opaque/normal or a 0.22-opacity first
    // layer (m5) renders as a nearly blank tile.
    const s = AF.swatchLayers("filter-v1-m5");
    assert.equal(s.length, 2);
    assert.equal(s[0].opacity, 1);
    assert.equal(s[0].css, "normal");
    assert.equal(s[1].opacity, 0.9);
    assert.equal(s[1].css, "soft-light");
  });

  test("every filter in BOTH sets produces a drawable swatch", () => {
    AF.FILTERS.concat(AF.MOONGLADE_FILTERS).forEach((f) => {
      const s = AF.swatchLayers(f.id);
      assert.ok(s.length >= 1, f.id + " has no swatch layers");
      s.forEach((L) => assert.match(AF.gradientCss(L), /^linear-gradient\(/));
    });
  });
});

// ---- the canvas/DOM half: no 2d context and no layout in this runner ----------------
describe("renderer wiring (source-presence: needs a real canvas/layout to exercise)", () => {
  test("the module never reaches the network -- it must work with no connection", () => {
    assert.doesNotMatch(src, /\bfetch\s*\(/, "art filters cost nothing and need no network");
    assert.doesNotMatch(src, /XMLHttpRequest|EventSource|WebSocket|navigator\.sendBeacon/);
    assert.doesNotMatch(src, /\bimport\s*\(/);
  });

  test("composite() drives globalCompositeOperation from the canvas mapping and resets it", () => {
    assert.match(src, /ctx\.globalCompositeOperation = L\.canvas;/,
      "the canvas path must use the mapped canvas op, not the raw PixAI blendMode name");
    assert.match(src, /ctx\.globalAlpha = L\.opacity;/);
    // Leaving a blend op or a partial alpha set on a context that a caller reuses is a
    // classic canvas footgun -- both must be put back.
    assert.match(src, /ctx\.globalCompositeOperation = 'source-over';/);
    assert.match(src, /ctx\.globalAlpha = 1;/);
  });

  test("the CSS preview isolates its stacking context so it blends the image, not the page", () => {
    // Without `isolation:isolate` on the stage, mix-blend-mode blends against whatever is
    // painted behind the container too, so the same filter looks different depending on
    // the page background it is mounted over.
    assert.match(src, /isolation:isolate/);
    // Set through the CSSOM property, so the string in the source is the camelCase name.
    assert.match(src, /\.style\.mixBlendMode = L\.css;/,
      "each overlay div must carry its layer's MAPPED css mode, not the raw PixAI name");
  });

  test("export goes through the canvas path and offers both a dataURL and a blob", () => {
    assert.match(src, /function composite\(/);
    assert.match(src, /toDataURL/);
    assert.match(src, /toBlob/);
  });

  test("the module is a plain global with no build step, like its sibling components", () => {
    assert.match(src, /window\.MgArtFilters = /);
    assert.doesNotMatch(src, /^\s*(export|import)\s/m);
  });
});
