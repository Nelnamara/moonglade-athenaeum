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
    assert.match(h, /tileChip\(st\.label, bf\.doc\.counts\)/);
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

describe("Fix all and its progress (W3c / W4c)", () => {
  test("the header's Fix all counts the plan and is hidden at zero", () => {
    const b = code("components/BrokenFiles.jsx");
    assert.match(b, /fixPlan\(doc, bf\.readOnly, bf\.done\)/);
    assert.match(b, /plan\.total > 0 \?/);
    assert.match(b, /"Fix all recoverable \(" \+ plan\.total \+ "\)"/);
  });
  test("every fix sends the action the list showed with each id", () => {
    const b = code("components/BrokenFiles.jsx");
    assert.match(b, /bf\.fix\(\[\{ media_id: mid, action: act \}\]\)/);
    assert.match(b, /bf\.fix\(plan\.items\)/);
    const m = code("components/BrokenFilesMobile.jsx");
    assert.match(m, /bf\.fix\(\[\{ media_id: sheetRow\.media_id, action: a \}\]\)/);
    assert.match(m, /bf\.fix\(plan\.items\)/);
    assert.match(code("lib/brokenFixRun.js"), /apiPost\("\/api\/integrity\/fix", \{ csrf: csrf\(\), items \}\)/);
  });
  test("one confirm, with the handoff's lines and Data saver's metered line", () => {
    const b = code("components/BrokenFiles.jsx");
    assert.match(b, /confirmLines\(plan, metered\)/);
    assert.match(b, /saver\.active && saver\.info && saver\.info\.metered/);
    assert.match(b, /className="mgbf-scrim"/);
    assert.match(b, /className="mgbf-host"/);
    assert.match(b, />Cancel</);
  });
  test("while a run goes the header is n / N fixed, the moon on its true fraction, and Stop", () => {
    const b = code("components/BrokenFiles.jsx");
    assert.match(b, /runHeader\(bf\.status\)/);
    assert.match(b, /<MoonGauge fraction=\{fractionOf\(bf\.status\.done, bf\.status\.total\)\} size=\{16\} bar=\{false\}/);
    assert.match(b, /onClick=\{\(\) => bf\.stop\(\)\}>Stop</);
  });
  test("when a run ends Health's tiles re-measure (the touched rows were re-checked on the server)", () => {
    const h = code("components/HealthOverlay.jsx");
    assert.match(h, /onRunEnd\(\(\) => setRunsEnded/);
    assert.match(h, /useHealth\(runsEnded\)/);
    assert.match(code("hooks/useHealth.js"), /refresh \? "\/api\/health\?fresh=1&run=" \+ refresh : "\/api\/health"/);
  });
  test("an Activity row mirrors the run with the moon and opens the list", () => {
    const r = code("notify/ActivityRow.jsx");
    assert.match(r, /j\.type === "integrity"/);
    assert.match(r, /openBrokenFiles\("all"\)/);
    assert.match(r, /<MoonGauge fraction=\{runMoon\}/);
    assert.match(code("notify/format.js"), /integrity: "Health"/);
  });
  test("the run's end says the counts once: the run's own toast, not the tray's generic one", () => {
    const s = code("notify/jobsStore.js");
    assert.match(s, /j\.type === "integrity"\) \{ last\[j\.job_id\] = st; return; \}/);
    const run = code("lib/brokenFixRun.js");
    assert.match(run, /toastShow\(/);
    assert.match(run, /endToast\(st\)/);
    assert.match(run, /label: "Show"/);
    assert.doesNotMatch(run, /kind: "err"/, "no ruby: a run with failures is not an error toast");
  });
});

describe("phone (W6a)", () => {
  test("Collection Health gains peach problem tiles and a 'Broken files ›' row that push the screen", () => {
    const h = code("components/HealthMobile.jsx");
    assert.match(h, /tileChip\(st\.label, bf\.doc\.counts\)/);
    assert.match(h, /className="mgbf-m-entry"/);
    assert.match(h, /entrySummary\(bf\.doc\)/);
    assert.match(h, /<MobileScreen open=\{bfOpen\} closing=\{bfClosing\} onClose=\{closeBf\} title="Broken files">/);
    assert.match(h, /useLayerHistory\(bfOpen, closeBf\)/, "Back closes the Broken files screen first");
    assert.match(h, /useHealth\(runsEnded\)/);
  });
  test("the screen: sideways chips, 64 px rows, a row-tap sheet, a sticky Fix all, a sheet confirm", () => {
    const m = code("components/BrokenFilesMobile.jsx");
    assert.match(m, /visibleChips\(doc && doc\.counts, true\)/);
    assert.match(m, /onClick=\{\(\) => \{ if \(!active && !fixed\) openRow\(r\.media_id\); \}\}/);
    assert.match(m, /className="mgbf-m-foot"/);
    assert.match(m, /confirmLines\(plan, metered\)/);
    assert.match(m, /<MobileSheet open=\{!!asking\}/);
    const css = src("styles/broken-files.css");
    assert.match(css, /\.mgbf-m-row \{[^}]*min-height: 64px/);
    assert.match(css, /\.mgbf-m-chips \{[^}]*height: 36px[^}]*overflow-x: auto/);
    assert.match(css, /\.mgbf-m-foot \{ position: sticky; bottom: -13px/);
  });
  test("a LOST row's sheet says why and never offers a re-download", () => {
    const m = code("components/BrokenFilesMobile.jsx");
    assert.match(m, /const a = bf\.running \? null : rowAction\(sheetRow, bf\.readOnly\)/);
    assert.match(m, /lostLine\(sheetRow\)/);
    assert.match(m, />Keep as is</);
  });
  test("progress shows at the screen's head, with the phone's moon", () => {
    const m = code("components/BrokenFilesMobile.jsx");
    assert.match(m, /runHeader\(bf\.status\)/);
    assert.match(m, /size=\{GAUGE_SIZES\.phone\} bar=\{false\}/);
  });
  test("the phone's doors: Control's Verify row, and the shell's opener onto Health", () => {
    const c = code("components/ControlMobile.jsx");
    assert.match(c, /key === "verify-library" && brokenReview/);
    assert.match(c, /openBrokenFiles\("all"\)/);
    const a = code("components/AppMobile.jsx");
    assert.match(a, /registerBrokenFilesOpener\(/);
    assert.match(a, /openScreenKey\("health"\)/);
  });
});
