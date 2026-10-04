import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* Where the Broken files list lives and how you get to it (Session W, W1a / W2a). Source-level,
   the established pattern for wiring in this runner (no jsdom/React harness here). */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");
const code = (rel) => src(rel).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("desktop: a section inside Health (W1a)", () => {
  test("under the tiles, above the storage bars, only when the last check found broken rows", () => {
    const h = code("components/HealthOverlay.jsx");
    const tiles = h.indexOf('className="mgh-stats"');
    const section = h.indexOf("<BrokenFiles ");
    const bars = h.indexOf("<StorageBars ");
    assert.ok(tiles >= 0 && section > tiles && bars > section, "order: tiles, Broken files, storage bars");
    assert.match(h, /bfShown \? \(\s*<BrokenFiles /, "drawn only while the list has rows");
    assert.match(h, /counts\.all > 0/);
  });
  test("a problem tile opens the list at its chip", () => {
    const h = code("components/HealthOverlay.jsx");
    assert.match(h, /TILE_CHIP\[st\.label\]/);
    assert.match(h, /onClick=\{\(\) => openBroken\(chip\)\}/);
    assert.match(h, /scrollIntoView/);
  });
  test("the Control Panel's Verify row says what it found and opens the list at All", () => {
    const c = code("components/ControlPanelOverlay.jsx");
    assert.match(c, /key === "verify-library" && brokenReview/);
    assert.match(c, /openBrokenFiles\("all"\)/);
    const a = code("App.jsx");
    assert.match(a, /registerBrokenFilesOpener\(\(\) => setOverlay\("health"\)\)/);
    assert.match(a, /onOpenDetails=\{\(mid\) => \{ setOverlay\(null\); openDetails\(mid\); \}\}/);
  });
});

describe("rows (W2a) and LOST (W5a)", () => {
  test("a row's action comes from rowAction, so a LOST row never offers a re-download", () => {
    const b = code("components/BrokenFiles.jsx");
    assert.match(b, /rowAction\(row, bf\.readOnly\)/);
    assert.match(b, /ACTION_LABEL\[act\]/);
    assert.doesNotMatch(b, /Re-download</, "the button's word comes from ACTION_LABEL only");
  });
  test("⋯ holds Open details · Mark lost · Copy path; a LOST row offers Open details · Keep as is", () => {
    const b = code("components/BrokenFiles.jsx");
    const menu = b.slice(b.indexOf('className="mgbf-pop"'));
    for (const word of ["Open details", "Mark lost", "Copy path"]) assert.ok(menu.includes(">" + word + "<"), word);
    assert.match(b, /bf\.mark\(mid, "kept"/);
    assert.match(b, />Keep as is</);
  });
  test("Mark lost is the Session N toast with Undo", () => {
    const b = code("components/BrokenFiles.jsx");
    assert.match(b, /<CurateToast toast=\{bf\.toast\} onUndo=\{bf\.undo\}/);
    const hook = code("hooks/useBrokenFiles.js");
    assert.match(hook, /UNDO_MS/);
    assert.match(hook, /mark: t\.prev\.mark/, "Undo sends back the mark the row had before");
  });
  test("no ruby, no 'corrupt'", () => {
    const css = src("styles/broken-files.css").replace(/\/\*[\s\S]*?\*\//g, "");
    assert.doesNotMatch(css, /--red|ruby|#f38ba8/i);
    for (const f of ["components/BrokenFiles.jsx", "hooks/useBrokenFiles.js", "lib/brokenFixRun.js"]) {
      assert.doesNotMatch(code(f), /corrupt/i, f);
    }
  });
});
