import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  RATIOS, ratioLabel, ratioAspect, ratioIndexOf, tierDims, autoDims, accountSizeRule,
  effectiveTier, tierLocked, deadRefs, renumberAfterRemove, heldItems, confirmTitle,
  needsSwitchConfirm, effectiveCreativity, profileExtra, profileLocked, profilePicked,
  onContextSide, contextMax, DEAD_REF, SEED_PROMPT,
} from "../../gallery/src/gen/tsubakiCore.js";
import {
  GEN_DEFAULTS, buildPayload, goGate, sizeInfo, imageRefs, tsubakiEditState, versionPatch,
} from "../../gallery/src/gen/genCore.js";
import { prefsFromState, stateFromPrefs, prefsMode } from "../../gallery/src/gen/genPrefs.js";

/* Session H -- Tsubaki.3 in the Generate drawer, the client's pure half (gen/tsubakiCore.js,
   gen/genPrefs.js and what genCore builds on them). The server half is
   dev/tests/test_tsubaki3_generate.py; the spend design is moonglade-internal/design/notes/
   tsubaki3-generate/BUILD-w2-gen.md. */

// /api/model-version's size_tiers for Tsubaki.3 (auth/T3v_size-config.json's M row in full,
// XL / L with a subset of their grid).
const M = { name: "M", min: 512, max: 1800, step: 16, required_tier: 0, access: "available",
  default: [768, 1280], presets: [
    { ratio: "3:5", width: 768, height: 1280 }, { ratio: "1:1", width: 992, height: 992 },
    { ratio: "9:16", width: 720, height: 1280 }, { ratio: "3:4", width: 864, height: 1152 },
    { ratio: "2:3", width: 816, height: 1232 }, { ratio: "7:9", width: 880, height: 1136 },
    { ratio: "1:3", width: 576, height: 1744 }] };
const XL = { name: "XL", min: 512, max: 2496, step: 16, required_tier: 0, access: "available",
  default: [1104, 1824], presets: [{ ratio: "3:5", width: 1104, height: 1824 },
    { ratio: "1:1", width: 1408, height: 1408 }] };
const L = { name: "L", min: 512, max: 2200, step: 16, required_tier: 1, access: "available",
  default: [944, 1584], presets: [{ ratio: "3:5", width: 944, height: 1584 }] };
const T3 = {
  version_id: "2024383379556065549", model_id: "2024383378759147749", title: "Tsubaki.3",
  context_images: true, creativity: true, context_max: 3,
  size_rule: { step: 16, lo: 512, hi: 2496 }, size_tiers: [XL, L, M],
  profile_rows: [
    { name: "pro", title: "Pro", base_price: 3000, flag: "default", required_tier: 0 },
    { name: "ultra", title: "Ultra", base_price: 3500, flag: "membershipOnly", required_tier: 1 },
  ],
};
const idx = (a, b) => RATIOS.findIndex(([x, y]) => x === a && y === b);

describe("decision 7 -- eleven ratios, one Portrait | Landscape switch", () => {
  test("the set, its labels and the orientation flip", () => {
    assert.deepEqual(RATIOS.map(([a, b]) => a + ":" + b),
      ["1:1", "5:4", "9:7", "4:3", "3:2", "5:3", "16:9", "2:1", "21:9", "3:1", "4:1"]);
    assert.equal(ratioLabel(idx(16, 9), false), "9:16");
    assert.equal(ratioLabel(idx(16, 9), true), "16:9");
    assert.equal(ratioLabel(0, true), "1:1");
    assert.equal(ratioAspect(idx(4, 1), false), 0.25);
    assert.equal(ratioIndexOf(9 / 16), idx(16, 9));
    assert.equal(ratioIndexOf(7 / 9), idx(9, 7));
    assert.equal(ratioIndexOf(1.2345), -1);
  });
});

describe("decisions 6 + 7 -- the tier sizes", () => {
  test("PixAI's own grid wins where it has the ratio (note 7's M row, exactly)", () => {
    const got = (a, b, land) => { const d = tierDims(T3, M, idx(a, b), land); return [d.width, d.height]; };
    assert.deepEqual(got(5, 3, false), [768, 1280]);
    assert.deepEqual(got(1, 1, false), [992, 992]);
    assert.deepEqual(got(16, 9, false), [720, 1280]);
    assert.deepEqual(got(4, 3, true), [1152, 864]);
    assert.deepEqual(got(5, 3, true), [1280, 768]);
    assert.deepEqual(got(16, 9, true), [1280, 720]);
    assert.equal(tierDims(T3, M, idx(3, 1), false).grid, true);
  });

  test("a ratio off the grid follows the area rule; a short edge under 512 holds", () => {
    const two = tierDims(T3, M, idx(2, 1), true);
    assert.deepEqual([two.width, two.height, two.held], [1408, 704, false]);
    const four = tierDims(T3, M, idx(4, 1), true);
    assert.deepEqual([four.width, four.height, four.held], [2048, 512, true]);
    const fourXL = tierDims(T3, XL, idx(4, 1), false);
    assert.deepEqual([fourXL.width, fourXL.height, fourXL.held], [624, 2496, false]);
    for (const [a, b] of RATIOS) {
      for (const t of [XL, L, M]) {
        const d = tierDims(T3, t, idx(a, b), false);
        assert.equal(d.width % 16, 0);
        assert.equal(d.height % 16, 0);
        assert.ok(Math.min(d.width, d.height) >= 512, a + ":" + b + " " + t.name);
        assert.ok(Math.max(d.width, d.height) <= 2496, a + ":" + b + " " + t.name);
      }
    }
  });

  test("Auto takes image 1's own aspect on the tier in force", () => {
    assert.deepEqual(autoDims(T3, XL, { w: 1216, h: 832 }), { width: 1712, height: 1168, held: false });
    assert.deepEqual(autoDims(T3, M, { w: 1000, h: 1000 }), { width: 992, height: 992, held: false });
    assert.equal(autoDims(T3, M, { w: 0, h: 832 }), null);
    const s = { ...GEN_DEFAULTS, model: T3, inputs: "context", tier: "XL",
      ctx: [{ media_id: "701", w: 1216, h: 832 }] };
    assert.deepEqual(sizeInfo(s).source, "auto");
    assert.deepEqual([sizeInfo(s).width, sizeInfo(s).height], [1712, 1168]);
    // picking a ratio leaves Auto
    assert.equal(sizeInfo({ ...s, auto: false, aspect: 1 }).source, "tier");
    // Auto without the picture's size falls back to the ratio on the tier
    assert.equal(sizeInfo({ ...s, ctx: [{ media_id: "701" }] }).source, "tier");
  });

  test("members-only tiers: locked only for an explicit non-member; the custom limit follows", () => {
    assert.equal(tierLocked(L, false), true);
    assert.equal(tierLocked(L, true), false);
    assert.equal(tierLocked(L, null), false, "unknown membership fails open");
    assert.equal(effectiveTier(T3, "L", false).name, "XL");
    assert.equal(effectiveTier(T3, "L", true).name, "L");
    assert.equal(effectiveTier(T3, "", true).name, "XL", "the model's own default");
    const locked = { ...T3, size_tiers: [{ ...XL, required_tier: 1 }, M] };
    assert.deepEqual(accountSizeRule(locked, false), { step: 16, lo: 512, hi: 1792 });
    assert.deepEqual(accountSizeRule(locked, true), { step: 16, lo: 512, hi: 2496 });
    const s = { ...GEN_DEFAULTS, model: locked, member: false, customW: "3000", customH: "3000" };
    assert.deepEqual([sizeInfo(s).width, sizeInfo(s).height], [1792, 1792]);
  });
});

describe("decision 1 -- the switch, what it holds, the confirm", () => {
  test("the Context side is live only on a context-image model", () => {
    assert.equal(onContextSide({ inputs: "context", model: T3 }), true);
    assert.equal(onContextSide({ inputs: "context", model: { ...T3, context_images: false } }), false);
    assert.equal(contextMax(T3), 3);
    assert.equal(contextMax({}), 3);
  });

  test("held items and the confirm card's title", () => {
    const s = { ...GEN_DEFAULTS, loras: [{ model_id: "L" }], negative: "lowres", recipes: [{ id: "1" }] };
    assert.deepEqual(heldItems(s), ["lora", "recipe", "negative"]);
    assert.equal(confirmTitle(heldItems(s)), "Switching holds your LoRA");
    assert.equal(confirmTitle(["negative"]), "Switching holds your negative prompt");
    assert.equal(needsSwitchConfirm(s), true);
    assert.equal(needsSwitchConfirm({ ...s, ctxWarned: true }), false);
    assert.equal(needsSwitchConfirm(GEN_DEFAULTS), false);
  });

  test("the Context side sends its images and holds the rest; the LoRA side never sends images", () => {
    const base = { ...GEN_DEFAULTS, model: T3, prompt: "Use @image2 with @image1", negative: "neg",
      loras: [{ model_id: "L", version_id: "LV", weight: 0.7 }], unlimited: true,
      recipes: [{ id: "2046394714775712134", title: "R", cover: "" }], creativity: "off",
      ctx: [{ media_id: "701", w: 1216, h: 832 }, { media_id: "702" }] };
    const lora = buildPayload(base);
    assert.equal(lora.context_images, undefined);
    assert.deepEqual(lora.recipeIds, ["2046394714775712134"]);
    assert.equal(lora.unlimited, true);
    assert.equal(lora.negative, "neg");
    assert.equal(lora.creativity, "off");
    assert.equal(lora.prompt_helper, false);
    assert.deepEqual(lora.loras, [{ version_id: "LV", weight: 0.7 }]);
    const ctx = buildPayload({ ...base, inputs: "context" });
    assert.deepEqual(ctx.context_images, ["701", "702"]);
    assert.deepEqual(ctx.image_refs, [1, 2]);
    assert.deepEqual(ctx.loras, []);
    assert.equal(ctx.negative, "");
    assert.equal(ctx.unlimited, undefined);
    assert.equal(ctx.recipeIds, undefined);
    assert.equal(ctx.creativity, "medium", "set by context images");
    assert.equal(ctx.ref_media_id, null);
    assert.equal(effectiveCreativity({ ...base, inputs: "context" }), "medium");
    // a model without the creativity meta sends the on/off helper only
    const legacy = buildPayload({ ...base, model: { ...T3, creativity: false } });
    assert.equal(legacy.creativity, undefined);
    assert.equal(legacy.prompt_helper, true);
  });

  test("the Go gate on the Context side", () => {
    const s = { ...GEN_DEFAULTS, model: T3, inputs: "context", prompt: "Use @image1",
      loras: [{ model_id: "L", failed: true }] };
    assert.match(goGate(s, 3), /Add a context image/);
    const one = { ...s, ctx: [{ media_id: "701" }] };
    assert.equal(goGate(one, 0), null, "held LoRAs are not judged (not sent)");
    assert.match(goGate({ ...one, prompt: "Use @image2" }, 3), /@image2 has no image/);
    assert.match(goGate({ ...one, prompt: "Use " + DEAD_REF }, 3), /removed image/);
    assert.match(goGate({ ...one, ctx: [1, 2, 3, 4].map((n) => ({ media_id: String(n) })), prompt: "p" }, 3),
      /up to 3 context images — remove 1/);
    // a lane rule never blocks the Context side (the lane is not sent there)
    assert.equal(goGate({ ...one, unlimited: true, customW: "2400", customH: "2400" }, 3), null);
  });
});

describe("decision 2 -- the @image grammar", () => {
  test("dead refs and renumbering after a slot is removed", () => {
    assert.deepEqual(deadRefs("@image1 @image3 @image0", 2), ["@image3", "@image0"]);
    // Flipped on the owner walk 2026-09-29: removing a slot used to write @image0 into the
    // prompt. A ref to the removed picture now keeps naming no picture on a real number: the
    // old last one, which nothing moved into -- and pictures past it follow their slot down.
    assert.equal(renumberAfterRemove("Use @image1 as face, @image2 pose, @image3 bg", 0, 3),
      "Use @image3 as face, @image1 pose, @image2 bg");
    assert.equal(renumberAfterRemove("a @image1 b @image2", 1, 2), "a @image1 b @image2",
      "removing the last slot leaves its ref exactly as typed");
    assert.equal(renumberAfterRemove("@image12 moves", 0, 12), "@image11 moves");
    assert.deepEqual(imageRefs("@image2 x @image1 @image2"), [1, 2]);
    assert.equal(SEED_PROMPT, "Use @image1 ");
  });

  test("the owner's walk: one image, removed, never leaves @image0 or any index under 1", () => {
    // Screenshot 13: one context image, prompt "@image1 holding flowers beside @image2"; its ✕
    // then back to LoRAs showed "@image0 holding flowers beside @image1".
    const before = "@image1 holding flowers beside @image2";
    const after = renumberAfterRemove(before, 0, 1);
    assert.equal(after, before, "the removed picture's ref stays as written; @image2 already named no picture");
    assert.deepEqual(deadRefs(after, 0), ["@image1", "@image2"], "both read as the peach 'no image' chip");
    for (const [p, k, n] of [[before, 0, 1], ["@image1 @image2 @image3", 0, 3], ["@image1 @image2 @image3", 1, 3],
      ["@image1 @image2 @image3", 2, 3], ["x @image1", 0, undefined]]) {
      const out = renumberAfterRemove(p, k, n);
      assert.ok(!/@image0\b/.test(out), p + " -> " + out);
      assert.ok(imageRefs(out).every((i) => i >= 1), p + " -> " + out);
    }
    // a ref to the removed picture can never turn into the picture that slid into its place
    const two = renumberAfterRemove("@image1 hugs @image2", 0, 2);
    assert.equal(two, "@image2 hugs @image1");
    assert.deepEqual(deadRefs(two, 1), ["@image2"], "the removed one is dead; the kept one follows its picture");
  });
});

describe("T1a -- the profile rows", () => {
  test("price, lock and pick", () => {
    const [pro, ultra] = T3.profile_rows;
    assert.equal(profileExtra(ultra, T3.profile_rows), 500);
    assert.equal(profileExtra(pro, T3.profile_rows), 0);
    assert.equal(profileLocked(ultra, false), true);
    assert.equal(profileLocked(ultra, null), false);
    assert.equal(profilePicked(pro, T3.profile_rows, "auto"), true);
    assert.equal(profilePicked(ultra, T3.profile_rows, "ultra"), true);
    const s = { ...GEN_DEFAULTS, model: T3, prompt: "p", mode: "ultra", member: false };
    assert.match(goGate(s, 3), /Ultra is for PixAI members/);
    assert.equal(goGate({ ...s, member: true }, 3), null);
  });

  test("versionPatch carries the Session H meta and drops what a row does not carry", () => {
    const v = versionPatch({ size_tiers: [M], context_max: 3, creativity: true,
      profile_rows: T3.profile_rows, context_images: true });
    assert.deepEqual(v.size_tiers, [M]);
    assert.equal(v.context_max, 3);
    assert.equal(v.creativity, true);
    const bare = versionPatch({});
    assert.equal(bare.size_tiers, null);
    assert.equal(bare.context_max, null);
    assert.equal(bare.creativity, false);
    assert.equal(bare.profile_rows, null);
  });
});

describe("T3a -- the Lightbox edit bar's payload is the dock's buildPayload", () => {
  test("Tsubaki.3, the picture as @image1, Auto, count 1, nothing else of the dock", () => {
    const st = tsubakiEditState({ model: T3, image: { media_id: "701", w: 1216, h: 832 },
      prompt: "make it night", mode: "ultra", tier: "XL", member: true });
    const p = buildPayload(st);
    assert.equal(p.version_id, T3.version_id);
    assert.equal(p.model_id, T3.model_id);
    assert.deepEqual(p.context_images, ["701"]);
    assert.equal(p.prompt, "make it night");
    // the SOURCE picture's own size, as PixAI's own Smart Reference submit sends (2026-10-03)
    assert.deepEqual([p.width, p.height], [1216, 832]);
    assert.equal(p.mode, "ultra");
    assert.equal(p.count, 1);
    assert.equal(p.high_priority, true);          // the bar runs at High Priority (2026-10-03)
    assert.deepEqual(p.loras, []);
    assert.equal(p.negative, "");
    assert.equal(p.recipeIds, undefined);
    assert.equal(p.unlimited, undefined);
    assert.equal(p.creativity, "medium");
    assert.equal(p.face_fix, false);
    assert.equal(p.quality_tag, null);
    assert.equal(p.upscale, null);
    assert.equal(p.seed, null);
  });
});

describe("T3a -- the bar sends the request PixAI's own site sends (2026-10-03 capture)", () => {
  /* The site's Smart Reference submit for the same edit, captured live: width and height are the
     source picture's own (1280 x 768), one picture, Pro, creativity medium, the picture as the one
     context image. The server half (controlNets [], no batchSize at one) is
     dev/tests/test_tsubaki3_generate.py::test_the_edit_bar_request_is_the_sites_smart_reference_shape. */
  const bar = (img) => buildPayload(tsubakiEditState({ model: T3, image: img, prompt: "make it night",
    mode: "pro", tier: "XL", member: true }));
  test("a 1280 x 768 source: these keys, these values", () => {
    const p = bar({ media_id: "701", w: 1280, h: 768 });
    assert.deepEqual(Object.keys(p).sort(), ["cfg", "context_images", "count", "creativity", "face_fix",
      "height", "high_priority", "image_refs", "loras", "mode", "model_id", "negative", "prompt",
      "prompt_helper", "quality_tag", "ref_media_id", "ref_strength", "seed", "steps", "upscale",
      "upscale_denoise", "upscale_denoise_steps", "version_id", "width"]);
    assert.deepEqual([p.width, p.height], [1280, 768]);
    assert.deepEqual(p.context_images, ["701"]);
    assert.equal(p.count, 1);
    assert.equal(p.mode, "pro");
    assert.equal(p.creativity, "medium");
    assert.equal(p.negative, "");
    assert.deepEqual(p.loras, []);
  });
  /* Review of 2026-10-03: the source's own size is used ONLY when both sides are at most 2048 (the
     logged-in site's Tsubaki.3 model-config, PROBE_2026-09-26_site) AND its area is within the tier's
     default area (PixAI's largest presets are about 2 MP). Anything bigger -- an upscale, a 4K
     picture -- goes back to Auto, the size the bar sent before. */
  const auto = (img) => buildPayload({ ...tsubakiEditState({ model: T3, image: img, prompt: "make it night",
    mode: "pro", tier: "XL", member: true }), customW: "", customH: "" });
  const wh = (p) => [p.width, p.height];
  const XL_AREA = XL.default[0] * XL.default[1];
  test("a small source keeps its own size, put on the model's 16 px steps", () => {
    assert.deepEqual(wh(bar({ media_id: "1", w: 1000, h: 600 })), [1008, 608]);
    assert.deepEqual(wh(bar({ media_id: "5", w: 1216, h: 832 })), [1216, 832]);
    const small = bar({ media_id: "3", w: 300, h: 200 });
    assert.ok(small.width >= T3.size_rule.lo && small.height >= T3.size_rule.lo, JSON.stringify(small));
  });
  for (const [w, h] of [[2560, 2560], [4096, 2304], [2048, 3072], [2048, 1152]]) {
    test("a " + w + " x " + h + " source goes back to Auto, never past 2048 a side or the tier's area", () => {
      const img = { media_id: "9", w, h };
      const p = bar(img);
      assert.deepEqual(wh(p), wh(auto(img)));
      assert.ok(p.width <= 2048 && p.height <= 2048, JSON.stringify(wh(p)));
      assert.ok(p.width * p.height <= XL_AREA * 1.02, JSON.stringify(wh(p)));
    });
  }
  test("the edges: 2048 a side and the tier's own area are still the source's size", () => {
    assert.deepEqual(wh(bar({ media_id: "6", w: 2048, h: 976 })), [2048, 976]);
    assert.deepEqual(wh(bar({ media_id: "7", w: 1104, h: 1824 })), [1104, 1824]);
  });
});

describe("T3a -- the bar runs at High Priority (owner's call, 2026-10-03)", () => {
  /* PixAI's free Turbo lane was not starting context-image edits; his site edits that worked ran at
     High Priority (a card covered one whole, extra included). The bar sends high_priority, and the
     quote is built from the same payload, so the shown cost is the spend. The server half is
     dev/tests/test_tsubaki3_generate.py (priority 1000 sent and quoted, card and no card). */
  const st = () => tsubakiEditState({ model: T3, image: { media_id: "701", w: 1280, h: 768 },
    prompt: "make it night", mode: "pro", tier: "XL", member: true });
  test("the bar's payload asks for High Priority", () => {
    assert.equal(st().highPriority, true);
    assert.equal(buildPayload(st()).high_priority, true);
  });
  test("and never the Unlimited lane, whose runs refuse High Priority", () => {
    const p = buildPayload({ ...st(), unlimited: true });
    assert.equal("unlimited" in p, false);
    assert.equal(buildPayload(st()).unlimited, undefined);
  });
  test("nothing else changes: the dock's default stays off", () => {
    assert.equal(GEN_DEFAULTS.highPriority, false);
    assert.equal(buildPayload({ ...GEN_DEFAULTS, model: T3, prompt: "p" }).high_priority, false);
  });
});

describe("the settings that follow the account (gen.image)", () => {
  test("round trip, and what comes back is checked", () => {
    const s = { ...GEN_DEFAULTS, creativity: "low", tier: "L", aspect: 16 / 9, landscape: true,
      auto: false, mode: "ultra", recipes: [{ id: "12", title: "R", cover: "/c.jpg", extra: 1 }] };
    const back = stateFromPrefs(JSON.parse(JSON.stringify(prefsFromState(s))));
    assert.deepEqual(back, { creativity: "low", tier: "L", aspect: 16 / 9, landscape: true,
      auto: false, mode: "ultra", recipes: [{ id: "12", title: "R", cover: "/c.jpg" }] });
    assert.deepEqual(stateFromPrefs({ creativity: "max", tier: "<x>", aspect: 99, mode: "turbo",
      recipes: [{ id: "abc" }], auto: "yes" }), { recipes: [] });
    assert.deepEqual(stateFromPrefs(null), {});
    assert.equal(prefsMode({ mode: "pro" }), "pro");
    assert.equal(prefsMode(undefined), "auto");
  });
});
