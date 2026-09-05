import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "path";

import {
  insertTriggerWords, missingTriggerWords, promptHasTrigger, splitTriggerWords,
} from "../../gallery/src/gen/loraTriggers.js";

/* Issue #45 -- "LoRA trigger words: no auto-insert anywhere; mobile lacks even the manual
   '+words' control" (owner, surface walk 2026-08-29: "does not auto insert - Desktop needs
   auto insert too... I have to click to add lora text which is dumb"; ruled 2026-09-04
   "auto insert for mobile AS WELL -- matches PixAI behavior").

   A LoRA attached without its activation tokens is a SILENT no-op on a paid generation
   (private/GENERATOR_SURFACE.md, "LoRA TRIGGER WORDS"), which is why PixAI's own composer
   appends them the moment you pick one. Before this change the desktop drawer had a manual
   "+words" button and mobile had nothing whatsoever.

   Both composers are JSX and this suite cannot import them, so the rule that decides WHAT
   text lands in the prompt lives in gallery/src/gen/loraTriggers.js -- the same reason
   gen/queueWait.js exists -- and is asserted here by calling the real functions. The source
   greps at the bottom pin the other half: that both surfaces, and the manual button, go
   through that one rule instead of growing a second formatter that drifts. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(__dirname, "../../", p), "utf8");
const hook = read("gallery/src/gen/useGenerate.js");
const drawer = read("gallery/src/components/GenerateDrawer.jsx");
const mobile = read("gallery/src/components/CreateMobile.jsx");
const mobileCss = read("gallery/src/styles/create-mobile.css");

// The two real banked values from private/GENERATOR_SURFACE.md, used verbatim throughout:
// a plain multi-token string, and one that ships PixAI's <lora:name:weight> syntax.
const TRISTAN = "1stasc, 2ndasc, 3rdasc";
const ERIS = "Eris_Adult, <lora:ErisV14:1>";

describe("the trigger-word insert appends in the drawer's own format", () => {
  test("an empty prompt takes the words alone, with no leading separator", () => {
    assert.equal(insertTriggerWords("", TRISTAN), "1stasc, 2ndasc, 3rdasc");
    // Whitespace-only is the same case -- the user has typed nothing.
    assert.equal(insertTriggerWords("   ", TRISTAN), "1stasc, 2ndasc, 3rdasc");
  });

  test("a prompt with text is trimmed, its trailing comma dropped, and joined with ', '", () => {
    assert.equal(insertTriggerWords("a knight", TRISTAN),
                 "a knight, 1stasc, 2ndasc, 3rdasc");
    // The trailing comma (and the space after it) is absorbed, never doubled.
    assert.equal(insertTriggerWords("a knight, ", TRISTAN),
                 "a knight, 1stasc, 2ndasc, 3rdasc");
    assert.equal(insertTriggerWords("  a knight,", TRISTAN),
                 "a knight, 1stasc, 2ndasc, 3rdasc");
  });

  test("PixAI's <lora:name:weight> token rides through untouched", () => {
    assert.equal(insertTriggerWords("portrait", ERIS),
                 "portrait, Eris_Adult, <lora:ErisV14:1>");
  });

  test("sloppy author spacing is normalised to the drawer's own ', ' join", () => {
    // The ONE deliberate departure from the button's old inline formatter, which pasted
    // the trigger_words string through verbatim (minus a trailing comma) and would have
    // produced "1stasc,2ndasc". Tokenising is what dedupe requires, and re-joining on the
    // same separator the drawer already uses between prompt and words is the consistent
    // answer -- no token's TEXT changes, only the whitespace between them.
    assert.equal(insertTriggerWords("", "1stasc,2ndasc,  3rdasc"), "1stasc, 2ndasc, 3rdasc");
  });

  test("the author's own capitalisation is what reaches the prompt", () => {
    // Matching is case-insensitive; the TEXT inserted is not lower-cased.
    assert.equal(insertTriggerWords("", "Eris_Adult"), "Eris_Adult");
  });
});

describe("a token already in the prompt is not appended a second time", () => {
  test("the whole set already present is a no-op that returns the prompt UNCHANGED", () => {
    const p = "a knight, 1stasc, 2ndasc, 3rdasc";
    assert.equal(insertTriggerWords(p, TRISTAN), p);
  });

  test("only the missing tokens are added, in the author's order", () => {
    assert.equal(insertTriggerWords("2ndasc, a knight", TRISTAN),
                 "2ndasc, a knight, 1stasc, 3rdasc");
  });

  test("dedupe ignores case", () => {
    assert.equal(insertTriggerWords("ERIS_ADULT", "Eris_Adult"), "ERIS_ADULT");
  });

  test("a prompt whose text merely CONTAINS the token still gets the token", () => {
    // The boundary rule in one assertion: "1stascension" is a different word, so the
    // LoRA's real "1stasc" is still missing and must be inserted. A naive substring
    // check would silently skip it and the LoRA would render as a no-op.
    assert.equal(insertTriggerWords("1stascension", "1stasc"), "1stascension, 1stasc");
    assert.equal(insertTriggerWords("my1stasc", "1stasc"), "my1stasc, 1stasc");
    // ...while a real boundary -- comma, space, start, end -- counts as present.
    assert.equal(insertTriggerWords("epic, 1stasc, glow", "1stasc"), "epic, 1stasc, glow");
    assert.equal(insertTriggerWords("1stasc", "1stasc"), "1stasc");
  });

  test("a token that OPENS and CLOSES on punctuation needs no word boundary", () => {
    // "<lora:ErisV14:1>" ends in '>' -- there is no word boundary to demand on either
    // side, and demanding one would make the token impossible to ever match.
    const p = "portrait, <lora:ErisV14:1>, soft light";
    assert.equal(insertTriggerWords(p, "<lora:ErisV14:1>"), p);
  });

  test("multi-word phrases match as phrases", () => {
    assert.equal(insertTriggerWords("a fairy knight tristan in armour", "Fairy Knight Tristan"),
                 "a fairy knight tristan in armour");
    assert.equal(insertTriggerWords("a fairy knight in armour", "Fairy Knight Tristan"),
                 "a fairy knight in armour, Fairy Knight Tristan");
  });

  test("duplicates WITHIN one trigger_words string collapse", () => {
    assert.equal(insertTriggerWords("", "cat, cat, CAT, dog"), "cat, dog");
  });
});

describe("a LoRA with nothing to insert never touches the prompt", () => {
  test("empty, blank, and missing trigger_words all leave the prompt byte-identical", () => {
    // Byte-identical MATTERS: this runs on every pick, including LoRAs with no triggers
    // at all, and trimming a prompt someone is mid-sentence in would eat the space they
    // just typed. The no-op path must not even normalise.
    const midSentence = "  a knight standing in ";
    for (const words of ["", "   ", ",", " , , ", undefined, null, 0, [], ["a"], {}]) {
      assert.equal(insertTriggerWords(midSentence, words), midSentence);
    }
  });

  test("splitTriggerWords answers [] for every non-string and every blank", () => {
    for (const words of ["", "  ", ",", ", ,", undefined, null, 0, false, [], ["1stasc"], {}]) {
      assert.deepEqual(splitTriggerWords(words), []);
    }
    assert.deepEqual(splitTriggerWords(TRISTAN), ["1stasc", "2ndasc", "3rdasc"]);
    assert.deepEqual(splitTriggerWords(ERIS), ["Eris_Adult", "<lora:ErisV14:1>"]);
    // Empty segments from sloppy authoring are dropped, not turned into blank tokens.
    assert.deepEqual(splitTriggerWords(" a,, b , "), ["a", "b"]);
  });

  test("a non-string prompt is treated as empty rather than throwing", () => {
    assert.equal(insertTriggerWords(undefined, "1stasc"), "1stasc");
    assert.equal(insertTriggerWords(null, "1stasc"), "1stasc");
  });
});

describe("the insert is idempotent -- pick, re-pick, or tap +words twice", () => {
  test("a second application changes nothing, on every fixture", () => {
    const prompts = ["", "a knight", "a knight, ", "2ndasc, a knight", "1stascension"];
    for (const p of prompts) {
      for (const w of [TRISTAN, ERIS, "Fairy Knight Tristan", ""]) {
        const once = insertTriggerWords(p, w);
        assert.equal(insertTriggerWords(once, w), once,
          `not idempotent for prompt ${JSON.stringify(p)} + words ${JSON.stringify(w)}`);
        // And after one pass nothing is left outstanding.
        assert.deepEqual(missingTriggerWords(once, w), []);
      }
    }
  });

  test("promptHasTrigger is exactly the predicate the insert is built on", () => {
    assert.equal(promptHasTrigger("epic, 1stasc", "1stasc"), true);
    assert.equal(promptHasTrigger("epic, 1stascension", "1stasc"), false);
    assert.equal(promptHasTrigger("epic", ""), false);
    assert.equal(promptHasTrigger(undefined, "1stasc"), false);
  });
});

describe("both composers reach the prompt through that ONE rule", () => {
  test("the shared hook auto-inserts on pick -- in BOTH of addLora's state writes", () => {
    // A picker row that already carries trigger_words and a row whose words only arrive
    // with the /api/model-version resolve are two different moments, and exactly one of
    // them fires per pick. Insert in only one and the feature silently does not happen
    // for half the LoRAs in the catalog.
    assert.match(hook, /import \{ insertTriggerWords \} from "\.\/loraTriggers\.js";/);
    const writes = hook.match(/prompt: autoInsert \? insertTriggerWords\(old\.prompt, words\) : old\.prompt,/g);
    assert.equal(writes && writes.length, 2,
      "addLora must insert on the picker-row path AND on the late version-resolve path");
  });

  test("REMIX opts out -- restoring a recipe never rewrites its prompt", () => {
    // A remix reproduces the run that made the artwork: the prompt it restores is the one
    // that actually rendered, and appending tokens the original did not use would change
    // the recipe under the owner before he re-pays for it. Auto-insert belongs to a PICK.
    assert.match(drawer, /await g\.addLora\(lr, \{ autoInsert: false \}\);/);
  });

  test("neither surface formats the insert itself", () => {
    for (const [name, src] of [["GenerateDrawer.jsx", drawer], ["CreateMobile.jsx", mobile]]) {
      assert.match(src, /import \{ insertTriggerWords \} from "\.\.\/gen\/loraTriggers\.js";/,
        name + " must import the shared rule");
      assert.match(src, /set\(\{ prompt: insertTriggerWords\(s\.prompt, l\.trigger_words\) \}\)/,
        name + "'s +words button must call the shared rule");
    }
    // The old inline formatter the +words button carried -- s.prompt.trim().replace(/,\s*$/,
    // "") assembled at the call site -- is gone. Exactly ONE inline copy of that join is
    // left in the drawer and it belongs to a different feature: insertSnip(), the saved-
    // snippet insert, which shares the JOIN but deliberately does not dedupe (inserting a
    // snippet is an explicit act each time, not an activation token that must appear once).
    // If a second copy ever reappears next to a LoRA, that is the drift this pins.
    const inline = drawer.match(/s\.prompt\.trim\(\)\.replace\(/g) || [];
    assert.equal(inline.length, 1,
      "only insertSnip may format inline; the LoRA path goes through loraTriggers.js");
    assert.match(drawer, /set\(\{ prompt: \(s\.prompt\.trim\(\) \? s\.prompt\.trim\(\)\.replace\(\/,\\s\*\$\/, ""\) \+ ", " : ""\) \+ sn \}\);/,
      "the one survivor must be the snippet insert");
  });

  test("mobile finally HAS a trigger-word control, and it is styled", () => {
    // The parity gap issue #45 names: CreateMobile.jsx never referenced trigger_words at all.
    assert.match(mobile, /l\.trigger_words \? \(/);
    assert.match(mobile, /className="cm-chipwords"/);
    assert.match(mobileCss, /\.cm-chipwords \{/);
  });

  test("both +words buttons are worded as the way BACK, not as the way in", () => {
    // The words arrive by themselves now, so the button's old "Insert: ..." title would
    // describe a job it no longer has. It is the re-insert affordance for words the user
    // deleted on purpose -- and dedupe makes a stray click a no-op, never a duplicator.
    for (const [name, src] of [["GenerateDrawer.jsx", drawer], ["CreateMobile.jsx", mobile]]) {
      assert.match(src, /Re-insert this LoRA's trigger words if you deleted them: /,
        name + "'s +words title must say it re-inserts");
    }
  });

  test("removing a LoRA does NOT strip its words back out of the prompt", () => {
    // PixAI does not strip either, and by then the prompt is the user's -- they may have
    // reworded around the tokens or reweighted them by hand. removeLora stays a pure
    // filter over s.loras and touches no other field.
    const removeLora = hook.match(/const removeLora = useCallback\([\s\S]*?\n  \}, \[\]\);/);
    assert.ok(removeLora, "removeLora not found in useGenerate.js");
    assert.equal(/prompt/.test(removeLora[0]), false,
      "removeLora must not touch the prompt");
  });
});
