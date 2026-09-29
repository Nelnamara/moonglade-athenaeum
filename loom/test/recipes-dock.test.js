import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  GEN_DEFAULTS, buildPayload, goGate, recipeFitCtx, tsubakiEditState,
} from "../../gallery/src/gen/genCore.js";
import { priceKey } from "../../gallery/src/gen/priceProbeCore.js";
import { prefsFromState, stateFromPrefs } from "../../gallery/src/gen/genPrefs.js";
import { chipOf } from "../../gallery/src/recipes/recipesCore.js";

/* Where lanes w2-gen (the Tsubaki.3 dock) and w2-recipes (the recipe row) meet, on the client:
   what the dock sends for its recipe row, what its price identity reads, when Generate refuses
   a recipe, and that both surfaces mount the real row with the props it needs. The server half
   of the same seam is tests/test_recipes.py's "integration with the Tsubaki.3 dock" section. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

const T3 = {
  version_id: "2024383379556065549", model_id: "2024383378759147749", title: "Tsubaki.3",
  model_type: "MMDIT26B_MODEL", context_images: true, creativity: true, context_max: 3,
};
const R1 = "2046394714775712134";
const R2 = "2046394714775712135";
const card = (o) => chipOf({ id: R1, title: "Classic Japanese", cover: "c.webp",
  model_type: "MMDIT26B_MODEL", model_title: "Tsubaki.3", prompt_len: 12, usability: "usable", ...o });

const dock = (o) => ({ ...GEN_DEFAULTS, model: T3, prompt: "a moonlit glade", ...o });

describe("buildPayload: recipeIds on the LoRA side only", () => {
  test("the ids only, as strings, in the row's order", () => {
    const p = buildPayload(dock({ recipes: [card({ id: R2 }), card({ id: R1 })] }));
    assert.deepEqual(p.recipeIds, [R2, R1]);
  });

  test("no recipes -> no recipeIds key at all (a plain payload is unchanged)", () => {
    const plain = buildPayload(dock({ recipes: [] }));
    assert.equal("recipeIds" in plain, false);
    assert.deepEqual(Object.keys(plain), Object.keys(buildPayload(dock())));
  });

  test("held on the Context side: never sent beside context images", () => {
    const s = dock({ recipes: [card()], inputs: "context", ctx: [{ media_id: "701" }], prompt: "Use @image1" });
    const p = buildPayload(s);
    assert.deepEqual(p.context_images, ["701"]);
    assert.equal("recipeIds" in p, false);
    // ...and switching back sends them again, untouched
    assert.deepEqual(buildPayload({ ...s, inputs: "loras" }).recipeIds, [R1]);
  });

  test("the Lightbox edit bar's payload never carries recipes", () => {
    const p = buildPayload(tsubakiEditState({ model: T3, image: { media_id: "701", w: 1216, h: 832 },
      prompt: "make it night" }));
    assert.equal("recipeIds" in p, false);
  });

  test("the price identity includes recipeIds, so adding or reordering one re-prices", () => {
    const a = priceKey(buildPayload(dock({ recipes: [card({ id: R1 })] })));
    const b = priceKey(buildPayload(dock({ recipes: [card({ id: R1 }), card({ id: R2 })] })));
    const c = priceKey(buildPayload(dock({ recipes: [card({ id: R2 }), card({ id: R1 })] })));
    const none = priceKey(buildPayload(dock()));
    assert.notEqual(a, b);
    assert.notEqual(b, c);
    assert.notEqual(a, none);
  });
});

describe("goGate: a recipe that doesn't fit holds Generate back (H T2b)", () => {
  test("a recipe made for another model refuses on the LoRA side, in the row's words", () => {
    const s = dock({ recipes: [card({ model_type: "SDXL_MODEL", model_title: "Pony" })] });
    assert.match(goGate(s, 3), /doesn't fit/);
  });

  test("held recipes (the Context side) are not judged", () => {
    const s = dock({ recipes: [card({ model_type: "SDXL_MODEL" })], inputs: "context",
      ctx: [{ media_id: "701" }], prompt: "Use @image1" });
    assert.equal(goGate(s, 3), null);
  });

  test("PixAI's own refusal on the last price answer refuses too", () => {
    const s = dock({ recipes: [card()] });
    assert.equal(goGate(s, 3), null);
    const answer = { cost: null, free: false, note: "x",
      recipe_error: { recipe_ids: [R1], copy: "Follow the author to use it", group: "follow" } };
    assert.match(goGate(s, 3, answer), /doesn't fit/);
    assert.deepEqual(Object.keys(recipeFitCtx(s, answer).refusals), [R1]);
    // a refusal naming a recipe no longer in the row holds nothing back
    assert.equal(goGate(dock({ recipes: [card({ id: R2 })] }), 3, answer), null);
  });

  test("a chip restored after reload ({id, title, cover} only) fails open to the server", () => {
    const restored = stateFromPrefs(prefsFromState(dock({ recipes: [card()] })));
    assert.deepEqual(restored.recipes, [{ id: R1, title: "Classic Japanese", cover: "c.webp" }]);
    assert.equal(goGate(dock({ recipes: restored.recipes }), 3), null);
    assert.deepEqual(buildPayload(dock({ recipes: restored.recipes })).recipeIds, [R1]);
  });
});

describe("both surfaces mount the real row", () => {
  for (const file of ["components/GenerateDrawer.jsx", "components/CreateMobile.jsx"]) {
    test(file + " renders RecipeRow with the dock's state, held on the Context side", () => {
      const s = src(file);
      assert.match(s, /import RecipeRow from "\.\.\/recipes\/RecipeRow\.jsx";/);
      assert.match(s, /<RecipeRow recipes=\{s\.recipes\} onChange=\{\(recipes\) => set\(\{ recipes \}\)\}\s+held=\{ctxOn\} loraCount=\{s\.loras\.length\} modelType=\{m \? m\.model_type : ""\} \/>/);
      assert.match(s, /goGate\(s, loraCap, (g\.)?priceAnswer\)/);
    });
  }

  test("the row is the recipe lane's, not the stub", () => {
    const row = src("recipes/RecipeRow.jsx");
    assert.doesNotMatch(row, /data-stub/);
    assert.match(row, /export default function RecipeRow\(\{ recipes, onChange, held, loraCount, modelType \}\)/);
    assert.doesNotMatch(src("styles/tsubaki.css"), /RecipeRow STUB/);
  });

  test("the dock publishes its request and price answer for the row and the picker", () => {
    const hook = src("gen/useGenerate.js");
    assert.match(hook, /publishDockRequest\(buildPayload\(s\)/);
    assert.match(hook, /publishDockPrice\(priceAnswer\)/);
    assert.match(hook, /goGate\(s, loraCap, priceAnswer\)/);
  });
});
