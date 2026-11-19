import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

/* ONE TIDY PLACE (owner pick 2026-11-19, round 2 option B): duplicates, stray files and broken
   files in one Control Panel tab. Source-level guards for the wiring and, above all, for the
   safety model the move must not loosen: the chain's order gate, confirm-then-run, and
   destructive buttons drawn only from summary.actions (local sessions). The render harness
   (dev/tests/test_render_harness.py) drives the tab in a real browser. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");
const code = (rel) => src(rel).replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("the tab", () => {
  test("Maintenance, Tidy, ✦ Branding -- one list the panel and the key-turn rail both read", async () => {
    const { PANEL_TABS } = await import(pathToFileURL(path.join(SRC, "lib", "panelTabs.js")).href);
    assert.deepEqual(PANEL_TABS.map((t) => t.id), ["maint", "tidy", "brand"]);
    assert.equal(PANEL_TABS.find((t) => t.id === "tidy").gated, undefined, "Tidy is never locked");
    const c = code("components/ControlPanelOverlay.jsx");
    assert.match(c, /panelTabLabel\("tidy"\)/);
    assert.match(c, /tab === "tidy" && \(\s*<TidyTab /);
  });

  test("three columns, as the board draws them: Duplicates, Stray files, Broken", () => {
    const t = code("components/TidyTab.jsx");
    const at = (s) => t.indexOf(s);
    assert.ok(at('aria-label="Duplicates"') < at('aria-label="Stray files"')
      && at('aria-label="Stray files"') < at('aria-label="Broken files"'));
    assert.match(t, />Find</);
    assert.match(t, />Review</);
    assert.match(t, /label="Preview"/);
    assert.match(t, /label="Undo"/);
    assert.match(t, />Fix all</);
  });

  test("Maintenance keeps no second Organize or Dedup, only a pointer to Tidy", () => {
    const c = code("components/ControlPanelOverlay.jsx");
    assert.doesNotMatch(c, /DEDUP_STAGES/);
    assert.doesNotMatch(c, /runAction\("organize"\)/);
    assert.doesNotMatch(c, /\["verify-dupes"/);
    assert.doesNotMatch(c, /\["verify-library"/);
    assert.match(c, /onClick=\{\(\) => setTab\("tidy"\)\}/);
  });
});

describe("one duplicates flow, no gate loosened", () => {
  test("Move all, Check and Delete keep the chain's order gate and its confirm", () => {
    const t = code("components/TidyTab.jsx");
    assert.match(t, /const early = i > dedupDone;/);
    assert.match(t, /disabled=\{busy \|\| early\}/);
    assert.match(t, /armed=\{confirmArm === key\} onRun=\{\(\) => runAction\(key\)\}/);
    for (const k of ["dedup-apply", "verify-dupes", "dedup-delete"]) {
      assert.match(t, new RegExp('step\\("' + k + '"'), k + " goes through the gated step()");
    }
    // the hook's own refusal stands behind the greyed button, unchanged
    const h = code("hooks/useControlPanel.js");
    assert.match(h, /if \(dedupIdx !== -1 && dedupIdx > dedupDone\) return;/);
    assert.match(h, /if \(spec\.destructive && confirmArm !== key\) \{\s*setConfirmArm\(key\);\s*return;/);
  });

  test("destructive buttons come only from summary.actions (a LAN session gets none)", () => {
    const j = code("components/JobConsole.jsx");
    assert.match(j, /if \(!spec\) return null;/);
    const t = code("components/TidyTab.jsx");
    assert.doesNotMatch(t, /all_actions/, "the unfiltered list would draw LAN buttons the server refuses");
  });

  test("Find is Audit, then Preview only after a clean Audit", () => {
    const h = code("hooks/useControlPanel.js");
    assert.match(h, /findChainRef\.current && finishedKey === "audit" && d\.status === "done"/);
    assert.match(h, /startJob\("dedup-dry"\)/);
    assert.doesNotMatch(h, /startJob\("dedup-apply"\)|startJob\("dedup-delete"\)/,
      "Find never starts a stage that changes files");
  });

  test("Review is the one Duplicate Review, on the Panel's sub-layer; Health opens Tidy instead", () => {
    const c = code("components/ControlPanelOverlay.jsx");
    assert.match(c, /<DuplicateReviewOverlay stacked backLabel="Tidy"/);
    const h = code("components/HealthOverlay.jsx");
    assert.doesNotMatch(h, /onOpenDuplicates/);
    assert.match(h, /onOpenTidy\(\)/);
    const a = code("App.jsx");
    assert.doesNotMatch(a, /DuplicateReviewOverlay/, "no second door to Duplicate Review on the desktop");
    assert.match(a, /onOpenTidy=\{openTidy\}/);
  });
});
