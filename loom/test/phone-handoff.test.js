import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  REMIX_NOTE, VIDEO_NOTE, isTemplateRun, remixImageInto, remixPatch, remixVideoInto, sendStartFrame,
  startFramePrefill,
} from "../../gallery/src/gen/phoneRemix.js";

/* Session Q, Q2: Remix and Send to Video on the phone OPEN the Create tab filled in and NEVER SEND.
   The behaviour half: which prompt a remix restores, what it reads, what it sets. The structural half
   (below) is the proof the brief asks for: no generate / price / submit call is reachable from the
   handoff code. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const read = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");
const codeOnly = (t) => t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

const ROW = {
  media_id: "700", task_id: "9001", model_id: "ver-7", model_name: "Probe Model", loras: "moonlit:0.7",
  prompt_full: "a {braced} scene, __list__ and plain", negative_prompt: "lowres", width: "832", height: "1216",
  steps: "28", cfg_scale: "6", seed: "12345",
};
const RUN = { template: "a {red|blue} door", var_mode: "random", count: 3, run_seed: 42, dock_seed: "" };

function fakeComposer() {
  const calls = [];
  const g = {
    s: { roll: 111 },
    set: (p) => calls.push(["set", p]),
    applyModelRow: async (r) => { calls.push(["applyModelRow", r]);
      return { version_id: "ver-9", versions: [{ version_id: "ver-9" }, { version_id: "ver-7" }] }; },
    pickVersion: (v) => calls.push(["pickVersion", v]),
    addLora: async (l, o) => { calls.push(["addLora", l.version_id, o]); },
  };
  return { g, calls };
}

function fakeApi(map) {
  const seen = [];
  const apiGet = async (url) => {
    seen.push(url);
    for (const k of Object.keys(map)) if (url.startsWith(k)) return typeof map[k] === "function" ? map[k](url) : map[k];
    return { error: "no such route in the fake: " + url };
  };
  return { apiGet, seen };
}

describe("which prompt a remix restores", () => {
  test("a picture from a Generate power tools run restores its TEMPLATE, Random and the run seed", () => {
    const r = remixPatch(ROW, RUN, { roll: 111 });
    assert.equal(r.source, "template");
    assert.equal(r.patch.prompt, "a {red|blue} door");           // not the resolved prompt on the row
    assert.equal(r.patch.varMode, "random");
    assert.equal(r.patch.count, 3);
    assert.equal(r.patch.roll, 42);
    assert.equal(r.patch.seed, "");                              // the seed field as it was: blank
  });

  test("a Matrix run restores its template and mode, and no count (a matrix is one image per cell)", () => {
    const r = remixPatch(ROW, { template: "{a|b} {c|d}", var_mode: "matrix", count: 4, run_seed: 5, dock_seed: "77" }, {});
    assert.equal(r.patch.varMode, "matrix");
    assert.equal("count" in r.patch, false);
    assert.equal(r.patch.seed, "77");
  });

  test("any other picture restores its RECORDED prompt, braces escaped so it re-sends byte for byte", () => {
    for (const run of [undefined, null, {}, { var_mode: "" }, { var_mode: "batch", template: "x" }]) {
      const r = remixPatch(ROW, run, {});
      assert.equal(r.source, "recorded");
      // escapeLiteral: braces, and the underscore pair that would otherwise be a saved-list token
      assert.equal(r.patch.prompt, "a \\{braced\\} scene, \\_\\_list\\_\\_ and plain");
      assert.equal("varMode" in r.patch, false);
      assert.equal(r.patch.seed, "12345");
    }
    assert.equal(isTemplateRun({ var_mode: "random" }), true);
    assert.equal(isTemplateRun({ var_mode: "single" }), false);
  });

  test("the size, steps, cfg and negative come from the row; LoRAs are cleared for the restore to refill", () => {
    const p = remixPatch(ROW, null, {}).patch;
    assert.deepEqual([p.customW, p.customH, p.steps, p.cfg, p.negative, p.loras], ["832", "1216", "28", "6", "lowres", []]);
    const bare = remixPatch({ prompt_preview: "only a preview" }, null, {}).patch;
    assert.equal(bare.prompt, "only a preview");
    assert.deepEqual([bare.customW, bare.customH, bare.steps, bare.cfg, bare.seed], ["", "", "", "", ""]);
  });

  test("'new seed' re-rolls exactly the seed (and the run seed of a template run)", () => {
    const fixed = () => 0.5;
    assert.equal(remixPatch(ROW, null, { newSeed: true, rand: fixed }).patch.seed, String(Math.floor(0.5 * 2147483647)));
    const t = remixPatch(ROW, RUN, { newSeed: true, rand: fixed }).patch;
    assert.equal(t.seed, "");
    assert.notEqual(t.roll, 42);
  });
});

describe("remixImageInto", () => {
  test("reads the record, the model version and the task, then fills the composer; it sends nothing", async () => {
    const { g, calls } = fakeComposer();
    const api = fakeApi({
      "/api/next/detail/": { row: ROW, run: RUN },
      "/api/model-version?version_id=ver-7": { model_id: "base-1" },
      "/api/task-params/": { loras: [{ model_id: "l1", version_id: "lv1", weight: 0.7 }], unresolved: 0 },
    });
    const out = await remixImageInto(g, "700", {}, { apiGet: api.apiGet });
    assert.equal(out.ok, true);
    assert.equal(out.source, "template");
    assert.deepEqual(out.notes, []);
    assert.deepEqual(api.seen, [
      "/api/next/detail/700", "/api/model-version?version_id=ver-7", "/api/task-params/9001"]);
    const names = calls.map((c) => c[0]);
    assert.deepEqual(names, ["applyModelRow", "pickVersion", "set", "addLora", "set"]);
    assert.deepEqual(calls[1], ["pickVersion", "ver-7"]);               // the exact version that rendered
    assert.deepEqual(calls[3], ["addLora", "lv1", { autoInsert: false }]);   // a restore adds no trigger words
    assert.equal(calls[4][1].note, REMIX_NOTE);
  });

  test("a model that cannot be restored is DISCLOSED and the LoRAs are not wired onto another model", async () => {
    const { g, calls } = fakeComposer();
    const api = fakeApi({ "/api/next/detail/": { row: ROW, run: null }, "/api/model-version": { error: "gone" } });
    const out = await remixImageInto(g, "700", {}, { apiGet: api.apiGet });
    assert.equal(out.ok, true);
    assert.ok(out.notes.includes("model could not be restored — pick it manually"));
    assert.ok(out.notes.includes("LoRAs not loaded without the model"));
    assert.equal(calls.some((c) => c[0] === "addLora"), false);
    assert.match(calls[calls.length - 1][1].note, /Partial: model could not be restored/);
  });

  test("an unreadable record touches nothing and says ok:false", async () => {
    const { g, calls } = fakeComposer();
    const api = fakeApi({ "/api/next/detail/": { error: "not found" } });
    const out = await remixImageInto(g, "700", {}, { apiGet: api.apiGet });
    assert.equal(out.ok, false);
    assert.equal(out.error, "not found");
    assert.deepEqual(calls, []);
  });

  test("two quick taps do not interleave: the older flow is retired", async () => {
    const { g, calls } = fakeComposer();
    let release;
    const gate = new Promise((r) => { release = r; });
    const api = fakeApi({
      "/api/next/detail/701": async () => { await gate; return { row: { ...ROW, media_id: "701", prompt_full: "first" }, run: null }; },
      "/api/next/detail/702": { row: { ...ROW, media_id: "702", prompt_full: "second" }, run: null },
      "/api/model-version": { model_id: "base-1" },
      "/api/task-params/": { loras: [] },
    });
    const first = remixImageInto(g, "701", {}, { apiGet: api.apiGet });
    const second = await remixImageInto(g, "702", {}, { apiGet: api.apiGet });
    release();
    const late = await first;
    assert.equal(second.ok, true);
    assert.equal(late.ok, false);                                        // retired wholesale
    const prompts = calls.filter((c) => c[0] === "set" && c[1].prompt).map((c) => c[1].prompt);
    assert.deepEqual(prompts, ["second"]);
  });

  test("no picture, no composer: nothing happens", async () => {
    assert.equal((await remixImageInto(null, "1")).ok, false);
    assert.equal((await remixImageInto({}, "")).ok, false);
  });
});

describe("Send to Video and a video's Remix", () => {
  test("the start frame is this picture, an image-to-video shot, and the drawer's reuse chip is cleared", () => {
    assert.deepEqual(startFramePrefill("700"), { mode: "i2v", images: [{ media_id: "700", thumb: "/thumbs/700.jpg" }] });
    const seen = [];
    const drawer = { prefill: (o) => seen.push(["prefill", o]), setReuse: (v) => seen.push(["setReuse", v]) };
    assert.equal(sendStartFrame(drawer, "700"), true);
    assert.deepEqual(seen, [["prefill", startFramePrefill("700")], ["setReuse", null]]);
    assert.match(VIDEO_NOTE, /Nothing is generated until you press Generate/);
    assert.equal(sendStartFrame(null, "700"), false);
    assert.equal(sendStartFrame({}, "700"), false);
    assert.equal(sendStartFrame(drawer, ""), false);
  });

  test("a clip's Remix fills the drawer from the row and the task's recipe, with a chip", async () => {
    const seen = [];
    const drawer = { prefill: (o) => seen.push(["prefill", o]), setReuse: (v) => seen.push(["setReuse", v]) };
    const api = fakeApi({
      "/api/next/detail/": { row: { media_id: "800", task_id: "9100", is_video: "1", prompt_full: "slow push in" } },
      "/api/video-task-params/9100": { kind: "i2v", video_model: "v4" },
    });
    const out = await remixVideoInto(drawer, "800", { apiGet: api.apiGet });
    assert.equal(out.ok, true);
    assert.deepEqual(api.seen, ["/api/next/detail/800", "/api/video-task-params/9100"]);
    assert.equal(seen[0][0], "prefill");
    assert.equal(seen[1][0], "setReuse");
    assert.equal(seen[1][1].tag, "#9100");
  });

  test("an unreadable clip touches nothing", async () => {
    const seen = [];
    const drawer = { prefill: (o) => seen.push(o), setReuse: (v) => seen.push(v) };
    const out = await remixVideoInto(drawer, "800", { apiGet: fakeApi({ "/api/next/detail/": { error: "x" } }).apiGet });
    assert.equal(out.ok, false);
    assert.deepEqual(seen, []);
  });
});

/* ---- the structural proof ------------------------------------------------------------------ */
describe("nothing that spends is reachable from the handoff", () => {
  const FORBIDDEN_IMPORTS = [
    /gen\/submitTask/, /gen\/priceRequest/, /gen\/usePriceProbe/, /gen\/priceProbeCore/, /gen\/useRuns/,
    /gen\/useGenerate/, /gen\/useEditGenerate/, /VideoDrawer/, /RunControls/, /api\.js"[^;]*apiPost/,
  ];
  const FORBIDDEN_CALLS = [
    /\bapiPost\b/, /\bapiUpload\b/, /\bsubmitTask\b/, /\.generate\s*\(/, /\brun\.go\b/, /\brunBody\b/,
    /\brefreshPrice\b/, /\bgql_/, /["'`]\/api\/generate/, /["'`]\/api\/price/, /["'`]\/api\/panel\/run/,
    /\bpayload\s*\(/, /method:\s*["']POST/i, /\bfetch\s*\(/,
  ];

  test("gen/phoneRemix.js imports only reads and pure cores, and calls nothing that sends", () => {
    const text = codeOnly(read("gen/phoneRemix.js"));
    const imports = [...text.matchAll(/^import .* from "([^"]+)";$/gm)].map((m) => m[1]);
    assert.deepEqual(imports.sort(), ["../api.js", "./genCore.js", "./templateCore.js", "./videoRemixCore.js"].sort());
    // and of api.js it takes the GET only
    assert.ok(/import \{ apiGet as defaultApiGet \} from "\.\.\/api\.js";/.test(text));
    for (const rx of FORBIDDEN_IMPORTS) assert.ok(!rx.test(text), "imports " + rx);
    for (const rx of FORBIDDEN_CALLS) assert.ok(!rx.test(text), "calls " + rx);
    // every route it reads is a GET the desktop remix reads too
    const routes = [...text.matchAll(/get\("(\/api\/[^"]+)"/g)].map((m) => m[1]);
    assert.deepEqual([...new Set(routes)].sort(), [
      "/api/model-version?version_id=", "/api/next/detail/", "/api/task-params/", "/api/video-task-params/"].sort());
  });

  test("the pure cores it leans on have no transport at all", () => {
    for (const f of ["gen/genCore.js", "gen/templateCore.js", "gen/videoRemixCore.js"]) {
      const text = codeOnly(read(f));
      assert.ok(!/\bfetch\s*\(/.test(text) && !/\bapiPost\b/.test(text) && !/from "\.\.\/api\.js"/.test(text), f);
    }
  });

  test("the shell's Remix / Send to Video handlers reach only phoneRemix and the composer's setters", () => {
    const app = codeOnly(read("components/AppMobile.jsx"));
    const a = app.indexOf("const leaveViewers");
    const b = app.indexOf("const openDetailsFromLightbox");
    assert.ok(a > 0 && b > a, "the handlers are where the test expects them");
    const handlers = app.slice(a, b);
    for (const rx of [/\bgen\.generate\b/, /\bgen\.run\b/, /\brefreshPrice\b/, /\bapiPost\b/, /\bsubmitTask\b/, /\bfetch\s*\(/,
      /\.payload\b/, /\.flushPromptEdit\b/, /["'`]\/api\//]) {
      assert.ok(!rx.test(handlers), "the handlers must not touch " + rx);
    }
    assert.ok(/remixImageInto\(gen, mid\)/.test(handlers));
    assert.ok(/remixVideoInto\(videoRef\.current, mid\)/.test(handlers));
    assert.ok(/sendStartFrame\(videoRef\.current, mid\)/.test(handlers));
  });

  test("the record's two buttons and the Lightbox's To Video only call the shell's handlers", () => {
    const det = codeOnly(read("components/ImageDetailsMobile.jsx"));
    assert.ok(/onClick=\{\(\) => onRemix\(row\.media_id, row\.is_video === "1"\)\}/.test(det));
    assert.ok(/onClick=\{\(\) => onSendToVideo\(row\.media_id\)\}/.test(det));
    const lb = codeOnly(read("components/LightboxMobile.jsx"));
    assert.ok(/onClick=\{\(\) => onSendToVideo && onSendToVideo\(it\.media_id\)\}/.test(lb));
    // and the disclosed "coming later" stub for Send to Video is gone from both
    assert.ok(!/toast\("Send to Video"/.test(det) && !/toast\("Send to Video"/.test(lb));
  });

  test("the record's foot puts the two 44 px buttons in the pinned row (drift 122), first", () => {
    const det = read("components/ImageDetailsMobile.jsx");
    const at = det.indexOf('<div className="idm-recrow">');
    const rr = det.indexOf('<div className="idm-remixrow">');
    assert.ok(at > 0 && rr > at && rr - at < 900, "idm-remixrow is the recrow's first child");
    const css = read("styles/phone-q.css");
    assert.match(css, /\.idm-remixbtn \{[^}]*min-height: 44px/);
  });
});
