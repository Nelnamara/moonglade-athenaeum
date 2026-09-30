import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The Folio for completionists' wiring, pinned at the source (Session O, O1-O3; Small Calls L2).
   The components are React and this suite has no renderer, so what is asserted here is the shape
   of the wiring the pure core (folio-completionist-core.test.js) cannot see: that no denominator
   in either Folio adds the feats' count (drift 110), that the "N to go" and the jump can only be
   drawn through the core's own answers (which are null for a feat), that the sort is read once
   and written only on a click, and that the relic rows are the earned-only rows. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");
const code = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const hook = src("hooks/useFolio.js");
const desk = src("components/FolioOverlay.jsx");
const phone = src("components/FolioMobile.jsx");
const app = src("App.jsx");

describe("drift 110: feats are in no denominator", () => {
  test("neither Folio adds the feats' count to the honors total", () => {
    for (const [name, file] of [["desktop", desk], ["phone", phone]]) {
      const c = code(file);
      assert.match(c, /const grandTotal = vm \? vm\.totalNonFeat : 0;/, name);
      assert.ok(!/totalNonFeat\s*\+/.test(c), name + " adds to the total");
      assert.ok(!/totalFeats/.test(c), name + " reads the feats' total");
      assert.ok(!/feats_revealed \? vm\.totalFeats/.test(c), name);
    }
  });

  test("the header's record N of M and the Earned tile use that total", () => {
    const c = code(desk);
    assert.match(c, /record \{fmt\(vm\.earnedNonFeat\)\} of \{fmt\(grandTotal\)\}/);
    assert.match(c, /of \{fmt\(grandTotal\)\} honors/);
  });

  test("the meter is completionOf over the payload's achievements, and its line is the core's", () => {
    assert.match(code(hook), /completionOf\(data\.achievements\)/);
    assert.match(code(desk), /meterLine\(meter\)/);
    assert.match(code(desk), /style=\{\{ width: meter\.pct \+ "%" \}\}/);
  });

  test("no hook or component builds a total from the feats bucket", () => {
    for (const file of [hook, desk, phone]) {
      const c = code(file);
      assert.ok(!/earnedFeats\s*\/|\/\s*vm\.totalFeats|totalFeats\s*\)/.test(c));
    }
  });
});

describe("O1: N to go, only through the core", () => {
  test("a card's count and jump come from progressOf / jumpOf, which are null for a feat", () => {
    const c = code(desk);
    assert.match(c, /const prog = progressOf\(a\);/);
    assert.match(c, /const jump = jumpOf\(a\);/);
    assert.match(c, /\{prog && \(/);
    assert.match(c, /\{jump && onJump && \(/);
    assert.match(c, /fraction=\{prog\.fraction\}/);
  });

  test("Within reach measures only honors with a count, and draws the moon on the true fraction", () => {
    const h = code(hook);
    assert.match(h, /\.map\(\(a\) => \(\{ a, p: progressOf\(a\) \}\)\)/);
    assert.match(code(desk), /<MoonGauge fraction=\{a\._ratio\}/);
  });

  test("the jump is the shell's: the overlay only names a target, and the click does not replay the card", () => {
    assert.match(code(desk), /onJump\(jump\.to\)/);
    assert.match(code(desk), /e\.stopPropagation\(\); onJump/);
    assert.match(app, /onJump=\{jumpFromFolio\}/);
    const j = app.slice(app.indexOf("const jumpFromFolio"), app.indexOf("const toggleDock"));
    for (const to of ["loom", "contests", "publish"]) assert.match(j, new RegExp('"' + to + '"'));
    assert.ok(!/apiPost|fetch\(/.test(j), "a jump writes nothing");
  });
});

describe("O3: the sort", () => {
  test("it is read once from this device's storage and written only by a chip's click", () => {
    const h = code(hook);
    assert.match(h, /useState\(\(\) => loadSort\(/);
    assert.equal((h.match(/saveSort\(/g) || []).length, 1);
    const chooser = h.slice(h.indexOf("function chooseSort"), h.indexOf("function chooseSort") + 160);
    assert.match(chooser, /saveSort\(safeStorage\(\), key\)/);
    // saveSort is never inside an effect
    for (const m of h.matchAll(/useEffect\(\(\) => \{([\s\S]*?)\n  \}, \[/g)) {
      assert.ok(!/saveSort/.test(m[1]), "the sort is written from an effect");
    }
  });

  test("the sorted list is built by sortHonors and the Feats section never reads it", () => {
    assert.match(code(hook), /return sortHonors\(flat, sortKey, earnedAt\);/);
    const d = code(desk);
    const featsAt = d.indexOf("{showFeats && (");
    assert.ok(featsAt > 0);
    assert.ok(!/sortedHonors/.test(d.slice(featsAt, featsAt + 1600)), "the feats section reads the sorted list");
    assert.match(d, /filteredFeats\.map\(/);
  });

  test("the default sort keeps today's layout: the plinth, the tracks and the sections", () => {
    const d = code(desk);
    assert.match(d, /\{!sorted && showLadders && vm\.ladders\.length > 0 && \(/);
    assert.match(d, /\{!sorted && showMilestones/);
    assert.match(d, /\{!sorted && showMasteries/);
  });

  test("the chips are the core's four, one per sort", () => {
    assert.match(code(desk), /SORTS\.map\(\(c\) =>/);
    assert.match(code(desk), /chooseSort\(c\.key\)/);
  });
});

describe("L2: relics by kind", () => {
  test("both Folios draw the earned-only rows from the hook, not the skins list", () => {
    for (const [name, file] of [["desktop", desk], ["phone", phone]]) {
      const c = code(file);
      assert.ok(!/vm\.relics/.test(c), name + " still reads the old relics list");
      assert.match(c, /relics\.length === 0/, name);
      assert.match(c, /row\.items\.map/, name);
    }
    assert.match(code(hook), /relicRows\(\{/);
  });

  test("the old locked rows and the line that hinted at an unearned one are gone", () => {
    for (const file of [desk, phone]) {
      const c = file;
      assert.ok(!/50k images/.test(c) && !/Feat sigils/.test(c) && !/keeps to itself/.test(c));
      assert.ok(!/🔒 locked/.test(code(c)));
    }
  });

  test("the relics are display only: nothing in the Folio wears a skin or opens the Branding tab", () => {
    // Owner, 2026-09-29: "You should not be able to switch marks and enable skins here AT ALL."
    for (const file of [desk, phone]) {
      const c = code(file);
      assert.ok(!/pickSkin|onPickSkin|onOpenBranding|requestPanelTab/.test(c));
      assert.ok(!/onClick=\{\(\) => \(row\.kind === "skins"/.test(c));
      assert.match(c, /<div (key=\{it\.id\} role="img"|role="img")/);
    }
    assert.ok(!/applySkin|pickSkin/.test(code(hook)));
    const css = src("styles/folio-completionist.css");
    assert.ok(!/\.mgfo-tile:hover/.test(css) && !/(mgfo|fm)-tile \{[^}]*cursor: pointer/.test(css));
  });

  test("the phone's rows scroll sideways with 64 px tiles", () => {
    const css = src("styles/folio-completionist.css");
    assert.match(css, /\.fm-kind-tiles \{[^}]*overflow-x: auto/);
    assert.match(css, /\.fm-tile \{[^}]*width: 64px/);
  });

  test("nothing in the Folio reserves a slot or a line for a relic the account has not earned", () => {
    for (const file of [desk, phone, hook, src("folio/completionistCore.js"), src("styles/folio-completionist.css")]) {
      assert.ok(!/placeholder relic|reserved slot|keeps to itself|secret relic/i.test(code(file)));
    }
  });
});

describe("nothing writes on open", () => {
  test("the Folio's mount effect is one read; pin, switch and sort choice are clicks", () => {
    const h = code(hook);
    const first = h.slice(h.indexOf("useEffect(() => {\n    let dead = false;"), h.indexOf("const iv = setInterval"));
    assert.match(first, /apiGet\("\/api\/achievements"\)/);
    assert.ok(!/apiPost|prefs\.set|saveSort/.test(first));
  });
});
