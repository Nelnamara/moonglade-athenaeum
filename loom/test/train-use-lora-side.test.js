import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { GEN_DEFAULTS, buildPayload, toLoraSide } from "../../gallery/src/gen/genCore.js";
import { loraForDock } from "../../gallery/src/gen/trainCore.js";

/* Where lane w3-train (Train a LoRA's "Use", Training Handoff 5c) meets wave 2's Tsubaki.3 dock
   (the LoRAs | Context images switch, Session H decision 1). On the Context side the dock HOLDS
   its LoRAs -- buildPayload sends none of them -- so a trained LoRA handed in there would sit
   unseen and never run. "Use" therefore moves the dock to the LoRA side first (toLoraSide) on
   both hosts: the desktop dock's genRequest {tab: "lora"} and the phone's Create tab. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

const T3 = {
  version_id: "2024383379556065549", model_id: "2024383378759147749", title: "Tsubaki.3",
  model_type: "MMDIT26B_MODEL", context_images: true, creativity: true, context_max: 3,
};
const trained = loraForDock({ model_id: "1900000000000000001", version_id: "1900000000000000002",
  title: "My trained LoRA", trigger_words: "moonkin", base_version_id: "x" }, () => "MMDIT26B_MODEL");
const onDock = (lora) => ({
  model_id: lora.model_id, version_id: lora.version_id, title: lora.title, weight: lora.weight,
  lora_base_type: lora.lora_base_model_type, trigger_words: lora.trigger_words, versions: [],
});
const ctxDock = {
  ...GEN_DEFAULTS, model: T3, prompt: "@image1 in a moonlit glade", inputs: "context",
  ctx: [{ media_id: "111", thumb: "", w: 1024, h: 1024 }], loras: [onDock(trained)],
};

describe("Use lands a trained LoRA on the LoRA side", () => {
  test("left on the Context side the LoRA would be held, never sent (the reason for the move)", () => {
    const p = buildPayload(ctxDock);
    assert.deepEqual(p.loras, []);
    assert.deepEqual(p.context_images, ["111"]);
  });

  test("toLoraSide sends the LoRA and no context image beside it", () => {
    const s = toLoraSide(ctxDock);
    assert.equal(s.inputs, "loras");
    const p = buildPayload(s);
    assert.equal(p.loras.length, 1);
    assert.equal(p.context_images, undefined);
    assert.equal(p.image_refs, undefined);
  });

  test("the context images are kept in the state, held, exactly as the switch leaves them", () => {
    const s = toLoraSide(ctxDock);
    assert.deepEqual(s.ctx, ctxDock.ctx);
  });

  test("already on the LoRA side: the same state object back (no needless re-render)", () => {
    const s = { ...GEN_DEFAULTS, model: T3 };
    assert.equal(toLoraSide(s), s);
  });
});

describe("both hosts route Use through takeLora", () => {
  test("useGenerate.takeLora moves to the LoRA side, then takes the picker's addLora road", () => {
    const u = src("gen/useGenerate.js");
    const body = u.slice(u.indexOf("const takeLora"), u.indexOf("return { s, set, busy"));
    assert.match(body, /setS\(toLoraSide\)/);
    assert.match(body, /return addLora\(row\)/);
    assert.match(u, /addLora, takeLora, removeLora/);
  });

  test("desktop: the dock's {tab: 'lora'} request calls takeLora, never the bare addLora", () => {
    const d = src("components/GenerateDrawer.jsx");
    const branch = d.slice(d.indexOf('request.tab === "lora"'), d.indexOf("}, [request]);"));
    assert.match(branch, /g\.takeLora\(request\.lora\)/);
    assert.doesNotMatch(branch, /g\.addLora\(/);
  });

  test("phone: Runs' Use on the Create tab calls takeLora", () => {
    const m = src("components/AppMobile.jsx");
    const fn = m.slice(m.indexOf("const takeTrainedLora"), m.indexOf("const logOut"));
    assert.match(fn, /gen\.takeLora\(lora\)/);
    assert.doesNotMatch(fn, /gen\.addLora\(/);
    assert.match(fn, /setTab\("create"\)/);
  });

  test("the train surfaces hand Use to their host (desktop overlay and phone screen)", () => {
    assert.match(src("App.jsx"), /<TrainOverlay onClose=\{\(\) => setOverlay\(null\)\} onUseLora=\{requestLora\} \/>/);
    assert.match(src("App.jsx"), /setGenRequest\(\{ tab: "lora", lora, nonce/);
    assert.match(src("components/AppMobile.jsx"), /<TrainMobile onClose=\{closeScreen\} onUseLora=\{takeTrainedLora\}/);
  });
});
