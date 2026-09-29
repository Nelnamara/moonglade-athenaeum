import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  FAMILIES, LAST_KEY, NEG_KEY, NEG_MAX, PRESETS_KEY, PRESET_MAX, QUICK_FAV_MAX, QUICK_KEY,
  QUICK_RECENT, QUICK_ROW_MAX, archName, baseHintOf, chipWeight, defaultState, defaultsFromPrefs,
  deletePreset, entryFromRow, familyOf, favIds, isFav, negativeOnSwitch, presetMeta,
  presetNegativeTail, presetsFromPrefs, quickChips, quickFromPrefs, recordSend, restorePatch,
  savePreset, snapshotFrom, snapshotOf, toggleDefault, toggleFav,
} from "../../gallery/src/gen/powerCore.js";
import { prefKeyProblem } from "../../gallery/src/hooks/accountPrefsStore.js";

/* Session M (Generate power tools) NOTES 4, 5 and 6: the default negative per base family,
   ↺ Last and Presets, the quick-pick chips. The pure half -- gen/powerCore.js -- is what the
   dock and the phone both render, so these are the rules the page (Generate Power Tools
   Handoff, M2 / M3 / M4) states, run as written. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8");

const T3 = { model_id: "111", title: "Tsubaki.3", model_type: "MMDIT26B_MODEL", version_id: "v9", thumb: "/t.jpg", base_hint: "" };
const SDXL = { model_id: "222", title: "Lucent Mix", model_type: "SDXL_MODEL", version_id: "v2", thumb: "", base_hint: "" };
const PONY = { model_id: "333", title: "Pony Prism", model_type: "SDXL_MODEL", version_id: "v3", thumb: "", base_hint: "Pony" };

describe("families", () => {
  test("the model card's base wins for Pony, Illustrious and Flux; otherwise the architecture", () => {
    assert.equal(familyOf(T3), "DiT");
    assert.equal(familyOf(SDXL), "SDXL");
    assert.equal(familyOf(PONY), "Pony");
    assert.equal(familyOf({ model_type: "SDXL_MODEL", base_hint: "Illustrious" }), "Illustrious");
    assert.equal(familyOf({ model_type: "MMDIT26B_MODEL", base_hint: "Flux" }), "Flux");
    assert.equal(familyOf({ model_type: "SD_V1_MODEL" }), "SD 1.5");
    assert.equal(familyOf({ model_type: "USER_DIT26A_MODEL" }), "DiT");
    assert.equal(familyOf({ model_type: "DIT7_MODEL" }), "DiT");
  });
  test("a model that says nothing has no family, and nothing is touched for it", () => {
    assert.equal(familyOf(null), "");
    assert.equal(familyOf({ model_id: "1", resolving: true }), "");
    assert.equal(familyOf({ model_type: "MYSTERY" }), "");
  });
  test("the base a card names is read the way the picker reads it", () => {
    assert.equal(baseHintOf("Pony"), "Pony");
    assert.equal(baseHintOf("uploaded-illustrious-xl"), "Illustrious");
    assert.equal(baseHintOf("flux-dev"), "Flux");
    assert.equal(baseHintOf("SDXL 1.0"), "SDXL");
    assert.equal(baseHintOf("sd v1.5"), "SD 1.5");
    assert.equal(baseHintOf("something else"), "");
    assert.equal(baseHintOf(""), "");
  });
  test("architecture names for a chip's reason", () => {
    assert.equal(archName("MMDIT26B_MODEL"), "DiT.3");
    assert.equal(archName("sdxl_model"), "SDXL");
    assert.equal(archName("NOPE"), "");
  });
});

describe("the default negative (NOTES 4, page M2)", () => {
  const D = { DiT: "lowres, bad hands, watermark, text", SDXL: "lowres, bad hands, watermark" };

  test("what comes back from the account is checked: known families, bounded text", () => {
    assert.deepEqual(defaultsFromPrefs({ DiT: "a", Nope: "b", SDXL: "  ", Pony: 3 }), { DiT: "a" });
    assert.deepEqual(defaultsFromPrefs({ DiT: "x".repeat(NEG_MAX + 1) }), {});
    assert.deepEqual(defaultsFromPrefs(null), {});
    assert.deepEqual(defaultsFromPrefs([1]), {});
  });

  test("the first model of a session fills an EMPTY field with its family's default", () => {
    const r = negativeOnSwitch({ from: "", to: "DiT", negative: "", defaults: D });
    assert.equal(r.negative, D.DiT);
    assert.match(r.note, /Started with your DiT default negative/);
    // ...and says nothing when there is no default to fill
    assert.deepEqual(negativeOnSwitch({ from: "", to: "Flux", negative: "", defaults: D }), { negative: "", note: "" });
  });

  test("a negative the owner typed is NEVER replaced, on the first model or on a switch", () => {
    assert.equal(negativeOnSwitch({ from: "", to: "DiT", negative: "my own", defaults: D }).negative, "my own");
    const r = negativeOnSwitch({ from: "DiT", to: "SDXL", negative: "my own", defaults: D });
    assert.deepEqual(r, { negative: "my own", note: "" });
  });

  test("a family switch replaces an empty field or the OLD family's default with the new default", () => {
    const a = negativeOnSwitch({ from: "DiT", to: "SDXL", negative: D.DiT, defaults: D });
    assert.equal(a.negative, D.SDXL);
    assert.equal(a.note, "Switched to SDXL: its default negative is filled in.");
    const b = negativeOnSwitch({ from: "DiT", to: "SDXL", negative: "  ", defaults: D });
    assert.equal(b.negative, D.SDXL);
  });

  test("switching to a family with no default clears the old default and says so", () => {
    const r = negativeOnSwitch({ from: "DiT", to: "Pony", negative: D.DiT, defaults: D });
    assert.equal(r.negative, "");
    assert.equal(r.note, "Switched to Pony: no default saved for it.");
  });

  test("the same family, or an unknown one, changes nothing", () => {
    assert.deepEqual(negativeOnSwitch({ from: "DiT", to: "DiT", negative: "", defaults: D }), { negative: "", note: "" });
    assert.deepEqual(negativeOnSwitch({ from: "DiT", to: "", negative: D.DiT, defaults: D }), { negative: D.DiT, note: "" });
  });

  test("★ Default shows while the field matches the saved default; clicking it again clears the default", () => {
    const on = defaultState({ family: "DiT", negative: D.DiT, defaults: D });
    assert.equal(on.isDefault, true);
    assert.equal(on.label, "★ Default · DiT");
    assert.match(on.title, /reset \(clear\) the DiT default/);
    const off = defaultState({ family: "DiT", negative: "different", defaults: D });
    assert.equal(off.isDefault, false);
    assert.equal(off.label, "☆ Set as default");
    const set = toggleDefault({ family: "DiT", negative: "different", defaults: D });
    assert.equal(set.defaults.DiT, "different");
    assert.equal(set.defaults.SDXL, D.SDXL);
    assert.equal(set.note, "Saved as the DiT default. New sessions start with it.");
    const cleared = toggleDefault({ family: "DiT", negative: D.DiT, defaults: D });
    assert.equal("DiT" in cleared.defaults, false);
    assert.equal(cleared.note, "The DiT default is cleared.");
    assert.equal(D.DiT.length > 0, true, "the input object is never mutated");
  });

  test("it cannot be set without a model's family or an empty negative, or over the bound", () => {
    assert.match(toggleDefault({ family: "", negative: "x", defaults: D }).error, /Pick a model first/);
    assert.match(toggleDefault({ family: "DiT", negative: "  ", defaults: {} }).error, /Type a negative first/);
    assert.match(toggleDefault({ family: "DiT", negative: "x".repeat(NEG_MAX + 1), defaults: {} }).error, /up to/);
    assert.equal(defaultState({ family: "", negative: "x", defaults: D }).disabled, true);
    assert.equal(defaultState({ family: "DiT", negative: "", defaults: {} }).disabled, true);
    assert.equal(defaultState({ family: "DiT", negative: "x", defaults: {} }).disabled, false);
  });

  test("the model row's preset note carries the page's tail only when a default would have been used", () => {
    const withNeg = { ...T3, preset: { negative: "bad" } };
    assert.equal(presetNegativeTail(withNeg, D), " · and a negative prompt (replaces your default)");
    assert.equal(presetNegativeTail(withNeg, {}), "");
    assert.equal(presetNegativeTail({ ...T3, preset: { negative: "" } }, D), "");
  });
});

describe("snapshots: ↺ Last and Presets (NOTES 5, page M3)", () => {
  const S = {
    model: { ...T3, extra: "dropped" },
    loras: [{ model_id: "9", title: "Moon", preview_url: "/m.jpg", version_id: "lv1", weight: 0.7, lora_base_type: "MMDIT26B_MODEL", trigger_words: "moon, glow", versions: [1, 2, 3] }],
    prompt: "1girl, {silver|cobalt} hair", negative: "lowres", aspect: 0.75, size: 1024, customW: "", customH: "",
    landscape: false, tier: "XL", auto: true, steps: "28", cfg: "6", count: 2, varMode: "matrix", mode: "pro",
    creativity: "low", highPriority: true, promptHelper: false, boosters: { face: true, quality: false, hires: true },
    seed: "12345", ctx: [{ media_id: "1" }], ref: { media_id: "2" }, palette: { name: "x" }, recipes: [{ id: "5" }], unlimited: true,
  };

  test("a preset holds the composer's fields and NEVER the seed; Last adds it", () => {
    const p = snapshotOf(S);
    assert.equal("seed" in p, false);
    assert.equal(p.tab, "image");
    assert.equal(p.model.model_id, "111");
    assert.equal("extra" in p.model, false);
    assert.deepEqual(p.loras[0], { model_id: "9", title: "Moon", preview_url: "/m.jpg", version_id: "lv1", weight: 0.7, lora_base_type: "MMDIT26B_MODEL", trigger_words: "moon, glow" });
    assert.equal(p.prompt, S.prompt);
    assert.equal(p.negative, "lowres");
    assert.equal(p.count, 2);
    assert.equal(p.varMode, "matrix");
    assert.equal(p.mode, "pro");
    assert.deepEqual(p.boosters, { face: true, quality: false, hires: true });
    const l = snapshotOf(S, { withSeed: true });
    assert.equal(l.seed, "12345");
  });

  test("images, the reference, the palette, recipes and Unlimited Mode are not part of one", () => {
    const p = snapshotOf(S);
    for (const k of ["ctx", "ref", "palette", "recipes", "unlimited"]) assert.equal(k in p, false, k);
  });

  test("it survives the account's JSON and is read back checked", () => {
    const back = snapshotFrom(JSON.parse(JSON.stringify(snapshotOf(S, { withSeed: true }))));
    assert.deepEqual(back, snapshotOf(S, { withSeed: true }));
  });

  test("a value of the wrong shape is dropped, never repaired into something the owner did not pick", () => {
    assert.equal(snapshotFrom(null), null);
    assert.equal(snapshotFrom([1]), null);
    const bad = snapshotFrom({ model: { model_id: "bad id!" }, loras: [{ model_id: "1", weight: "x" }, { model_id: "2", weight: 0.5 }],
      count: 99, varMode: "both", mode: "warp", creativity: "max", steps: "abc", cfg: "1.234", aspect: 99, seed: "1x" });
    assert.equal(bad.model, null);
    assert.deepEqual(bad.loras.map((l) => l.model_id), ["2"]);
    assert.equal(bad.count, 4);
    assert.equal(bad.varMode, "random");
    assert.equal(bad.mode, "auto");
    assert.equal(bad.creativity, "medium");
    assert.equal(bad.steps, "");
    assert.equal(bad.cfg, "");
    assert.equal(bad.aspect, 1);
    assert.equal(bad.seed, "");
  });

  test("restoring writes every field, lands on the LoRA side, and touches the seed only for Last", () => {
    const snap = snapshotFrom(snapshotOf(S, { withSeed: true }));
    const p = restorePatch(snap);
    assert.equal("seed" in p, false);
    assert.equal(p.inputs, "loras");
    assert.equal(p.prompt, S.prompt);
    assert.equal(p.varMode, "matrix");
    assert.deepEqual(p.boosters, { face: true, quality: false, hires: true });
    assert.equal("model" in p, false, "the model and the LoRAs need the applied model, so the hook restores them");
    assert.equal("loras" in p, false);
    assert.equal(restorePatch(snap, { withSeed: true }).seed, "12345");
  });
});

describe("presets (NOTES 5: 30 at most, account-side)", () => {
  const snap = snapshotOf({ model: T3, loras: [], prompt: "p", negative: "", count: 1, boosters: {} });

  test("saving puts the newest first and the same name replaces", () => {
    let list = [];
    list = savePreset(list, "A", snap).list;
    list = savePreset(list, "B", snap).list;
    assert.deepEqual(list.map((p) => p.name), ["B", "A"]);
    const again = savePreset(list, "A", { ...snap, prompt: "changed" });
    assert.deepEqual(again.list.map((p) => p.name), ["A", "B"]);
    assert.equal(again.list[0].prompt, "changed");
    assert.equal(again.replaced, true);
  });

  test("a name is required and trimmed; the seed is never stored even if it is in the snapshot", () => {
    assert.match(savePreset([], "  ", snap).error, /name/);
    const r = savePreset([], "  My preset  ", { ...snap, seed: "5" });
    assert.equal(r.list[0].name, "My preset");
    assert.equal("seed" in r.list[0], false);
  });

  test("thirty is the limit: the thirty-first is refused in plain words, replacing one still works", () => {
    let list = [];
    for (let i = 0; i < PRESET_MAX; i++) list = savePreset(list, "p" + i, snap).list;
    assert.equal(list.length, 30);
    assert.match(savePreset(list, "one more", snap).error, /30 presets/);
    assert.equal(savePreset(list, "p3", { ...snap, prompt: "again" }).list.length, 30);
  });

  test("a save that would come near the store's 64 KB is refused, not sent to fail", () => {
    const fat = { ...snap, prompt: "x".repeat(8000) };
    let list = [];
    let last;
    for (let i = 0; i < 12; i++) { last = savePreset(list, "big" + i, fat); if (last.error) break; list = last.list; }
    assert.match(last.error, /too large/);
  });

  test("delete removes by name; what comes back is deduplicated, capped and checked", () => {
    const list = [{ name: "a", ...snap }, { name: "b", ...snap }];
    assert.deepEqual(deletePreset(list, "a").map((p) => p.name), ["b"]);
    const back = presetsFromPrefs([{ name: "a", ...snap, seed: "9" }, { name: "a", ...snap }, { name: "", ...snap }, { nope: 1 }, "x",
      { name: "c", ...snap, model: { model_id: "bad id" } }]);
    assert.deepEqual(back.map((p) => p.name), ["a", "c"]);
    assert.equal("seed" in back[0], false);
    assert.equal(back[1].model, null);
    const many = Array.from({ length: 40 }, (_, i) => ({ name: "n" + i, ...snap }));
    assert.equal(presetsFromPrefs(many).length, PRESET_MAX);
    assert.deepEqual(presetsFromPrefs("no"), []);
  });

  test("the line under a preset's name", () => {
    assert.equal(presetMeta({ model: { title: "Tsubaki.3" }, loras: [{}, {}], count: 2, varMode: "matrix" }), "Tsubaki.3 · 2 LoRAs · ×2 · matrix");
    assert.equal(presetMeta({ model: null, loras: [{}], count: 1, varMode: "random" }), "no model · 1 LoRA · ×1");
  });
});

describe("quick-pick chips (NOTES 6, page M4)", () => {
  const S1 = { model: T3, inputs: "loras", loras: [
    { model_id: "10", title: "Moonstalker", preview_url: "/a.jpg", weight: 0.65, lora_base_type: "MMDIT26B_MODEL" },
    { model_id: "11", title: "Soft rim", preview_url: "", weight: 0.5, lora_base_type: "MMDIT26B_MODEL" }] };

  test("a send moves the recents: the last 3 DISTINCT, newest first, this send's LoRAs first in order", () => {
    let q = quickFromPrefs(null);
    q = recordSend(q, S1);
    assert.deepEqual(q.models.recent.map((e) => e.id), ["111"]);
    assert.deepEqual(q.loras.recent.map((e) => e.id), ["10", "11"]);
    q = recordSend(q, { model: SDXL, loras: [{ model_id: "12", title: "Glade", weight: 0.6, lora_base_type: "SDXL_MODEL" }] });
    q = recordSend(q, { model: T3, loras: [] });
    q = recordSend(q, { model: PONY, loras: [] });
    q = recordSend(q, { model: SDXL, loras: [] });
    assert.deepEqual(q.models.recent.map((e) => e.id), ["222", "333", "111"], "3 at most, distinct, newest first");
    assert.deepEqual(q.loras.recent.map((e) => e.id), ["12", "10", "11"]);
    assert.equal(QUICK_RECENT, 3);
  });

  test("a LoRA's last weight is kept and its chip adds at it (0.7 when it has never been sent)", () => {
    const q = recordSend(null, S1);
    assert.equal(chipWeight(q, "10"), 0.65);
    assert.equal(chipWeight(q, "999"), 0.7);
  });

  test("the Context side holds its LoRAs, so a send from it records none and keeps no weights", () => {
    const q = recordSend(null, { ...S1, inputs: "context" });
    assert.deepEqual(q.loras.recent, []);
    assert.deepEqual(q.weights, {});
    assert.deepEqual(q.models.recent.map((e) => e.id), ["111"]);
  });

  test("★ favourites come from the pickers: toggled on and off, newest first, bounded", () => {
    const row = { model_id: "500", title: "Fav LoRA", preview_url: "/f.jpg", lora_base_model_type: "SDXL_MODEL" };
    const e = entryFromRow("lora", row);
    assert.deepEqual(e, { id: "500", title: "Fav LoRA", thumb: "/f.jpg", base: "SDXL_MODEL" });
    let q = toggleFav(null, "lora", e);
    assert.equal(isFav(q, "lora", "500"), true);
    assert.deepEqual(favIds(q, "lora"), ["500"]);
    assert.deepEqual(favIds(q, "base"), []);
    q = toggleFav(q, "lora", e);
    assert.equal(isFav(q, "lora", "500"), false);
    const m = entryFromRow("base", { model_id: "600", title: "Pony X", preview_url: "", model_type: "SDXL_MODEL", base_model: "Pony" });
    assert.deepEqual(m, { id: "600", title: "Pony X", thumb: "", type: "SDXL_MODEL", hint: "Pony" });
    let many = null;
    for (let i = 0; i < QUICK_FAV_MAX + 5; i++) many = toggleFav(many, "base", { id: "f" + i, title: "t", thumb: "", type: "", hint: "" });
    assert.equal(favIds(many, "base").length, QUICK_FAV_MAX);
    assert.equal(entryFromRow("base", { title: "no id" }), null);
  });

  test("a row holds the 3 recents then the favourites that are not among them, at most 6", () => {
    let q = null;
    for (const id of ["1", "2", "3", "4"]) q = recordSend(q, { model: { model_id: id, title: "M" + id, model_type: "SDXL_MODEL" }, loras: [] });
    for (const id of ["1", "7", "8", "9", "10"]) q = toggleFav(q, "base", { id, title: "F" + id, thumb: "", type: "", hint: "" });
    const chips = quickChips(q, "base", { model: { model_id: "4", model_type: "SDXL_MODEL" } });
    assert.ok(chips.length <= QUICK_ROW_MAX);
    assert.deepEqual(chips.map((c) => c.id), ["4", "3", "2", "10", "9", "8"], "recents (3) first, then favourites not already there, capped at 6");
    assert.equal(chips[0].on, true);
    assert.equal(chips[1].on, false);
    assert.equal(chips[3].fav, true);
    assert.ok(chips[3].label.startsWith("★ "));
    assert.equal(chips[1].label.startsWith("★"), false);
  });

  test("a favourite that is also recent is one chip, drawn as a favourite", () => {
    let q = recordSend(null, { model: T3, loras: [] });
    q = toggleFav(q, "base", { id: "111", title: "Tsubaki.3", thumb: "", type: "MMDIT26B_MODEL", hint: "" });
    const chips = quickChips(q, "base", { model: SDXL });
    assert.equal(chips.length, 1);
    assert.equal(chips[0].fav, true);
    assert.equal(chips[0].on, false);
  });

  test("a LoRA chip is on while it is attached, and a LoRA for another family is dimmed with its reason", () => {
    const q = recordSend(null, S1);
    const dit = quickChips(q, "lora", { model: T3, loras: [{ model_id: "10" }] });
    assert.equal(dit[0].on, true);
    assert.equal(dit[0].dim, false);
    assert.equal(dit[0].title, "Tap to remove");
    assert.equal(dit[1].title, "Tap to add at its last weight");
    assert.equal(dit[0].label, "Moonstalker 0.65");
    const onSdxl = quickChips(q, "lora", { model: SDXL, loras: [] });
    assert.equal(onSdxl[0].dim, true);
    assert.equal(onSdxl[0].title, "For DiT.3 models; Lucent Mix is SDXL");
    // with no model yet nothing can be judged incompatible
    assert.equal(quickChips(q, "lora", { model: null, loras: [] })[0].dim, false);
  });

  test("what comes back from the account is checked and bounded", () => {
    const q = quickFromPrefs({ models: { recent: [{ id: "1", title: "a" }, { id: "1", title: "dup" }, { id: "bad id" }, null, { id: "2" }, { id: "3" }, { id: "4" }], fav: "no" },
      loras: { recent: [{ id: "5", base: "sdxl_model" }] }, weights: { 5: 0.4, x: "bad", 6: 99, "bad key": 1 } });
    assert.deepEqual(q.models.recent.map((e) => e.id), ["1", "2", "3"]);
    assert.deepEqual(q.models.fav, []);
    assert.equal(q.loras.recent[0].base, "SDXL_MODEL");
    assert.deepEqual(q.weights, { 5: 0.4 });
    assert.deepEqual(quickFromPrefs("junk"), { models: { recent: [], fav: [] }, loras: { recent: [], fav: [] }, weights: {} });
  });

  test("weights are kept only for LoRAs that still have a chip", () => {
    let q = recordSend(null, S1);
    for (const id of ["20", "21", "22"]) q = recordSend(q, { model: T3, loras: [{ model_id: id, title: id, weight: 0.3, lora_base_type: "" }] });
    assert.deepEqual(Object.keys(q.weights).sort(), ["20", "21", "22"]);
  });
});

describe("where it lives", () => {
  test("every key is one the account store accepts, under the dock's own gen. segment", () => {
    for (const k of [NEG_KEY, PRESETS_KEY, LAST_KEY, QUICK_KEY]) {
      assert.equal(prefKeyProblem(k), "", k);
      assert.ok(k.startsWith("gen."), k);
    }
    assert.equal(new Set([NEG_KEY, PRESETS_KEY, LAST_KEY, QUICK_KEY]).size, 4);
    assert.ok(FAMILIES.length >= 5);
  });

  test("nothing writes on open: the store is written only from a click or an accepted send", () => {
    const hook = src("gen/useGenerate.js");
    // every write of the four keys sits inside a named callback, never a bare effect body
    for (const key of ["LAST_KEY", "QUICK_KEY", "PRESETS_KEY", "NEG_KEY"]) {
      const at = [...hook.matchAll(new RegExp("\\.set\\(" + key, "g"))].map((m) => m.index);
      assert.ok(at.length >= 1, key + " is written somewhere");
      for (const i of at) {
        const before = hook.slice(Math.max(0, i - 900), i);
        const lastEffect = before.lastIndexOf("useEffect(");
        const lastCb = Math.max(before.lastIndexOf("useCallback("), before.lastIndexOf("=> {"));
        assert.ok(lastCb > lastEffect, key + " is written outside any effect");
      }
    }
    for (const f of ["components/PowerControls.jsx", "components/PowerMobile.jsx"]) {
      assert.ok(!/accountPrefs\(\)\.set|prefs\.set\(/.test(src(f)), f + " draws only; the hook writes");
      assert.ok(!/useEffect\([^)]*\.(save|set)\w*\(/s.test(src(f)), f);
    }
  });

  test("Last and the quick picks are recorded only from a send the server accepted", () => {
    const hook = src("gen/useGenerate.js");
    assert.match(hook, /const taskId = await submitTask\("\/api\/generate"[\s\S]{0,80}\n\s*if \(taskId\) noteSent\(s\);/);
    assert.match(hook, /res\.jobs\.some\(\(j\) => j && \(j\.state === "sent" \|\| j\.task_id\)\)/);
    // noteSent is the only writer of gen.last, and it never reads the seed from anywhere but the send
    assert.equal([...hook.matchAll(/LAST_KEY, snapshotOf/g)].length, 1);
  });

  test("a restore blocks the send until it has settled, and never sends", () => {
    const hook = src("gen/useGenerate.js");
    assert.match(hook, /if \(busyRef\.current \|\| runs\.busyRef\.current \|\| restoringRef\.current\) return;/);
    const body = hook.slice(hook.indexOf("const restoreComposer"), hook.indexOf("const restoreLast"));
    assert.ok(!/submitTask|runs\.|apiPost|generate\(/.test(body), "a restore only prefills");
    assert.match(body, /autoInsert: false/);
    const dock = src("components/GenerateDrawer.jsx");
    assert.match(dock, /g\.power\.restoring \|\| !g\.canSubmit/);
  });

  test("the phone does not offer setting up a Matrix", () => {
    const rc = src("components/RunControls.jsx");
    assert.match(rc, /\{!phone && \(\s*<div className="mgrun-seg">/);
    const cm = src("components/CreateMobile.jsx");
    assert.match(cm, /<RunModeRow [^>]*phone \/>/);
    assert.match(cm, /desktop-only/);
  });
});
