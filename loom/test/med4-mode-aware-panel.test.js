import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { usesCloseFrame } from "../src/loom-core.js";

/* MODE-AWARE CAST/REF PANEL (2026-07-27, round 3).

   Round 2's "N of M reference slots used" budget line and its live-tag tooltip ("this is
   what the composed prompt and the generator actually send") rendered for EVERY mode.
   But only R2V/V2V generations take the reference bank: an FLF generation consumes the
   two frames alone and an I2V generation only the opening frame -- on an I2V shot the
   panel asserted two cast members were "sent". Refuted in adversarial review.

   The repair derives the mode family from usesCloseFrame/CLOSE_FRAME_MODES plus the mode
   itself (modeSendsRefs -- NEVER a second mode table), keeps the live @imageN visible in
   every mode (shotText cites cast/refs by position regardless of mode -- the number IS
   the composed prompt's citation), and words the claim per family: "not sent" becomes
   "not cited" on FLF/I2V, tooltips stop claiming send-ness there, and the budget
   arithmetic is replaced by an honest one-liner.

   The helpers are plain consts in the JSX, so they are EXTRACTED and executed here
   against the real usesCloseFrame -- behavior, not just source shape. Extraction
   pattern and its rationale: med-mg-generate-drawer-mode-carry.test.js. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8")
  .replace(/\r\n/g, "\n");   // working trees on this machine can be CRLF; every pattern below assumes LF

function extractConst(name) {
  // Arrow consts at the component's 2-space indent; a single-expression body ends with
  // ";" at end-of-line, the block-bodied liveTagTitle with "\n  };".
  const m = jsx.match(new RegExp("\\n  const " + name + " = \\([^)]*\\) =>(?: \\{[\\s\\S]*?\\n  \\};|[\\s\\S]*?;)(?=\\n)"));
  assert.ok(m, `expected to find "const ${name} = (...) =>" in master-storyboard.jsx -- ` +
    `round 2 had no mode-family helpers at all; if renamed/moved, update this pattern`);
  return m[0];
}

const helpers = new Function("usesCloseFrame", `
  ${extractConst("modeSendsRefs")}
  ${extractConst("modeSendsLine")}
  ${extractConst("liveTagText")}
  ${extractConst("liveTagTitle")}
  return { modeSendsRefs, modeSendsLine, liveTagText, liveTagTitle };
`)(usesCloseFrame);

describe("modeSendsRefs -- derived from usesCloseFrame, never a second mode table", () => {
  test("R2V and V2V send the reference bank; FLF and I2V do not", () => {
    assert.equal(helpers.modeSendsRefs("R2V"), true);
    assert.equal(helpers.modeSendsRefs("V2V"), true);
    assert.equal(helpers.modeSendsRefs("FLF"), false, "an FLF generation consumes only the two frames");
    assert.equal(helpers.modeSendsRefs("I2V"), false, "an I2V generation consumes only the opening frame");
    assert.equal(helpers.modeSendsRefs(undefined), false, "a stale/absent mode claims nothing");
  });

  test("the derivation really rides usesCloseFrame -- no independent list in the JSX", () => {
    const src = extractConst("modeSendsRefs");
    assert.match(src, /usesCloseFrame\(m\)/,
      "modeSendsRefs must derive from the exported predicate -- an independent mode " +
      "list here is the two-numbering-systems drift class all over again");
    assert.ok(!/\[\s*"/.test(src), "no array-literal mode table inside modeSendsRefs");
  });
});

describe("live-tag labels stop claiming send-ness on FLF/I2V", () => {
  test("a live tag passes through unchanged in every mode (it IS the prompt's citation)", () => {
    for (const mode of ["R2V", "V2V", "FLF", "I2V"]) {
      assert.equal(helpers.liveTagText("@image3", false, mode), "@image3", mode);
    }
  });

  test("past-budget reads 'not sent' only where sending is real; 'not cited' elsewhere", () => {
    assert.equal(helpers.liveTagText(null, true, "R2V"), "not sent");
    assert.equal(helpers.liveTagText(null, true, "V2V"), "not sent");
    assert.equal(helpers.liveTagText(null, true, "FLF"), "not cited",
      "nothing cast-shaped is sent on FLF either way -- the only thing lost past the " +
      "cap is the composed prompt's citation");
    assert.equal(helpers.liveTagText(null, true, "I2V"), "not cited");
  });

  test("no picture still reads as a plain dash, never a warning", () => {
    assert.equal(helpers.liveTagText(null, false, "R2V"), "—");
    assert.equal(helpers.liveTagText(null, false, "I2V"), "—");
  });

  test("tooltips: 'actually send' is exclusive to the sending modes", () => {
    assert.match(helpers.liveTagTitle("@image2", false, "R2V", "A·01"), /actually send/);
    assert.match(helpers.liveTagTitle("@image2", false, "V2V", "A·01"), /actually send/);
    for (const mode of ["FLF", "I2V"]) {
      const t = helpers.liveTagTitle("@image2", false, mode, "A·01");
      assert.ok(!/actually send/.test(t), `${mode} tooltip must not claim send-ness: ${t}`);
      assert.match(t, /NOT attached/, `${mode} tooltip must say the picture is not attached`);
      assert.match(t, /citation/, `${mode} tooltip must frame the number as the prompt's citation`);
    }
    assert.match(helpers.liveTagTitle("@image2", false, "FLF", "A·01"), /start\/end frames/);
    assert.match(helpers.liveTagTitle("@image2", false, "I2V", "A·01"), /opening frame/);
  });

  test("past-budget tooltips split the same way", () => {
    assert.match(helpers.liveTagTitle(null, true, "R2V", "A·01"), /not sent/);
    const flf = helpers.liveTagTitle(null, true, "FLF", "A·01");
    assert.ok(!/— not sent/.test(flf), "FLF past-budget tooltip must not end on a send claim");
    assert.match(flf, /left out of the composed prompt/);
  });
});

describe("the budget line is gated to the modes whose arithmetic is true", () => {
  test("the honest one-liners say exactly what each mode sends", () => {
    assert.match(helpers.modeSendsLine("I2V"), /I2V sends the opening frame only/);
    assert.match(helpers.modeSendsLine("I2V"), /not references/);
    assert.match(helpers.modeSendsLine("FLF"), /start & end frames only/);
    assert.match(helpers.modeSendsLine("FLF"), /not references/);
  });

  test("the castList budget IIFE checks modeSendsRefs BEFORE doing slot arithmetic", () => {
    const block = jsx.match(/\{sel && \(\(\) => \{[\s\S]*?refBudget\(sel, project, imgSrc\)/);
    assert.ok(block, "could not locate the Cast & assets budget block");
    assert.match(block[0], /if \(!modeSendsRefs\(sel\.c\.mode\)\)/,
      "round 2 rendered '<used> of <budget> reference slots used' unconditionally -- " +
      "on an I2V shot that asserted cast members were consuming slots of a generation " +
      "that sends the opening frame alone");
    assert.match(block[0], /modeSendsLine\(sel\.c\.mode\)/,
      "the non-sending branch must render the shared honest one-liner");
  });

  test("both cast-row surfaces route wording through the shared helpers", () => {
    assert.match(jsx, /title=\{liveTagTitle\(liveTag, pastBudget, sel\.c\.mode, sel\.code\)\}[\s\S]{0,80}liveTagText\(liveTag, pastBudget, sel\.c\.mode\)/,
      "the detailed cast row must use liveTagTitle/liveTagText -- inline strings are " +
      "how round 2's mode-blind claim shipped");
    const simple = jsx.match(/lv-simplegrid[\s\S]*?lv-addcast/);
    assert.ok(simple, "could not locate the Simple grid (lv-simplegrid ... lv-addcast)");
    assert.match(simple[0], /liveTagTitle\(liveTag, pastBudget, sel\.c\.mode, sel\.code\)/,
      "the Simple grid's tag must carry the same mode-aware tooltip");
  });
});
