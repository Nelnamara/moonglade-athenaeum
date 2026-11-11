import { test } from "node:test";
import assert from "node:assert/strict";
import { ruleLine, ceilingNotice } from "../../gallery/src/lib/contestRules.js";

/* #94. The contest detail screens build every required-model/LoRA/recipe link through
   ruleLine; these pin that an id is encoded before it reaches an href, that an unknown rule
   kind never gets a link (and is never counted as models), and the ceiling notice's words. */

test("ids are encoded before they reach an href", () => {
  const l = ruleLine({ type: "required_recipe_ids", recipe_ids: ['a/b?x#y"<'] });
  assert.equal(l.href(l.ids[0]), "https://pixai.art/recipes/a%2Fb%3Fx%23y%22%3C");
  const m = ruleLine({ type: "required_model_ids", model_ids: ["a/b"] });
  assert.equal(m.href("a/b"), "https://pixai.art/model/a%2Fb");
  const o = ruleLine({ type: "required_lora_ids", lora_ids: [7] });
  assert.equal(o.kind, "LoRA");
  assert.equal(o.href(7), "https://pixai.art/model/7");
});

test("a recipe rule is a recipe line, not a model line", () => {
  const l = ruleLine({ type: "required_recipe_ids", recipe_ids: ["2049376847228801627"] });
  assert.equal(l.kind, "recipe");
  assert.deepEqual(l.ids, ["2049376847228801627"]);
});

test("unknown kind never gets a link and is named by its own type", () => {
  const l = ruleLine({ type: "required_widget_ids", widget_ids: ["w"] });
  assert.equal(l.kind, "widget");
  assert.deepEqual(l.ids, ["w"]);
  assert.equal(l.href("w"), null);
});

test("missing or malformed id lists are empty, never a throw", () => {
  for (const r of [{ type: "required_recipe_ids" }, { type: "required_recipe_ids", recipe_ids: null },
                   { type: "required_recipe_ids", recipe_ids: 5 }, {}, null, "x"]) {
    assert.deepEqual(ruleLine(r).ids, []);
  }
});

test("the ceiling notice names the limit and the board's size, or just the limit", () => {
  const fmt = (n) => n.toLocaleString("en-US");
  assert.equal(ceilingNotice(undefined, fmt), null);
  assert.equal(ceilingNotice({ truncated: false }, fmt), null);
  assert.equal(ceilingNotice({ truncated: true, limit: 1000, total_count: 1200 }, fmt),
    "The newest 1,000 of PixAI's 1,200 contests are shown; older ones are not read.");
  assert.equal(ceilingNotice({ truncated: true, limit: 1000 }, fmt),
    "The oldest contests on PixAI's board are not shown: this app reads only the newest 1,000.");
});