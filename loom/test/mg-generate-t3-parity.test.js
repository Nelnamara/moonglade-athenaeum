import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  ASPECTS, SIZES, GEN_DEFAULTS, adjustedText, buildPayload, dims, qualityTagTitle,
  refIsContext, snapSize,
} from "../../gallery/src/gen/genCore.js";
import {
  buildImgGenBody, genStepFor, resolveGenDims, snap8, snapStep,
} from "../src/loom-mutations.js";

/* SCOPE_2026-09-26 lane G, the client half: the Generate drawer shows -- and sends -- what the
   server's per-model gate will send (moonglade_backup._gate_image_params), and the Loom snaps
   to the model's grid. The Python side, and the JS/Python parity over all 32 presets, is
   tests/test_tsubaki3_image_gate.py; this file pins the JS logic directly. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.resolve(__dirname, rel), "utf8").replace(/\r\n/g, "\n");

const T3_RULE = { step: 16, lo: 512, hi: 2496 };
const at = (label) => ASPECTS.find(([l]) => l === label)[1];

describe("G1 -- dims() applies the model's size rule", () => {
  test("the nine failing presets snap; the other 23 do not move", () => {
    const expected = {
      "2:3@1024": [688, 1024], "3:2@1024": [1024, 688],
      "2:3@2048": [1376, 2048], "3:2@2048": [2048, 1376],
      "9:16@768": [512, 912], "16:9@768": [912, 512],
      "3:1@768": [1536, 512], "3:1@1024": [1520, 512], "3:1@2048": [2048, 688],
    };
    const moved = {};
    for (const [label, r] of ASPECTS) {
      for (const size of SIZES) {
        const raw = dims({ aspect: r, size });
        const got = dims({ aspect: r, size, model: { size_rule: T3_RULE } });
        if (raw.width !== got.width || raw.height !== got.height) {
          moved[label + "@" + size] = [got.width, got.height];
        }
      }
    }
    assert.deepEqual(moved, expected);
  });

  test("on-grid sizes pass untouched; 768×432 -> 912×512; no rule = today's /8", () => {
    for (const [w, h] of [[2048, 1152], [816, 2448], [1088, 1824]]) {
      assert.deepEqual(snapSize(w, h, T3_RULE), { width: w, height: h });
    }
    assert.deepEqual(snapSize(768, 432, T3_RULE), { width: 912, height: 512 });
    assert.deepEqual(dims({ aspect: at("16:9"), size: 768 }), { width: 768, height: 432 });
    assert.deepEqual(snapSize(1001, 7, null), { width: 1001, height: 7 });
    // custom W×H rides the same rule
    assert.deepEqual(dims({ customW: "768", customH: "432", model: { size_rule: T3_RULE } }),
      { width: 912, height: 512 });
  });

  test("rounding is half-up, like the server's floor(x/step + 0.5)", () => {
    assert.deepEqual(snapSize(1024, 680, T3_RULE), { width: 1024, height: 688 });
    assert.deepEqual(snapSize(1016, 1016, { step: 16, lo: 64, hi: 4096 }),
      { width: 1024, height: 1024 });
  });
});

describe("G2/G3/G4 -- buildPayload withholds what the drawer shows as not applying", () => {
  const base = () => ({
    ...GEN_DEFAULTS, prompt: "p", negative: "<negative>",
    boosters: { hires: false, quality: true, face: true },
  });

  test("face_fix / quality_tag / negative follow their compat flags; chip state is kept", () => {
    const s = { ...base(), model: { version_id: "V", model_id: "M",
      compat_face: false, compat_quality: false, compat_neg: false } };
    const p = buildPayload(s);
    assert.equal(p.face_fix, false);
    assert.equal(p.quality_tag, null);
    assert.equal(p.negative, "");
    assert.equal(s.boosters.face, true, "the chip keeps its state");
    assert.equal(s.negative, "<negative>", "typed text stays in the box, unsent");
    const open = buildPayload({ ...base(), model: { version_id: "V", model_id: "M" } });
    assert.equal(open.face_fix, true);
    assert.equal(open.quality_tag, "Masterpiece");
    assert.equal(open.negative, "<negative>");
  });

  test("a reference on a context-image model sends no negative", () => {
    const m = { version_id: "V", model_id: "M", context_images: true };
    const s = { ...base(), model: m, ref: { media_id: "M1" } };
    assert.equal(refIsContext(s), true);
    assert.equal(buildPayload(s).negative, "");
    assert.equal(buildPayload(s).ref_media_id, "M1");
    assert.equal(refIsContext({ ...s, ref: null }), false);
    assert.equal(refIsContext({ ...s, model: { ...m, context_images: false } }), false);
  });

  test("the Quality Tag tooltip reads from the version's own tag", () => {
    assert.match(qualityTagTitle({ quality_tag: { prefix: "", suffix: "<sfx>" } }), /after: <sfx>/);
    assert.match(qualityTagTitle({ compat_quality: false }), /publishes no quality tag/);
    assert.doesNotMatch(qualityTagTitle(null), /Masterpiece/);
  });
});

describe("receipts -- used:null reads 'off'", () => {
  test("adjustedText", () => {
    assert.equal(adjustedText([{ field: "width", asked: 768, used: 912 },
                               { field: "negativePrompts", asked: "x".repeat(40), used: null }]),
      "width 768→912, negativePrompts " + "x".repeat(23) + "…→off");
    assert.equal(adjustedText(undefined), "");
  });

  test("submitTask and CostBadge both render it (the badge in its note line, before a spend)", () => {
    const sub = read("../../gallery/src/gen/submitTask.js");
    assert.match(sub, /const adj = adjustedText\(d\.adjusted\);/);
    const badge = read("../../gallery/src/components/CostBadge.jsx");
    assert.match(badge, /adjustedText\(d\.adjusted\)/);
    // In the EXISTING note line, never a line of its own (review F5): the block form's one
    // mgc-sub note carries it (after the expiry / card-short note, or in the empty slot), and
    // the stack form's second line carries it before the balance.
    assert.match(badge, /sub \? \{ text: sub\.text \+ " · " \+ adj, title: sub\.title \+ " · " \+ adj/);
    assert.match(badge, /: \{ text: adj, title: adj, days: null \}\)/);
    assert.match(badge, /\{m\.noteLine \? <span className="mgc-sub" title=\{m\.noteLine\.title\}>\{m\.noteLine\.text\}<\/span> : null\}/);
    assert.match(badge, /if \(adj\) parts\.push\(adj\);[^\n]*\n\s*if \(balanceN != null\) parts\.push/);
    assert.doesNotMatch(badge, /\{m\.adj \?/, "no sibling span for the receipt");
    assert.equal((badge.match(/className="mgc-sub"/g) || []).length, 3,
      "the chip's, the stack's card-short and the block form's note -- no fourth");
  });
});

describe("the drawer wiring (source reads -- no React harness in this runner)", () => {
  const drawer = read("../../gallery/src/components/GenerateDrawer.jsx");
  const phone = read("../../gallery/src/components/CreateMobile.jsx");
  const hook = read("../../gallery/src/gen/useGenerate.js");

  test("STRENGTH and the negative box read disabled while a ref is a context image", () => {
    assert.match(drawer, /disabled=\{refIsContext\(s\)\}/);
    assert.match(drawer, /disabled=\{\(m && m\.compat_neg === false\) \|\| refIsContext\(s\)\}/);
    assert.match(phone, /disabled=\{\(m && m\.compat_neg === false\) \|\| refIsContext\(s\)\}/);
  });

  test("the version fields ride every apply, explicitly", () => {
    for (const f of ["compat_face:", "compat_quality:", "quality_tag:", "size_rule:", "context_images:"]) {
      assert.ok(hook.includes(f), f);
    }
  });
});

describe("G1 -- the Loom snaps to the model's grid", () => {
  test("snapStep(n, 8) is snap8(n); DiT families take 16", () => {
    for (const n of [0, 7, 64, 432, 1001, 1007, 5000, NaN, undefined, -3]) {
      assert.equal(snapStep(n, 8), snap8(n), String(n));
    }
    for (const t of ["DIT7_MODEL", "DIT7B_MODEL", "MMDIT26A_MODEL", "MMDIT26B_MODEL",
      "USER_DIT26A_MODEL", "USER_DIT26B_MODEL"]) {
      assert.equal(genStepFor(t), 16, t);
    }
    assert.equal(genStepFor("SDXL_MODEL"), 8);
    assert.equal(genStepFor(""), 8);
    assert.equal(snapStep(680, 16), 688);
  });

  test("resolveGenDims takes the step (default 8, unchanged) and buildImgGenBody passes it", () => {
    const adv = { aspectW: 2, aspectH: 3, size: 1024 };
    assert.deepEqual(resolveGenDims(adv), { w: 680, h: 1024, custom: false });
    assert.deepEqual(resolveGenDims(adv, 16), { w: 688, h: 1024, custom: false });
    const t3 = buildImgGenBody({ model_id: "M", model_type: "MMDIT26B_MODEL" }, [], adv, "p");
    assert.equal(t3.width, 688);
    const sdxl = buildImgGenBody({ model_id: "M", model_type: "SDXL_MODEL" }, [], adv, "p");
    assert.equal(sdxl.width, 680);
  });

  test("both readouts pass the same step", () => {
    const sb = read("../master-storyboard.jsx");
    const n = (sb.match(/resolveGenDims\(imgAdv, genStepFor\(imgModel && imgModel\.model_type\)\)/g) || []).length;
    assert.equal(n, 2);
    assert.ok(!/resolveGenDims\(imgAdv\)/.test(sb), "no readout left on the bare /8 grid");
  });
});
