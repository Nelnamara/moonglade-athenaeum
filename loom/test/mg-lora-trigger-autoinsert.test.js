import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "path";

import {
  insertTriggerWords, missingTriggerWords, promptHasTrigger, splitTriggerWords,
  removeTriggerWords, removableTriggerWords, triggerOccurrences, triggerWordSet,
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
   through that one rule instead of growing a second formatter that drifts.

   CORRECTION 2026-09-04. The first cut of this feature ruled that removing a LoRA leaves
   its words in the prompt, and pinned that with a test asserting removeLora never mentions
   the prompt. The owner, from live use: "Removing a Lora on pixai DOES remove words." The
   ruling on #45 is "matches PixAI behavior", so that was a bug with a test holding it in
   place; the un-pick now strips, on the SAME matching rule, sparing any word a still-picked
   LoRA also owns. That old test is replaced -- not deleted quietly -- by the block below. */

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
    assert.match(hook, /import \{ insertTriggerWords, removeTriggerWords \} from "\.\/loraTriggers\.js";/);
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

  test("removing a LoRA strips its words back out, through that same one rule", () => {
    // CORRECTED 2026-09-04. The first cut of #45 asserted the opposite here -- "removing a
    // LoRA does NOT strip its words, PixAI does not strip either" -- and pinned it by
    // asserting removeLora never mentions the prompt. The owner, from live use: "Removing
    // a Lora on pixai DOES remove words." The ruling on #45 is "matches PixAI behavior",
    // so his observation IS the contract and that old assertion was pinning a bug.
    const removeLora = hook.match(/const removeLora = useCallback\([\s\S]*?\n  \}, \[\]\);/);
    assert.ok(removeLora, "removeLora not found in useGenerate.js");
    assert.match(hook, /import \{ insertTriggerWords, removeTriggerWords \} from "\.\/loraTriggers\.js";/);
    assert.match(removeLora[0], /prompt: removeTriggerWords\(old\.prompt, gone\.trigger_words,/,
      "removeLora must strip the removed row's words through the shared rule");
    // keepWords is built from what SURVIVES the filter, never from the pre-removal list --
    // pass old.loras and the LoRA being removed would keep its own words alive forever.
    assert.match(removeLora[0], /loras\.map\(\(l\) => l\.trigger_words\)/,
      "keepWords must come from the REMAINING loras");
    assert.match(removeLora[0], /const loras = old\.loras\.filter\(\(l\) => l\.model_id !== modelId\);/);
    // No second formatter: the hook must not hand-roll a strip of its own.
    assert.equal(/replace\(/.test(removeLora[0]), false,
      "removeLora must not format the prompt itself; loraTriggers.js owns the rule");
  });

  test("ONE remove path serves both composers and every control that reaches it", () => {
    // The desktop x, the mobile chip x, and either picker's un-toggle all call the shared
    // hook's removeLora -- so wiring the strip there is what makes it happen on the phone
    // as well. If a surface ever grows its own filter over s.loras, this catches it.
    for (const [name, src] of [["GenerateDrawer.jsx", drawer], ["CreateMobile.jsx", mobile]]) {
      assert.equal(/loras\.filter\(/.test(src), false,
        name + " must not remove LoRAs itself -- it goes through useGenerate.removeLora");
      assert.match(src, /removeLora\(model\.model_id\)/,
        name + "'s picker un-toggle must call the shared removeLora");
    }
    // ...and the mobile chip's own x, which is the surface #45 added.
    assert.match(mobile, /onClick=\{\(\) => removeLoraChip\(l\.model_id\)\}/);
    assert.match(mobile, /const removeLoraChip = \(modelId\) => \{\s*\/\/[^\n]*\n\s*removeLora\(modelId\);/);
  });
});

describe("un-picking a LoRA takes its trigger words back out", () => {
  // The correction of 2026-09-04. GROUNDING: private/GENERATOR_SURFACE.md documents where
  // the tokens COME from (`latestVersion.extra.triggerWords`) but is silent on what the
  // site does when you drop a LoRA; the owner's live observation -- "Removing a Lora on
  // pixai DOES remove words" -- is the standard, and whole-token removal is the shape.

  test("the words a LoRA brought in leave with it", () => {
    assert.equal(removeTriggerWords("a knight, 1stasc, 2ndasc, 3rdasc", TRISTAN, ""),
                 "a knight");
    // ...and the same for the <lora:name:weight> style token, which no \b regex survives.
    assert.equal(removeTriggerWords("portrait, Eris_Adult, <lora:ErisV14:1>, soft light", ERIS, ""),
                 "portrait, soft light");
    assert.equal(removeTriggerWords("portrait, <lora:ErisV14:1>", "<lora:ErisV14:1>", ""),
                 "portrait");
    assert.equal(removeTriggerWords("<lora:ErisV14:1>, portrait", "<lora:ErisV14:1>", ""),
                 "portrait");
  });

  test("a word another picked LoRA still owns SURVIVES the removal", () => {
    // The guard the whole keepWords argument exists for: two LoRAs can share an activation
    // token, and dropping one of them must not silently disarm the other. "2ndasc" is
    // still arming the LoRA that stayed, so only the unshared tokens go.
    assert.equal(removeTriggerWords("a knight, 1stasc, 2ndasc, 3rdasc", TRISTAN, "2ndasc, glow"),
                 "a knight, 2ndasc");
    // keepWords takes the caller's own shape -- an ARRAY of the remaining rows' strings.
    assert.equal(
      removeTriggerWords("a knight, 1stasc, 2ndasc, 3rdasc", TRISTAN, ["2ndasc, x", "3rdasc"]),
      "a knight, 2ndasc, 3rdasc");
    // Sharing is matched case-insensitively, like everything else in this module.
    assert.equal(removeTriggerWords("portrait, Eris_Adult", ERIS, "ERIS_ADULT"),
                 "portrait, Eris_Adult");
    // Nothing shared -> everything the LoRA owns goes.
    assert.equal(removeTriggerWords("a knight, 1stasc", TRISTAN, ["", null, undefined]),
                 "a knight");
  });

  test("the seams close up -- start, middle and end alike", () => {
    // Cutting out of the MIDDLE is the "a, , b" case the tidy exists for.
    assert.equal(removeTriggerWords("a, 1stasc, b", "1stasc", ""), "a, b");
    // Cutting off the FRONT must not leave a leading ", ".
    assert.equal(removeTriggerWords("1stasc, a, b", "1stasc", ""), "a, b");
    // Cutting off the END must not leave a trailing ", ".
    assert.equal(removeTriggerWords("a, b, 1stasc", "1stasc", ""), "a, b");
    // Every token gone at once leaves an empty prompt, not a heap of punctuation.
    assert.equal(removeTriggerWords("1stasc, 2ndasc, 3rdasc", TRISTAN, ""), "");
    // Adjacent removals collapse to ONE separator, not one per token.
    assert.equal(removeTriggerWords("a, 1stasc, 2ndasc, b", TRISTAN, ""), "a, b");
    // Sloppy author spacing around the cut is normalised to the list's own ", ".
    assert.equal(removeTriggerWords("a,  1stasc  , b", "1stasc", ""), "a, b");
    assert.equal(removeTriggerWords("a , 1stasc,b", "1stasc", ""), "a, b");
    // A token space-separated rather than comma-separated leaves a space, not a comma --
    // the tidy repairs the seam it found, it does not impose a list on prose.
    assert.equal(removeTriggerWords("a 1stasc b", "1stasc", ""), "a b");
  });

  test("a prompt carrying none of the words comes back BYTE-identical", () => {
    // Same contract as the insert's no-op: this fires on every un-pick, including LoRAs
    // with no triggers at all, and normalising a prompt someone is mid-sentence in would
    // eat the space they just typed. Not "equal after trimming" -- identical.
    const midSentence = "  a knight standing in ";
    for (const words of [TRISTAN, ERIS, "", "   ", ",", undefined, null, 0, [], ["a"], {}]) {
      assert.equal(removeTriggerWords(midSentence, words, ""), midSentence);
    }
    // Boundary-aware, so a prompt word that merely CONTAINS a token is not butchered.
    assert.equal(removeTriggerWords("1stascension, my1stasc", TRISTAN, ""),
                 "1stascension, my1stasc");
    // Every word kept = nothing to cut = byte-identical, even though the words ARE there.
    const p = "a knight, 1stasc, 2ndasc, 3rdasc";
    assert.equal(removeTriggerWords(p, TRISTAN, TRISTAN), p);
    // A non-string prompt is treated as empty rather than throwing.
    assert.equal(removeTriggerWords(undefined, TRISTAN, ""), "");
    assert.equal(removeTriggerWords(null, TRISTAN, ""), "");
  });

  test("pick -> un-pick -> re-pick restores the words", () => {
    // The round trip, which is what an accidental un-pick costs the user: nothing.
    for (const p of ["", "a knight", "a knight, ", "1stascension", "  a knight standing in "]) {
      for (const w of [TRISTAN, ERIS, "Fairy Knight Tristan", ""]) {
        const added = insertTriggerWords(p, w);
        const back = removeTriggerWords(added, w, "");
        const again = insertTriggerWords(back, w);
        assert.equal(again, added,
          `round trip broke for prompt ${JSON.stringify(p)} + words ${JSON.stringify(w)}`);
        // The user's own writing survives the excursion -- what comes back is exactly the
        // head the insert built from (trimmed, trailing comma absorbed), nothing less. A
        // LoRA with NO triggers never touched the prompt at all, so it comes back raw.
        const expected = splitTriggerWords(w).length ? p.trim().replace(/,\s*$/, "") : p;
        assert.equal(back, expected,
          `user text lost for prompt ${JSON.stringify(p)} + words ${JSON.stringify(w)}`);
      }
    }
  });

  test("the guarantee is by CONTENT, not by byte, when the user typed a token first", () => {
    // Nothing records who typed which token -- PixAI records no such thing either -- so an
    // exact occurrence goes even if the user wrote it before ever picking the LoRA, and
    // re-picking brings it back in this module's canonical order rather than the user's.
    // Documented rather than fudged: inventing provenance would be the worse lie.
    const added = insertTriggerWords("2ndasc, a knight", TRISTAN);
    assert.equal(added, "2ndasc, a knight, 1stasc, 3rdasc");
    const back = removeTriggerWords(added, TRISTAN, "");
    assert.equal(back, "a knight");
    assert.equal(insertTriggerWords(back, TRISTAN), "a knight, 1stasc, 2ndasc, 3rdasc");
    // Removal is idempotent for the same reason the insert is: a second pass finds nothing.
    assert.equal(removeTriggerWords(back, TRISTAN, ""), back);
  });

  test("removableTriggerWords is exactly the set the removal cuts", () => {
    assert.deepEqual(removableTriggerWords("a, 1stasc, 2ndasc", TRISTAN, ""),
                     ["1stasc", "2ndasc"]);          // 3rdasc is not in the prompt
    assert.deepEqual(removableTriggerWords("a, 1stasc, 2ndasc", TRISTAN, "2ndasc"),
                     ["1stasc"]);                     // 2ndasc is still arming another LoRA
    assert.deepEqual(removableTriggerWords("a knight", TRISTAN, ""), []);
    assert.deepEqual(removableTriggerWords("a, 1stasc", undefined, ""), []);
  });

  test("triggerWordSet unions the remaining rows' strings, case-folded", () => {
    assert.deepEqual([...triggerWordSet(["1stasc, 2ndasc", "2ndasc, ERIS_Adult"])],
                     ["1stasc", "2ndasc", "eris_adult"]);
    assert.deepEqual([...triggerWordSet(TRISTAN)], ["1stasc", "2ndasc", "3rdasc"]);
    for (const bad of ["", null, undefined, [], [null, ""], 0, {}]) {
      assert.deepEqual([...triggerWordSet(bad)], []);
    }
  });

  test("the insert and the removal match on ONE rule, not two", () => {
    // promptHasTrigger is now the occurrence finder asked as a yes/no -- the dedupe and
    // the strip cannot disagree about what counts as a match, which is the whole reason
    // this module exists. Assert they answer together on the awkward cases.
    for (const [p, t] of [["epic, 1stasc", "1stasc"], ["epic, 1stascension", "1stasc"],
                          ["a<lora:ErisV14:1>b", "<lora:ErisV14:1>"],
                          ["a fairy knight tristan", "Fairy Knight Tristan"],
                          ["my1stasc", "1stasc"], ["epic", "1stasc"]]) {
      assert.equal(promptHasTrigger(p, t), triggerOccurrences(p, t).length > 0);
      // Present <=> the removal changes something; absent <=> byte-identical.
      assert.equal(removeTriggerWords(p, t, "") !== p, promptHasTrigger(p, t),
        `insert and removal disagree on ${JSON.stringify(p)} / ${JSON.stringify(t)}`);
    }
    assert.deepEqual(triggerOccurrences("epic, 1stasc, 1stasc", "1stasc"), [[6, 12], [14, 20]]);
    assert.deepEqual(triggerOccurrences("epic, 1stascension", "1stasc"), []);
    // EVERY occurrence goes, not just the first.
    assert.equal(removeTriggerWords("epic, 1stasc, glow, 1stasc", "1stasc", ""), "epic, glow");
  });
});
