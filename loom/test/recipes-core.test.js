import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  MAX_RECIPES, KINDS, VISIBILITIES, addRecipe, removeRecipe, hasRecipe, chipOf, misfitOf, recipeGate,
  promptLimit, loraWeightRange, compact, kindsText, newDraft, stillNeeded, firstOpenStep, neededLine,
  shelfLine, toServerDraft, draftFromRecipe, kindMenu, tierDims, testPricePayload, marketQuery,
  filterChips, statusPill, statusAction, draftId, draftsFromPrefs, savedAgo, promptAddLine,
} from "../../gallery/src/recipes/recipesCore.js";

/* THE RECIPES' PURE HALF (lane w2-recipes, 2026-09-28): Session K and H3/H8/H10. What a
   recipe card says, whether a recipe fits the dock's request (T2b), the dock row's own
   refusal, what the creator still needs, the draft <-> PixAI body mapping. The server half
   (moonglade_recipes.py) is pinned by tests/test_recipes.py. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

const card = (o) => ({ id: "2046394714775712134", title: "Classic Japanese", cover: "c.webp",
  model_type: "MMDIT26B_MODEL", model_title: "Tsubaki.3", prompt_len: 86, usability: "usable", ...o });

describe("the dock row's list", () => {
  test("adds once, never past ten, and keeps what the fit check needs", () => {
    let list = [];
    for (let i = 0; i < MAX_RECIPES; i += 1) list = addRecipe(list, card({ id: String(100 + i) })).list;
    assert.equal(list.length, 10);
    const r = addRecipe(list, card({ id: "999" }));
    assert.equal(r.list, list);
    assert.match(r.refused, /Up to 10/);
    assert.equal(addRecipe(list, card({ id: "100" })).list, list);   // already in: no-op, no refusal
    assert.deepEqual(Object.keys(chipOf(card())).slice(0, 3), ["id", "title", "cover"]);
    assert.equal(chipOf(card()).model_type, "MMDIT26B_MODEL");
  });
  test("removes by id and answers membership", () => {
    const list = [chipOf(card({ id: "1" })), chipOf(card({ id: "2" }))];
    assert.deepEqual(removeRecipe(list, "1").map((r) => r.id), ["2"]);
    assert.ok(hasRecipe(list, "2") && !hasRecipe(list, "3"));
  });
});

describe("T2b: does a recipe fit the dock's request", () => {
  test("a different model type is a misfit named by both models", () => {
    const m = misfitOf(card({ model_type: "MMDIT26A_MODEL", model_title: "Tsubaki.2" }),
      { modelType: "MMDIT26B_MODEL", modelTitle: "Tsubaki.3" });
    assert.equal(m.tag, "Needs Tsubaki.2");
    assert.equal(m.why, "made for Tsubaki.2, not Tsubaki.3");
    assert.equal(m.group, "model");
  });
  test("the same type is left to PixAI, never guessed", () => {
    assert.equal(misfitOf(card(), { modelType: "MMDIT26B_MODEL" }), null);
    assert.equal(misfitOf(card(), {}), null);
  });
  test("a card PixAI says is unavailable or followers-only reads the handoff's copy", () => {
    assert.equal(misfitOf(card({ usability: "unavailable" }), {}).why, "This recipe isn't available any more");
    assert.equal(misfitOf(card({ usability: "follow_required" }), {}).why, "Follow the author to use it");
  });
  test("the prompt budget counts the dock's prompt and the other chips", () => {
    const others = [chipOf(card({ id: "1", prompt_len: 4000 }))];
    assert.equal(misfitOf(card({ model_type: "SDXL_MODEL", prompt_len: 90 }), { modelType: "SDXL_MODEL", promptLen: 0, recipes: others }), null);
    const m = misfitOf(card({ model_type: "SDXL_MODEL", prompt_len: 100 }), { modelType: "SDXL_MODEL", promptLen: 10, recipes: others });
    assert.equal(m.tag, "Prompt too long");
    assert.equal(promptLimit("MMDIT26B_MODEL"), 10000);
    assert.equal(promptLimit("SDXL_MODEL"), 4096);
  });
  test("PixAI's own refusal wins over everything the client can see", () => {
    const re = { tag: "Too many LoRAs", copy: "A recipe brings too many LoRAs", fix: "Remove a LoRA", group: "loras" };
    const m = misfitOf(card(), { refusals: { "2046394714775712134": re } });
    assert.equal(m.tag, "Too many LoRAs");
  });
  test("the row's refusal for Generate names the misfit", () => {
    assert.equal(recipeGate([], {}), null);
    assert.equal(recipeGate([chipOf(card())], { modelType: "MMDIT26B_MODEL" }), null);
    assert.match(recipeGate([chipOf(card({ model_type: "SDXL_MODEL" }))], { modelType: "MMDIT26B_MODEL" }), /doesn't fit/);
  });
  test("the pane's prompt line: +N chars, then the running total when the dock published its prompt", () => {
    assert.equal(promptAddLine(card(), {}), "+86 chars");
    assert.equal(promptAddLine(card(), { promptLen: 1154, modelType: "MMDIT26B_MODEL" }), "+86 chars · 1,240 / 10,000");
  });
});

describe("the creator's draft", () => {
  test("from a picture: step 2, the picture as showcase 1, the category never guessed", () => {
    const d = newDraft({ id: "d1", now: 1, from: { media_id: "501", model_id: "1850", model_type: "MMDIT26B_MODEL",
      model_title: "Tsubaki.3", prompt: "a moon", loras: [{ version_id: "88", weight: 0.7, trigger_words: "moon" }] } });
    assert.equal(d.step, 2);
    assert.equal(d.category, "");
    assert.deepEqual(d.showcase.map((s) => s.media_id), ["501"]);
    assert.equal(d.test.prompt, "a moon");
    assert.equal(d.ingredients[0].loras[0].trigger_words, "moon");
    assert.deepEqual(stillNeeded(d, 1), ["a category"]);
    assert.equal(neededLine(stillNeeded(d, 1)), "Still needed: a category");
    assert.deepEqual(stillNeeded(d, 2), ["2 more showcase images"]);
    assert.equal(firstOpenStep(d), 1);
    assert.equal(shelfLine(d), "Draft · step 1 of 3 · still needed: a category");
  });
  test("LoRA weights must sit in the model family's range", () => {
    const d = newDraft({ model: { model_id: "1", model_type: "MMDIT26B_MODEL" } });
    d.category = "style";
    d.ingredients = [{ type: "lora", loras: [{ version_id: "8", weight: 1.5 }] }];
    d.showcase = [1, 2, 3].map((i) => ({ media_id: String(i) }));
    assert.deepEqual(stillNeeded(d, 2), ["LoRA weights between 0 and 1.2"]);
    assert.deepEqual(loraWeightRange("SDXL_MODEL"), { min: -2, max: 2 });
  });
  test("the body PixAI's update route takes, one slot per ingredient, in order", () => {
    const d = newDraft({ model: { model_id: "1850", model_type: "MMDIT26B_MODEL" } });
    Object.assign(d, { category: "character", title: " Priestess ", preset: "follow_to_use",
      showcase: [{ media_id: "11" }, { media_id: "12" }, { media_id: "13" }],
      ingredients: [
        { type: "promptFragment", text: "night elf" },
        { type: "lora", loras: [{ version_id: "88", weight: 0.7, trigger_words: "" }] },
        { type: "contextImages", images: [{ media_id: "5", role: "character" }] },
        { type: "styleCode", code: " SC-1 " },
      ] });
    const b = toServerDraft(d);
    assert.deepEqual(b.categories, ["character"]);
    assert.equal(b.title, "Priestess");
    assert.equal(b.presetType, "follow_to_use");
    assert.equal(b.coverMediaId, "11");
    assert.deepEqual(b.slots, [
      { type: "promptFragment", text: "night elf" },
      { type: "lora", loras: [{ versionId: "88", weight: 0.7 }] },
      { type: "contextImages", images: [{ mediaId: "5", role: "character" }] },
      { type: "styleCode", styleCode: "SC-1" },
    ]);
  });
  test("a published recipe comes back into the creator with its values", () => {
    const d = draftFromRecipe({ id: "9", title: "Moon library", category: "scene", model_id: "1850",
      model_type: "MMDIT26B_MODEL", preset_type: "public", cover_media_id: "11", showcase_media_ids: ["11", "12", "13"],
      slots: [{ type: "promptFragment", text: "a library" }, { type: "lora", loras: [{ versionId: "8", weight: 0.5 }] }] }, { id: "d2", now: 5 });
    assert.equal(d.recipe_id, "9");
    assert.ok(d.editing);
    assert.equal(toServerDraft(d).slots[1].loras[0].versionId, "8");
    assert.deepEqual(stillNeeded(d, 1), []);
  });
  test("the add-ingredient menu: every kind, live counts, and why a kind is off", () => {
    const d = newDraft({ model: { model_id: "1", model_type: "MMDIT26B_MODEL", title: "Tsubaki.3" } });
    d.ingredients = [{ type: "lora", loras: [{ version_id: "8", weight: 0.7 }] }];
    const m = kindMenu(d, { slots: [{ type: "promptFragment", max: 10 }, { type: "lora", max: 10 }, { type: "styleCode", max: 1 }] });
    assert.equal(m.length, KINDS.length);
    const by = Object.fromEntries(m.map((k) => [k.type, k]));
    assert.equal(by.lora.text, "1 / 10");
    assert.equal(by.baseImage.off, "not taken by Tsubaki.3");
    assert.equal(by.promptFragment.off, "");
    assert.match(kindMenu(d, null)[0].off, /reading/);
  });
  test("the Unlisted choice is drawn and off: PixAI's update route can't set it", () => {
    const u = VISIBILITIES.find((v) => v.key === "unlisted");
    assert.ok(u && u.off);
    assert.deepEqual(VISIBILITIES.filter((v) => !v.off).map((v) => v.key), ["public", "follow_to_use", "private"]);
  });
});

describe("sizes, queries, labels", () => {
  test("H decision 7's rule on the M tier matches PixAI's own M row", () => {
    assert.deepEqual(tierDims("3:5", "M"), { width: 768, height: 1280 });
    assert.deepEqual(tierDims("1:1", "M"), { width: 992, height: 992 });
    assert.deepEqual(tierDims("16:9", "M"), { width: 1280, height: 720 });
  });
  test("the ✦ Test quote is the test shape with the draft's LoRAs folded in", () => {
    const d = newDraft({ model: { model_id: "1", version_id: "2", model_type: "MMDIT26B_MODEL" }, prompt: "p" });
    d.ingredients = [{ type: "lora", loras: [{ version_id: "8", weight: 0.6 }] }];
    const p = testPricePayload(d);
    assert.equal(p.count, 4);
    assert.deepEqual(p.loras, [{ version_id: "8", weight: 0.6 }]);
    assert.equal(p.version_id, "2");
    assert.ok(!("recipeIds" in p));
  });
  test("market queries: search trims and caps; filters become chips", () => {
    assert.deepEqual(marketQuery({ sort: "most-used", category: "style", modelType: "SDXL_MODEL", q: "  moon " }),
      { sort: "most-used", page: 1, page_size: 24, category: "style", model_type: "SDXL_MODEL", q: "moon" });
    assert.deepEqual(filterChips({ modelType: "MMDIT26B_MODEL" }), [{ key: "modelType", text: "Model: DiT.3" }]);
  });
  test("counts, pills, actions, ids", () => {
    assert.equal(compact(66900), "66.9k");
    assert.equal(compact(8), "8");
    assert.equal(kindsText([{ type: "promptFragment", count: 1 }, { type: "lora", count: 1 }]), "Prompt · LoRA ×1");
    assert.deepEqual(statusPill("test"), ["In review", "lavender"]);
    assert.equal(statusAction("archived"), "Unarchive");
    assert.match(draftId(1759000000000, "A1-b2c3!"), /^d[a-z0-9]+$/);
    assert.equal(savedAgo(0, 5), "");
    assert.equal(savedAgo(1000, 1000 + 7200 * 1000), "saved 2 h ago");
    const prefs = { "recipes.draft.da": { id: "da", saved: 1 }, "recipes.draft.db": { id: "db", saved: 2 }, "other": 1 };
    assert.deepEqual(draftsFromPrefs(prefs).map((d) => d.id), ["db", "da"]);
  });
});

describe("source guards", () => {
  test("nothing writes on open: the creator reaches PixAI only through publish/update", () => {
    const creator = src("recipes/RecipeCreator.jsx");
    assert.doesNotMatch(creator, /recipes\/draft/);
    const calls = creator.match(/recipesApi\.(\w+)/g) || [];
    const writes = calls.filter((c) => /publish|update|transition|setCreate|setToggle/.test(c));
    assert.deepEqual([...new Set(writes)].sort(), ["recipesApi.publish", "recipesApi.update"]);
    // both sit inside the one publish() handler the Publish / Save button runs
    assert.match(creator, /const publish = \(\) => \{[\s\S]*recipesApi\.update[\s\S]*recipesApi\.publish/);
  });
  test("✦ Test never sends a run, and its quote can never read FREE", () => {
    const creator = src("recipes/RecipeCreator.jsx");
    assert.match(creator, /const test = \(\) => setTestMsg\(/);
    assert.match(creator, /requestPrice\(\{ \.\.\.testPricePayload\(draft\), no_card: true \}/);
    assert.doesNotMatch(creator, /submitTask|\/api\/generate/);
  });
  test("the row's props contract, exactly as lane w2-gen renders it", () => {
    const row = src("recipes/RecipeRow.jsx");
    assert.match(row, /export default function RecipeRow\(\{ recipes, onChange, held, loraCount, modelType \}\)/);
  });
  test("only the one price transport names /api/price", () => {
    for (const f of ["recipes/RecipesOverlay.jsx", "recipes/RecipeCreator.jsx", "recipes/RecipeRow.jsx", "recipes/RecipesMobile.jsx"]) {
      assert.doesNotMatch(src(f), /\/api\/price/);
    }
  });
});
