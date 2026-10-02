import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { setFolioRow, takeFolioRow, folioHref, readFolioHash } from "../../gallery/src/folio/folioFocus.js";

/* The pinned goal, the Vigil and the Honors card, pinned at the source (Session O, O4-O6 and the
   phone). The components are React and this suite has no renderer, so what is asserted here is the
   shape of the wiring the pure cores (folio-goal-core / folio-honors-card) cannot see: where the
   chips are mounted, that nothing writes on open, that the pin clears only on the marking read's
   earn, that the celebration band hides the chips, and that the card never leaves the device. */

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(here, "..", "..");
const read = (rel) => readFileSync(path.join(ROOT, rel), "utf8").replace(/\r\n/g, "\n");
const code = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const chipsHook = read("gallery/src/hooks/useGoalChips.js");
const chips = read("gallery/src/components/GoalChips.jsx");
const sep = read("gallery/src/components/SeparatorBar.jsx");
const appMobile = read("gallery/src/components/AppMobile.jsx");
const app = read("gallery/src/App.jsx");
const loom = read("loom/master-storyboard.jsx");
const ach = read("gallery/src/notify/ach.js");
const folioHook = read("gallery/src/hooks/useFolio.js");
const desk = read("gallery/src/components/FolioOverlay.jsx");
const phone = read("gallery/src/components/FolioMobile.jsx");
const cardBrowser = read("gallery/src/folio/honorsCardBrowser.js");
const cardPanel = read("gallery/src/folio/HonorsCardPanel.jsx");
const css = read("gallery/src/styles/goal-chips.css");

describe("O4/O5: where the chips are mounted", () => {
  test("the separator bar (gallery and the dock beneath it) mounts them beside the credits", () => {
    const c = code(sep);
    assert.match(c, /import GoalChips from "\.\/GoalChips\.jsx";/);
    assert.ok(c.indexOf("<GoalChips />") > 0);
    assert.ok(c.indexOf("<GoalChips />") < c.indexOf('className="mgx-cred"'), "before the credits chip");
  });

  test("the Loom's header mounts them", () => {
    assert.match(code(loom), /import GoalChips from "\.\.\/gallery\/src\/components\/GoalChips\.jsx";/);
    assert.match(code(loom), /<GoalChips \/>/);
  });

  test("the phone mounts them in one row directly above the tab bar", () => {
    const c = code(appMobile);
    const at = c.indexOf("<GoalChips phone />");
    assert.ok(at > 0);
    assert.ok(c.indexOf("<TabBarMobile", at) - at < 40, "the tab bar follows straight after");
  });

  test("one chip row: the pin and the Vigil come from the same hook", () => {
    const c = code(chips);
    assert.match(c, /useGoalChips\(\)/);
    assert.match(c, /if \(g\.hidden \|\| \(!g\.pin && !g\.vigil\)\) return null;/);
  });

  test("the phone chip is 32 px and swiped away through the core's rule", () => {
    assert.match(css, /\.mgg-chips\.phone \{[^}]*height: 32px/);
    assert.match(code(chips), /swipedAway\(e\.clientX - s\.x, e\.clientY - s\.y\)/);
    assert.match(code(chips), /phone && \(e\.key === "Delete"/, "a keyboard way to unpin too");
  });

  test("the chip's moon is the shared gauge at the phone's 14 px, on the pin's true fraction", () => {
    assert.match(code(chips), /<MoonGauge fraction=\{pin\.fraction\} size=\{GAUGE_SIZES\.phone\} bar=\{false\}/);
  });
});

describe("O4: what writes, and when", () => {
  test("the hook never sets anything: it can only unset, on a click or on the earn", () => {
    const c = code(chipsHook);
    assert.ok(!/\.set\(/.test(c), "no prefs.set in the chips hook");
    assert.equal((c.match(/unset/g) || []).length >= 2, true);
    // the automatic unset is inside the achievements listener and needs a MARKING read's newly list
    assert.match(c, /if \(marked && pinEarned\(pinRef\.current, d\.newly\)\) unsetRef\.current\(PIN_KEY\);/);
  });

  test("the only other read is one plain GET, and only when a chip is wanted and nothing is in hand", () => {
    const c = code(chipsHook);
    assert.match(c, /if \(!wanted \|\| have\) return undefined;/);
    assert.equal((c.match(/apiGet\(/g) || []).length, 1);
    assert.ok(!/apiPost|fetch\(/.test(c));
  });

  test("the chip draws only from pinView, which is null for a feat, an earned honor or no count", () => {
    assert.match(code(chipsHook), /pinView\(data && data\.achievements, pin\)/);
  });

  test("the Folio's pin button exists only for an honor with a count, and pins through the core", () => {
    const d = code(desk);
    assert.match(d, /goal\.onPin && canPin\(a\)/);
    assert.match(code(folioHook), /const next = togglePin\(pin, a\);\s*if \(next === null\) return null;/);
    const p = code(phone);
    assert.match(p, /\{canPin\(a\) && \(/);
  });

  test("the pin and the Vigil switch are written only by their own handlers", () => {
    const h = code(folioHook);
    assert.match(h, /function setVigilOn\(on\) \{\s*return on \? prefs\.set\(VIGIL_HEADER_KEY, true\) : prefs\.unset\(VIGIL_HEADER_KEY\);/);
    // no effect in the hook writes the pin or the switch
    const effects = h.match(/useEffect\([\s\S]*?\n  \}, \[[^\]]*\]\);/g) || [];
    for (const e of effects) assert.ok(!/PIN_KEY|VIGIL_HEADER_KEY|pinToggle|setVigilOn/.test(e), e.slice(0, 80));
  });
});

describe("O4: hidden during a celebration", () => {
  test("the engine exposes the celebration band as a subscribable fact", () => {
    const c = code(ach);
    assert.match(c, /export function celebrationUp\(\) \{ return _live\.size > 0 \|\| _bespoke > 0; \}/);
    assert.match(c, /export function onCelebration\(fn\)/);
    // every path that raises or lowers the band tells the listeners
    assert.match(c, /function _mount\(el\) \{ _live\.add\(el\); document\.body\.appendChild\(el\); _celebChanged\(\); \}/);
    assert.match(c, /function _unmount\(el\) \{[^}]*_celebChanged\(\);\s*\}/);
    assert.match(c, /export function beginBespokeMoment\(\) \{ _bespoke\+\+; _celebChanged\(\); \}/);
    assert.match(c, /_resume\(\);\s*_celebChanged\(\);\s*\}/);
  });

  test("the hook hides the chips while it is up", () => {
    const c = code(chipsHook);
    assert.match(c, /useState\(\(\) => celebrationUp\(\)\)/);
    assert.match(c, /useEffect\(\(\) => onCelebration\(setHidden\), \[\]\);/);
  });

  test("the engine tells subscribers about every answer it reads, marking or not, before it toasts", () => {
    const c = code(ach);
    const at = c.indexOf("_dataListeners.forEach((fn) => { try { fn(d, !!mark); }");
    assert.ok(at > 0);
    assert.ok(at < c.indexOf("if (mark) toastNew(d);"), "listeners hear it before the toast queue does");
  });
});

describe("O4: the click opens the row", () => {
  test("the gallery, the phone and the Loom each have a door", () => {
    assert.match(code(chipsHook), /if \(!openFolio\(\)\) window\.location\.href = folioHref\(id\);/);
    assert.match(code(ach), /export function openFolio\(\)/);
    for (const [name, file] of [["desktop", app], ["phone", appMobile]]) {
      assert.match(code(file), /readFolioHash\(window\.location\.hash\)/, name);
      assert.match(code(file), /setFolioRow\(fh\.row\)/, name);
    }
  });

  test("the row link is one slot, consumed on read", () => {
    setFolioRow("honor-a");
    assert.equal(takeFolioRow(), "honor-a");
    assert.equal(takeFolioRow(), null);
    setFolioRow("");
    assert.equal(takeFolioRow(), null);
    setFolioRow(42);
    assert.equal(takeFolioRow(), null);
  });

  test("the address the Loom crosses with, and how the gallery reads it", () => {
    assert.equal(folioHref("a b"), "/#folio=a%20b");
    assert.equal(folioHref(""), "/#folio");
    assert.deepEqual(readFolioHash("#folio=a%20b"), { row: "a b" });
    assert.deepEqual(readFolioHash("#folio"), { row: "" });
    for (const other of ["#image", "#edit", "", "#folio=x&y", "#foliox", null, undefined]) {
      assert.equal(readFolioHash(other), null, String(other));
    }
    assert.deepEqual(readFolioHash("#folio=" + "x".repeat(200)), { row: "" });
    assert.deepEqual(readFolioHash("#folio=%E0%A4%A"), { row: "" });
  });

  test("the Folio rings and scrolls to a row only if it is a listed honor with a count", () => {
    const h = code(folioHook);
    assert.match(h, /if \(!a \|\| !canPin\(a\)\) return;/);
    assert.match(h, /setRingId\(a\.id\);/);
    assert.match(code(desk), /data-honor-id=\{!isFeat && prog \? a\.id : undefined\}/);
    assert.match(code(phone), /data-honor-id=\{prog \? a\.id : undefined\}/);
  });
});

describe("O5: the Vigil", () => {
  test("the Folio header always shows it, with 'best N', and the switch adds it to the app header", () => {
    const d = code(desk);
    assert.match(d, /\{vigil && \(/);
    assert.match(d, /<VigilChip vigil=\{vigil\} \/>/);
    assert.match(d, /\{vigil\.bestText\}/);
    assert.match(d, /Show in the app header/);
    assert.match(d, /onClick=\{\(\) => setVigilOn\(!vigilOn\)\}/);
  });

  test("the phone header shows it too, and its switch names the row above the tab bar", () => {
    const p = code(phone);
    assert.match(p, /<VigilChip vigil=\{vigil\} \/>/);
    assert.match(p, /Show the Vigil above the tab bar/);
  });

  test("a miss says nothing: the chip's text is only the day and no copy about a streak is anywhere", () => {
    for (const file of [chips, desk, phone, chipsHook]) {
      assert.ok(!/streak (broken|lost)|you missed|welcome back|lost your/i.test(code(file)));
    }
  });
});

describe("O6: the card stays on the device", () => {
  test("nothing in the browser half uploads: no network call of any kind", () => {
    const c = code(cardBrowser) + code(cardPanel);
    assert.ok(!/\bfetch\(|apiPost|apiGet|XMLHttpRequest|sendBeacon|FormData|WebSocket/.test(c), "no network");
    assert.match(c, /new Image\(\)/);
    assert.match(c, /createObjectURL/);
    assert.match(c, /navigator\.share/);
    assert.match(c, /navigator\.clipboard\.write/);
  });

  test("only the app's own badge art is fetched, as a still", () => {
    assert.match(code(cardBrowser), /badgeSources\(b\.id, 384\)\[1\]/);
  });

  test("the card is drawn only after a click, from the Folio's own model", () => {
    assert.match(code(desk), /cardOpen && cardModel && \(/);
    assert.match(code(desk), /setCardOpen\(\(o\) => !o\)/);
    assert.match(code(phone), /setCardOpen\(true\)/);
    assert.match(code(folioHook), /honorsCardModel\(\{/);
  });

  test("desktop offers Save and Copy; the phone offers Share, with Save as the fallback", () => {
    const c = code(cardPanel);
    assert.match(c, /Save PNG/);
    assert.match(c, /Copy image/);
    assert.match(c, />Share<\/button>/);
    assert.match(c, /r === "unsupported"/);
  });
});

describe("the phone screens for O1-O3", () => {
  test("the meter line sits under the header points, with the phone's 14 px moon", () => {
    const p = code(phone);
    assert.match(p, /<MoonGauge fraction=\{fractionOf\(meter\.earned, meter\.total\)\} size=\{GAUGE_SIZES\.phone\}/);
    assert.match(p, /meterLine\(meter\)/);
  });

  test("'N to go' sits under each row and in the sheet, only through progressOf", () => {
    const p = code(phone);
    assert.match(p, /function ToGo\(\{ a, onJump, pin, onPin, sheet = false \}\) \{\s*const prog = progressOf\(a\);\s*if \(!prog\) return null;/);
    assert.match(p, /<ToGo a=\{sheetAch\} sheet/);
    assert.match(css, /\.fm-togo-btn \{[^}]*min-width: 44px; min-height: 44px/);
  });

  test("the Sort chip ends the bucket chip row and opens a sheet of the core's four sorts", () => {
    const p = code(phone);
    assert.match(p, /className=\{"fm-chip fm-sortchip"/);
    assert.match(p, /SORTS\.map\(\(c\) => \(/);
    assert.match(p, /onClick=\{\(\) => \{ chooseSort\(c\.key\); closeSort\(\); \}\}/);
    const chipsRow = p.indexOf('className="fm-chipsrow"');
    assert.ok(p.indexOf("fm-sortchip") > chipsRow);
  });

  test("Within reach draws the moon, not the old bar", () => {
    assert.ok(!/className="reach"/.test(code(phone)));
    assert.match(code(phone), /className="fm-reach-gauge"/);
  });

  test("the phone shell gives the Folio its jump host: Create, the Loom, Contests, Publish", () => {
    const c = code(appMobile);
    assert.match(c, /<FolioMobile onClose=\{closeFolio\} onJump=\{jumpFromFolio\} \/>/);
    assert.match(c, /if \(to === "loom"\) \{ window\.location\.href = "\/loom"; return; \}/);
    assert.match(c, /if \(to === "contests"\) \{ openScreenKey\("contests"\); return; \}/);
    assert.match(c, /if \(to === "publish"\) \{ openPublish\(""\); return; \}/);
    assert.match(c, /setTab\("create"\);/);
  });

  test("no hard-coded hex in the new stylesheet: the app's tokens re-dress it", () => {
    assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(code(css)), "no hex in goal-chips.css");
  });
});
