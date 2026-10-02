import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { remixPatch } from "../../gallery/src/gen/phoneRemix.js";
import {
  escapeLiteral, forcesNoCard, parse, planJobs, sendRoute,
} from "../../gallery/src/gen/templateCore.js";

/* The seam between the phone's Remix (Session Q) and the template rule the Generate power tools fix
   round changed (the S1 ruling): a {...} group is a variable ONLY when it holds a top-level |, a
   brace group without one is literal text sent as typed, a backslash is consumed only where it
   changes the parse, and a prompt with no | group and no __name__ token resolves to itself.

   A Remix of an ordinary picture puts its RECORDED prompt into the Create form through
   remixPatch -> escapeLiteral. This file pins that what the form would then SEND (parse, then
   resolve with the shared expander, one send) is the recorded prompt, byte for byte. If a case
   here ever fails the fix belongs in the Remix code (phoneRemix.js / templateCore.escapeLiteral),
   never in this list. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const read = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");
const codeOnly = (t) => t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

/* What the Create form sends for a Remix of a plain picture whose recorded prompt is `recorded`:
   the patch the phone applies, then the composer's own expansion of it in Random mode, count 1
   (no lists: a recorded prompt is never a request to read the account's lists). */
function sentAfterRemix(recorded, lists) {
  const { patch, source } = remixPatch({ prompt_full: recorded }, null, {});
  assert.equal(source, "recorded");
  const plan = planJobs(patch.prompt, lists || {}, "random", 1, 0);
  assert.equal(plan.error, undefined, "the remixed prompt must not be refused: " + JSON.stringify(recorded));
  assert.equal(plan.jobs.length, 1, "one send: " + JSON.stringify(recorded));
  assert.equal(plan.mode, "single");
  return { sent: plan.jobs[0].prompt, patchPrompt: patch.prompt, plan };
}

const TRICKY = [
  ["an empty string", ""],
  ["plain text", "1girl, solo, long_hair, looking at viewer"],
  ["emphasis braces", "{masterpiece}, 1girl"],
  ["emphasis braces, doubled", "{{best quality}}, {{{highres}}}, 1girl"],
  ["a | inside braces", "a {red|blue} door"],
  ["a | inside braces at both ends", "{a|b}"],
  ["two | groups", "{a|b} and {c|d|e}"],
  ["a | group beside an emphasis group", "{masterpiece}, {red|blue} hair"],
  ["an empty option", "{a|} x"],
  ["nested braces, no pipe", "{a {b} c}"],
  ["nested braces, pipe outside", "{a {b} c|d}"],
  ["nested braces, pipe inside", "{a|{b|c}}"],
  ["nested braces, pipe in the inner", "{a {b|c} d}"],
  ["an unclosed brace", "a { b"],
  ["an unclosed brace with a | after it", "a { b | c"],
  ["a stray closing brace", "a } b"],
  ["a stray closing brace after a group", "{a|b} }"],
  ["unclosed after a closed pair", "{masterpiece} {open | more"],
  ["a backslash before a brace", "a \\{b\\} c"],
  ["a backslash before a | group's braces", "a \\{b|c\\} d"],
  ["a backslash before only the closing brace of a | group", "{b|c\\} d"],
  ["a backslash before only the opening brace of a | group", "a \\{b|c}"],
  ["a backslash before an unclosed brace with a |", "a \\{ b | c"],
  ["a backslash-underscore kaomoji", "(\\_/) cute, \\_(:3」∠)_"],
  ["a backslash-underscore kaomoji beside a list-shaped token", "\\_(ツ)_/¯ __x__"],
  ["a shrug that is not a token", "¯\\_(ツ)_/¯"],
  ["a list token", "a __colours__ scene"],
  ["a list token, twice", "__a__ and __b__"],
  ["a list token with a backslash before it", "a \\__name__ b"],
  ["a list token with two backslashes before it", "a \\\\__name__ b"],
  ["a list token beside underscores", "___name___ and long__word__here"],
  ["underscores that are not a token", "long_hair, __, ___, a__b, __A__, __ x __"],
  ["a token inside braces", "{__colours__}"],
  ["a token inside a | group", "{__colours__|red}"],
  ["a lone backslash", "\\"],
  ["backslashes in a row", "a \\\\ b \\\\\\ c"],
  ["a trailing backslash", "1girl, \\"],
  ["unicode", "少女, ヴァイオレット・エヴァーガーデン, café, ñandú"],
  ["emoji", "1girl 🌙✨ {glow|shine} 👩‍👩‍👧"],
  ["a curly-quoted emphasis", "“{masterpiece}” — ‘quality’"],
  ["a weight syntax", "(masterpiece:1.2), [lowres], <lora:moonlit:0.7>"],
  ["whitespace and newlines kept as they are", "  a\n\t{b|c}\r\n  d  "],
  ["a long mixed prompt", "masterpiece, {best quality|high} \\{x\\} __name__ (\\_/) {a {b|c}} { open | {d} } }"],
];

describe("Remix of a recorded prompt: what the Create form sends is the recorded prompt, byte for byte", () => {
  for (const [name, recorded] of TRICKY) {
    test(name, () => {
      const { sent } = sentAfterRemix(recorded);
      assert.equal(sent, recorded);
    });
  }

  test("a prompt with no | group and no __name__ token gets no backslash at all (the old escaping put them in)", () => {
    for (const recorded of ["{masterpiece}, 1girl", "{{a}} {b {c} d} { open } }", "long_hair \\_/ (\\_/)", "a { b", "a } b", ""]) {
      assert.equal(escapeLiteral(recorded), recorded);
      assert.equal(remixPatch({ prompt_full: recorded }, null, {}).patch.prompt, recorded);
    }
  });

  test("the escaped prompt is never refused and carries no variable, whatever was recorded", () => {
    for (const [, recorded] of TRICKY) {
      const P = parse(escapeLiteral(recorded), {});
      assert.equal(P.error, null, JSON.stringify(recorded));
      assert.equal(P.vars.length, 0, JSON.stringify(recorded));
    }
  });

  test("the recorded prompt survives with the account's lists present too (a list token is escaped, not read)", () => {
    const lists = { colours: ["red", "blue"], name: ["n"], a: ["1"], b: ["2"], x: ["y"] };
    for (const [, recorded] of TRICKY) {
      assert.equal(sentAfterRemix(recorded, lists).sent, recorded);
    }
  });

  test("every recorded-prompt field the phone reads is escaped: prompt_full, else prompt_preview", () => {
    assert.equal(sentAfterRemix("{a|b} __x__").sent, "{a|b} __x__");
    const viaPreview = remixPatch({ prompt_preview: "{a|b} __x__" }, null, {}).patch.prompt;
    assert.equal(planJobs(viaPreview, {}, "random", 1, 0).jobs[0].prompt, "{a|b} __x__");
    assert.equal(planJobs(remixPatch({}, null, {}).patch.prompt, {}, "random", 1, 0).jobs[0].prompt, "");
  });

  test("a seeded sweep of brace, pipe, backslash and underscore soup round-trips too", () => {
    const alphabet = ["{", "}", "|", "\\", "_", "__", "a", "b", " ", "x_y", "__n__", "(", ")"];
    let seed = 20260929;
    const next = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed; };
    for (let k = 0; k < 4000; k++) {
      const len = next() % 14;
      let recorded = "";
      for (let j = 0; j < len; j++) recorded += alphabet[next() % alphabet.length];
      assert.equal(sentAfterRemix(recorded).sent, recorded, JSON.stringify(recorded));
    }
  });
});

describe("the phone's Remix has no escaping of its own", () => {
  test("phoneRemix.js takes escapeLiteral from the shared templateCore.js and defines no escape", () => {
    const code = codeOnly(read("gen/phoneRemix.js"));
    assert.match(code, /import\s*\{[^}]*\bescapeLiteral\b[^}]*\}\s*from\s*"\.\/templateCore\.js"/);
    assert.equal(/function\s+\w*escape\w*/i.test(code), false, "no escape function of its own");
    assert.equal(/=>\s*[^;\n]*\.replace\(\s*\/[^/\n]*[{}_\\][^/\n]*\/g/.test(code), false, "no regex escaping of braces or underscores");
    assert.equal(/\\\\\{|"\\\\"\s*\+|\\\\\$&/.test(code), false, "no hand-built backslash insertion");
  });

  test("the desktop dock's Remix uses the same shared escapeLiteral, and nothing else in the phone code escapes", () => {
    const dock = codeOnly(read("components/GenerateDrawer.jsx"));
    assert.match(dock, /import\s*\{[^}]*\bescapeLiteral\b[^}]*\}\s*from\s*"\.\.\/gen\/templateCore\.js"/);
    for (const rel of ["gen/phoneRemix.js", "components/CreateMobile.jsx", "components/GalleryMobile.jsx",
      "components/ImageDetailsMobile.jsx", "components/LightboxMobile.jsx", "components/PlacardMobile.jsx",
      "lib/phoneCore.js"]) {
      const code = codeOnly(read(rel));
      assert.equal(/function\s+\w*escape\w*\s*\(/i.test(code), false, rel + " defines its own escape");
    }
  });
});

describe("Remix of a picture from a power tools run restores its TEMPLATE, unchanged", () => {
  test("the template is filled in as recorded: no escaping, the run's own mode, count and seed", () => {
    const tpl = "a {red|blue} door, {masterpiece}, __colours__";
    const r = remixPatch({ prompt_full: "a red door, {masterpiece}, red" },
      { template: tpl, var_mode: "random", count: 3, run_seed: 42, dock_seed: "" }, { roll: 9 });
    assert.equal(r.source, "template");
    assert.equal(r.patch.prompt, tpl);
    assert.equal(r.patch.varMode, "random");
    assert.equal(r.patch.count, 3);
  });
});

describe("a Remix of a Matrix run never leaves a one-cell matrix charged without a confirm", () => {
  const remixState = (template, lists) => {
    const { patch } = remixPatch({ prompt_full: "resolved text" },
      { template, var_mode: "matrix", count: 4, run_seed: 5, dock_seed: "" }, {});
    // the composer state after g.set(patch), then what useGenerate derives from it
    const s = { prompt: patch.prompt, varMode: patch.varMode, count: 1 };
    const plan = planJobs(s.prompt, lists || {}, s.varMode, 1, 0);
    return { s, plan, route: sendRoute(plan, parse(s.prompt, lists || {}).syntax) };
  };

  test("a matrix of 2 or more cells is a confirm-first send priced with no free card", () => {
    const { plan, route } = remixState("{a|b} {c|d}");
    assert.equal(plan.jobs.length, 4);
    assert.equal(route, "confirm");
    assert.equal(forcesNoCard(plan), true);
  });

  test("a one-cell matrix (a one-item list) is an ordinary single send: no_card is not forced, and the two agree", () => {
    const { plan, route } = remixState("a __one__ door", { one: ["red"] });
    assert.equal(plan.mode, "matrix");
    assert.equal(plan.jobs.length, 1);
    assert.equal(forcesNoCard(plan), false);
    assert.notEqual(route, "confirm");
  });

  test("whenever the send forces no card, the route is the confirm (never a one-shot /generate or /run)", () => {
    for (const t of ["{a|b}", "{a|b} {c|d} {e|f}", "{a|b} __one__", "__one__", "x", "{a|a}", "{a|b} {"]) {
      const { plan, route } = remixState(t, { one: ["1"] });
      if (forcesNoCard(plan)) assert.equal(route, "confirm", t);
    }
  });

  test("the phone's own gate refuses a matrix left in the shared dock state, before any send", () => {
    const code = codeOnly(read("components/CreateMobile.jsx"));
    assert.match(code, /s\.varMode === "matrix"\s*&&\s*run\s*&&\s*run\.parsed\s*&&\s*run\.parsed\.syntax/);
    assert.match(code, /Setting up a Matrix is desktop-only/);
  });
});
