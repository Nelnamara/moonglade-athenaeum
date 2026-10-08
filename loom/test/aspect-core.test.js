import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  AR_ERROR, ASPECT_CHOICES, OPERATOR_CHIPS, parseAspect, aspectIn, withAspect, aspectError,
  aspectSuggestions, applySuggestion, ratioLabel, hasToken, toggleToken,
} from "../../gallery/src/curation/aspectCore.js";

/* Session N7, the client half of the ar: operator. The FILTERING is the server's (see
   dev/tests/test_aspect_and_storage.py); these pin what the screens decide around it: which values
   are valid, the Aspect field's round trip through the search text, the suggestions while typing,
   the operator chips, and the label a card draws for its own shape. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

describe("which values are valid", () => {
  // the SAME table dev/tests/test_aspect_and_storage.py runs against the server: the two must agree
  const GOOD = ["square", "portrait", "landscape", "tall", "wide", "TALL", "3:2", "9:16", "1.91:1",
    "1.5:1", ">2", "<0.5", ">.5", ">1.7"];
  const BAD = ["", "banana", "0:0", "3:", ":3", "1:0", "0:1", ">", "<", ">x", "3:2:1", "tall ", "=2", ">=2"];
  test("the accepted forms", () => {
    for (const v of GOOD.filter((x) => x !== "tall ")) assert.equal(parseAspect(v).ok, true, v);
    assert.equal(parseAspect(" tall ").ok, true);      // trimmed, the server trims too
  });
  test("the refused forms", () => {
    for (const v of BAD.filter((x) => x !== "tall ")) assert.equal(parseAspect(v).ok, false, JSON.stringify(v));
  });
  test("what a value parses to", () => {
    assert.deepEqual(parseAspect("3:2"), { ok: true, kind: "ratio", w: 3, h: 2, value: "3:2" });
    assert.equal(parseAspect(">2").kind, "gt");
    assert.equal(parseAspect("<0.5").n, 0.5);
    assert.equal(parseAspect("Square").kind, "square");
  });
});

describe("the Aspect field's round trip through the search text", () => {
  test("reads the value the search holds", () => {
    assert.equal(aspectIn("night ar:tall"), "tall");
    assert.equal(aspectIn("ar:3:2 keeper"), "3:2");
    assert.equal(aspectIn("night"), "");
    assert.equal(aspectIn("-ar:tall"), "");                  // a negation is not a chosen shape
    assert.equal(aspectIn("ar:banana"), "");                 // not one the field can show
    assert.equal(aspectIn('"ar:tall" night'), "");           // inside a phrase: just words
  });
  test("sets, replaces and clears it, leaving everything else", () => {
    assert.equal(withAspect("night keeper", "tall"), "night keeper ar:tall");
    assert.equal(withAspect("ar:tall night", "wide"), "night ar:wide");
    assert.equal(withAspect("ar:tall night ar:square", "wide"), "night ar:wide");
    assert.equal(withAspect("ar:tall night", ""), "night");
    assert.equal(withAspect("", "square"), "ar:square");
    assert.equal(withAspect("-ar:tall night", "wide"), "-ar:tall night ar:wide");   // the negation stays
    assert.equal(withAspect('"a b" ar:wide', "tall"), '"a b" ar:tall');
  });
  test("aspect: is the same operator", () => {
    assert.equal(aspectIn("aspect:wide"), "wide");
    assert.equal(withAspect("aspect:wide", "tall"), "ar:tall");
  });
});

describe("a typo is said, not silently searched", () => {
  test("an ar: nobody understands names the accepted forms", () => {
    assert.equal(aspectError("night ar:banana"), AR_ERROR);
    assert.equal(aspectError("-ar:0:0"), AR_ERROR);
    assert.match(AR_ERROR, /W:H, square, portrait, landscape, tall, wide, >N or <N/);
  });
  test("the token still being typed is left alone until it has been searched", () => {
    assert.equal(aspectError("ar:ta", { ignoreLast: true }), "");
    assert.equal(aspectError("night ar:1:", { ignoreLast: true }), "");
    assert.equal(aspectError("ar:banana ", { ignoreLast: true }), AR_ERROR);          // finished with a space
    assert.equal(aspectError("ar:banana night", { ignoreLast: true }), AR_ERROR);      // not the last token
    assert.equal(aspectError("ar:banana", { ignoreLast: false }), AR_ERROR);           // searched: say so
    assert.equal(aspectError("ar:banana"), AR_ERROR);
  });
  test("a good one, a half-typed one and no ar: at all are quiet", () => {
    assert.equal(aspectError("ar:tall"), "");
    assert.equal(aspectError("ar:"), "");                    // still being typed
    assert.equal(aspectError("night ar:>2 keeper"), "");
    assert.equal(aspectError("banana"), "");
    assert.equal(aspectError(""), "");
  });
});

describe("suggestions while typing", () => {
  test("after ar: it offers the values, filtered by what is typed", () => {
    const all = aspectSuggestions("ar:").map((s) => s.token);
    assert.deepEqual(all.slice(0, 5), ["ar:square", "ar:portrait", "ar:landscape", "ar:tall", "ar:wide"]);
    assert.deepEqual(aspectSuggestions("ar:t").map((s) => s.token), ["ar:tall"]);
    assert.deepEqual(aspectSuggestions("ar:1").map((s) => s.token), ["ar:1:1", "ar:16:9"]);
    assert.deepEqual(aspectSuggestions("ar:1:1"), []);        // already exactly that
  });
  test("a bare 'ar' offers them too, and a negation keeps its minus", () => {
    assert.ok(aspectSuggestions("night ar").length > 0);
    assert.deepEqual(aspectSuggestions("-ar:w").map((s) => s.token), ["-ar:wide"]);
  });
  test("nothing for other words, a finished word, or a trailing space", () => {
    assert.deepEqual(aspectSuggestions("night"), []);
    assert.deepEqual(aspectSuggestions("a"), []);            // one letter is just a letter
    assert.deepEqual(aspectSuggestions("ar:tall "), []);
    assert.deepEqual(aspectSuggestions(""), []);
  });
  test("picking one replaces only the last token and leaves a space to keep typing", () => {
    assert.equal(applySuggestion("night ar:t", "ar:tall"), "night ar:tall ");
    assert.equal(applySuggestion("ar", "ar:wide"), "ar:wide ");
  });
});

describe("the operator chips", () => {
  test("a chip toggles its token", () => {
    assert.equal(toggleToken("night", "keeper"), "night keeper");
    assert.equal(toggleToken("night keeper", "keeper"), "night");
    assert.equal(hasToken("night KEEPER", "keeper"), true);
    assert.equal(hasToken("nightkeeper", "keeper"), false);
  });
  test("ar: chips are exclusive: a picture has one shape", () => {
    assert.equal(toggleToken("ar:tall", "ar:wide"), "ar:wide");
    assert.equal(toggleToken("ar:wide", "ar:wide"), "");
    assert.equal(toggleToken("night ar:square keeper", "ar:tall"), "night keeper ar:tall");
  });
  test("the chips are all real operators", () => {
    for (const c of OPERATOR_CHIPS) assert.ok(/^(-?)(ar:|type:|★|keeper|reject)/.test(c), c);
    assert.ok(OPERATOR_CHIPS.includes("ar:tall") && OPERATOR_CHIPS.includes("ar:wide"));
  });
  test("every Aspect choice is a valid value", () => {
    for (const c of ASPECT_CHOICES) assert.equal(parseAspect(c.value).ok, true, c.value);
  });
});

describe("the label a card draws", () => {
  test("the named shapes", () => {
    assert.equal(ratioLabel(1024, 1024), "1:1");
    assert.equal(ratioLabel(1536, 1024), "3:2");
    assert.equal(ratioLabel(1000, 1500), "2:3");
    assert.equal(ratioLabel(832, 1216), "9:13");             // the page's own name for 0.684
    assert.equal(ratioLabel(1920, 1080), "16:9");
    assert.equal(ratioLabel(576, 1024), "9:16");
    assert.equal(ratioLabel(1250, 1000), "5:4");
    assert.equal(ratioLabel(2048, 1024), "2:1");
  });
  test("text sizes, as the catalog stores them", () => {
    assert.equal(ratioLabel("1216", "832"), "3:2");           // 1.46: near enough to 3:2
  });
  test("a shape with no name shows its ratio, and no size shows nothing", () => {
    assert.equal(ratioLabel(1100, 1000), "1.10:1");
    assert.equal(ratioLabel("", ""), "");
    assert.equal(ratioLabel(0, 800), "");
    assert.equal(ratioLabel("abc", "800"), "");
  });
});

describe("the screens use it", () => {
  test("the flyout has the Aspect field and reads and writes the ar: token", () => {
    const fly = src("components/Flyout.jsx");
    assert.match(fly, /Aspect/);
    assert.match(fly, /aspectIn\(/);
    assert.match(fly, /withAspect\(/);
    assert.match(fly, /<code>ar:tall<\/code>/);
  });
  test("the search fields offer the suggestions", () => {
    assert.match(src("components/FiltersPanel.jsx"), /aspectSuggestions\(/);
  });
  test("the phone's Advanced Search has the Aspect chip row", () => {
    const g = src("components/GalleryMobile.jsx");
    assert.match(g, /ASPECT_CHOICES/);
    assert.match(g, /withAspect\(/);
  });
});
