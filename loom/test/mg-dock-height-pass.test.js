import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  dockLayout, PROMPT_FLOOR, PROMPT_CAP, SLAB_CHROME, REEL_MIN_ROOM, HISTORY_STRIP,
} from "../../gallery/src/gen/dockLayout.js";

// The Generate dock's HEIGHT PASS -- owner calls 08-16d/e/f, drift-report §43,
// handoff-2026-08-16-generate-dock-history §4, as drawn by the design of record
// (Frontend Gallery.dc.html measureDock 2020-2047 · fitReel 2071-2081 · reelShown 2823 ·
// promptRows 3561 · Esc chain 1977-1984). The rules under test:
//
//   1. the prompt's resting floor is 6 rows (was 2); it grows with the text to the
//      room-driven cap, max 14; past that the TEXTAREA scrolls, never the panel;
//   2. standard stays content-sized under the separator ceiling; ▲ / long prompt /
//      History may grow to 100vh − 28 (History's strip is its own chrome term);
//   3. ▲ keeps the reel visible above the settings slabs -- tiles tier to 84/104, the
//      reel's room is measured against ▲'s own ceiling less the ~330px of slab chrome,
//      and the reel hides only when a short window leaves it under 60px;
//   4. ▲ and History compose -- neither toggle closes the other, and Esc peels them one
//      at a time (settings, then History, then the dock).
//
// dockLayout() is the SAME pure function the React dock renders from, so these run the
// real arithmetic against plain numbers. The Esc chain, the CSS floors for the video
// contenteditable / the Fixer-Enhance copy line, and the Edit instruction's rows are not
// pure, so those are pinned in the source (short, literal, and each one is a line the
// pass changed).

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");

const desk = { vh: 1080, sepBottom: 262 };   // the owner's install: 1080p, banner slim

describe("prompt rows: floor 6, grows with the text, capped by room, textarea scrolls past", () => {
  test("an empty prompt rests at 6 rows on every tab state (was 2)", () => {
    for (const st of [{}, { expanded: true }, { historyOpen: true }, { expanded: true, historyOpen: true }]) {
      const L = dockLayout({ ...desk, promptLen: 0, promptFocus: false, ...st });
      assert.equal(L.promptRows, PROMPT_FLOOR, JSON.stringify(st));
      assert.equal(PROMPT_FLOOR, 6);
    }
  });
  test("focus adds a row only above the floor -- a short prompt stays at 6 focused", () => {
    const L = dockLayout({ ...desk, promptLen: 40, promptFocus: true });
    assert.equal(L.promptRows, 6);
  });
  test("grows one row per 76 characters once past the floor", () => {
    const L7 = dockLayout({ ...desk, promptLen: 76 * 7, promptFocus: false });
    assert.equal(L7.promptRows, 7);
    const L7f = dockLayout({ ...desk, promptLen: 76 * 7, promptFocus: true });
    assert.equal(L7f.promptRows, 8);
  });
  test("a 2,000-character prompt caps at 14 rows and the panel never grows past it", () => {
    const L = dockLayout({ ...desk, promptLen: 2000, promptFocus: true });
    assert.equal(L.promptLines, Math.ceil(2000 / 76));   // 27 lines of text
    assert.equal(L.promptRows, PROMPT_CAP);               // 14 shown -- the rest scrolls
    assert.equal(PROMPT_CAP, 14);
    assert.ok(L.longPrompt, "a long prompt lifts the dock's ceiling to 100vh-28");
    assert.equal(L.capH, desk.vh - 28);
  });
  test("a short window lowers the cap, never the floor -- the floor is the design's, not the room's", () => {
    // 620px tall, expanded, reel showing: the room-driven cap falls under 6
    const L = dockLayout({ vh: 620, sepBottom: 262, expanded: true, promptLen: 0, promptFocus: false });
    assert.ok(L.promptMax < 6, "cap is " + L.promptMax);
    assert.equal(L.promptRows, 6);
  });
});

describe("standard: content-sized under the separator ceiling", () => {
  test("neither ▲ nor a long prompt -> the clamp is the separator ceiling, not the viewport", () => {
    const L = dockLayout({ ...desk, promptLen: 100, promptFocus: false });
    assert.equal(L.capH, desk.vh - desk.sepBottom - 14);
    assert.ok(!L.longPrompt);
  });
  test("▲ lifts the clamp to 100vh − 28", () => {
    const L = dockLayout({ ...desk, expanded: true, promptLen: 0, promptFocus: false });
    assert.equal(L.capH, desk.vh - 28);
  });
  test("History alone lifts the clamp too -- its own dock mode (DC dockStyle 3505-3506)", () => {
    const L = dockLayout({ ...desk, historyOpen: true, promptLen: 0, promptFocus: false });
    assert.equal(L.capH, desk.vh - 28);
    // and the prompt cap counts the 2-row strip, not the one-row reel term
    assert.equal(HISTORY_STRIP, 260);
    const chrome = 46 + HISTORY_STRIP + 96;
    assert.equal(L.promptMax, Math.min(PROMPT_CAP, Math.floor((L.capH - chrome) / 25)));
  });
});

describe("▲ keeps the reel visible above the settings slabs (08-16e)", () => {
  test("expanded, on the owner's install: the reel SHOWS, tiered to 104", () => {
    const L = dockLayout({ ...desk, expanded: true, promptLen: 0, promptFocus: false });
    assert.equal(L.reelVisible, true);
    assert.equal(L.reelTier, 104);
    assert.equal(L.reelH, 104);
  });
  test("under 760px tall the ▲ tier is 84", () => {
    const L = dockLayout({ vh: 740, sepBottom: 262, expanded: true, promptLen: 0, promptFocus: false });
    assert.equal(L.reelTier, 84);
  });
  test("the reel's room in ▲ is measured against ▲'s ceiling minus the slab chrome (fitReel 2073-2074)", () => {
    const L = dockLayout({ ...desk, expanded: true, promptLen: 0, promptFocus: false });
    assert.equal(L.reelRoom, (desk.vh - 28) - 56 - 118 - 46 - SLAB_CHROME);
    assert.equal(SLAB_CHROME, 330);
    // and in standard against the separator ceiling, no slab chrome
    const S = dockLayout({ ...desk, promptLen: 0, promptFocus: false });
    assert.equal(S.reelRoom, (desk.vh - desk.sepBottom - 14) - 56 - 118 - 46);
  });
  test("the reel hides only when a short window leaves it under 60px of room", () => {
    // ▲ at 600px: room = 572 - 220 - 330 = 22 -> hidden
    const short = dockLayout({ vh: 600, sepBottom: 262, expanded: true, promptLen: 0, promptFocus: false });
    assert.ok(short.reelRoom < REEL_MIN_ROOM);
    assert.equal(short.reelVisible, false);
    assert.equal(REEL_MIN_ROOM, 60);
    // ▲ at 660px: room = 632 - 550 = 82 -> shown, clamped to the room
    const ok = dockLayout({ vh: 660, sepBottom: 262, expanded: true, promptLen: 0, promptFocus: false });
    assert.equal(ok.reelVisible, true);
    assert.equal(ok.reelH, 82);
  });
  test("open History always shows its strip, even where the reel would hide", () => {
    const L = dockLayout({ vh: 600, sepBottom: 262, expanded: true, historyOpen: true, promptLen: 0, promptFocus: false });
    assert.equal(L.reelVisible, true);
  });
  test("with the reel showing in ▲ the prompt cap counts it -- the panel stays under 100vh−28", () => {
    // 900px tall, ▲, reel 104: chrome = 46 + 150 + 330 + 96 = 622; (872-622)/25 = 10
    const L = dockLayout({ vh: 900, sepBottom: 262, expanded: true, promptLen: 2000, promptFocus: false });
    assert.equal(L.reelVisible, true);
    assert.equal(L.promptMax, 10);
    assert.equal(L.promptRows, 10);
    const total = 46 + (L.reelH + 46) + 330 + 96 + L.promptRows * 25;
    assert.ok(total <= L.capH, "dock " + total + " under ceiling " + L.capH);
  });
});

describe("the dock wires the pure layout, and the pieces that are not pure carry the pass", () => {
  const dock = src("gallery/src/components/GenerateDrawer.jsx");
  const edit = src("gallery/src/components/EditTab.jsx");
  const css = src("gallery/src/styles/dock.css");

  test("GenerateDrawer renders from dockLayout(), not a private copy of the math", () => {
    assert.match(dock, /import \{ dockLayout \} from "\.\.\/gen\/dockLayout\.js"/);
    assert.match(dock, /const \{ capH, reelH, reelVisible, promptMax, promptRows \} = dockLayout\(\{/);
    assert.doesNotMatch(dock, /const reelVisible = !expanded/, "the old '!expanded' reel gate is gone");
    assert.doesNotMatch(dock, /const promptRows = Math\.max\(2/, "the old 2-row floor is gone");
  });
  test("▲ and History compose: neither toggle closes the other", () => {
    // the ▲ toggle is a bare flip; the History button is a bare flip
    assert.match(dock, /onToggle=\{\(\) => setExpanded\(\(v\) => !v\)\}/);
    assert.match(dock, /onClick=\{\(\) => setHistoryOpen\(\(v\) => !v\)\}/);
    assert.doesNotMatch(dock, /setHistoryOpen\(false\);\s*setExpanded/, "no cross-close");
    assert.doesNotMatch(dock, /setExpanded\(false\);\s*setHistoryOpen/, "no cross-close");
  });
  test("Esc peels ▲, then History, then the dock (DC 1982-1984)", () => {
    const i = dock.indexOf('if (expanded) { setExpanded(false); return; }');
    const j = dock.indexOf('if (historyOpen) { setHistoryOpen(false); return; }');
    const k = dock.indexOf('closeDrawer();', j);
    assert.ok(i > 0 && j > i && k > j, "order: expanded < history < close");
  });
  test("the Edit instruction shares the composer's 6-row floor", () => {
    assert.match(edit, /Math\.max\(6, Math\.min\(dock\.promptMax \|\| 8,/);
  });
  test("the video contenteditable and the Fixer/Enhance copy line hold the same 6-row rest", () => {
    // .mgdock-composer .mgd-ce: 6 lines at rest = 9em at line-height 1.5
    const ce = css.match(/\.mgdock-composer \.mgd-ce \{[^}]*\}/)[0];
    assert.match(ce, /min-height: 9em/);
    assert.match(ce, /max-height: calc\(max\(var\(--mg-prompt-max, 8\), 6\) \* 1\.5em\)/);
    // the no-prompt line holds the same 144px (16px * 1.5 * 6)
    const msg = css.match(/\.mgdock-composer-msg \{[^}]*\}/)[0];
    assert.match(msg, /min-height: 144px/);
  });
  test("no second focus ring on the composer textareas (the composer border is the ring)", () => {
    assert.match(css, /\.mgdock-prompt:focus-visible, \.mgdock-neg:focus-visible \{ outline: none; \}/);
  });
});
