import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE PHONE'S FOUNDATIONS (2026-09-06) -- source guards for the four things the render
   harness measures in a real browser at 390x844, plus the two the harness cannot see.

   The behaviour lives in tests/test_render_harness.py:
     ..._the_back_gesture_closes_one_layer_at_a_time_and_never_leaves_the_app
     ..._the_pager_lands_each_page_at_its_top
     ..._an_open_sheet_holds_the_library_still_behind_it
     ..._each_tab_keeps_its_own_scroll
   These pin the WIRING those rest on -- the same call this suite's own
   gallery-stands-still.test.js and overlay-open-perf.test.js make, and for the same
   reason: there is no React test renderer here, so what can be pinned is the structure.
   Every layer the shell pushes has to be ON the ledger, and a missing one is invisible in
   any single behavioural test -- it is only a missing LINE. That is what this file is for. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite: the repo stores LF
// (.gitattributes `* text=auto`) while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");
const repo = (p) => readFileSync(path.resolve(__dirname, "../..", p), "utf8")
  .replace(/\r\n/g, "\n");

const manager = src("hooks/useLayerHistory.js");
const mobile = src("components/AppMobile.jsx");
const control = src("components/ControlMobile.jsx");
const create = src("components/CreateMobile.jsx");
const health = src("components/HealthMobile.jsx");
const folioMobile = src("components/FolioMobile.jsx");
const glmCss = src("styles/gallery-mobile.css");
const idmCss = src("styles/image-details-mobile.css");
const fmCss = src("styles/folio-mobile.css");
const iconCss = src("styles/icons.css");
const server = repo("moonglade_gallery.py");
const devShell = repo("gallery/index.html");

// ------------------------------------------------------------------ 1. the Back gesture
describe("ONE ledger, one entry per open layer, and a Back closes the topmost", () => {
  test("the manager reconciles a DEPTH against the open stack -- never a push per call site", () => {
    assert.match(manager, /const stack = \[\];/);
    assert.match(manager, /let depth = 0;/);
    // pushes are driven by the shortfall, not by the caller
    assert.match(manager, /while \(depth < want\) \{/);
    assert.match(manager, /window\.history\.pushState\(\{ mgLayer: depth \}, ""\);/);
    // ...and the same address, always: nothing on this shell is URL-synced
    assert.doesNotMatch(manager, /pushState\([^)]*,\s*""\s*,/);
    assert.match(manager, /if \(depth > want\) \{/);
    assert.match(manager, /window\.history\.go\(-drop\);/);
  });

  test("ONE reconcile per commit, on a microtask -- a swap must not fire go() and pushState at each other", () => {
    assert.match(manager, /function schedule\(\) \{/);
    assert.match(manager, /Promise\.resolve\(\)\.then\(\(\) => \{ scheduled = false; sync\(\); \}\);/);
    // every registration edge goes through the scheduler, never straight to sync()
    const hook = manager.slice(manager.indexOf("export default function useLayerHistory"));
    assert.match(hook, /stack\.push\(entry\);\n\s+schedule\(\);/);
    assert.match(hook, /stack\.splice\(i, 1\);\n\s+schedule\(\);/);
    assert.doesNotMatch(hook, /\bsync\(\);/);
  });

  test("the owner's Back is told apart from our own unwind, and drops the ledger BEFORE closing", () => {
    const pop = manager.slice(manager.indexOf("function onPop()"), manager.indexOf("function sync()"));
    assert.match(pop, /if \(unwinding > 0\) \{ unwinding -= 1; return; \}/);
    assert.match(pop, /if \(!depth\) return;/);
    assert.ok(pop.indexOf("depth -= 1;") < pop.indexOf(".close()"),
      "the ledger must drop before the close, or the reconcile the close schedules "
      + "will ask the browser to go back a second time");
    // the topmost layer NOT already told to close -- two Backs in one frame must not
    // close the same layer twice and strand the one beneath it
    assert.match(pop, /if \(!stack\[i\]\.closing\) \{ stack\[i\]\.closing = true; stack\[i\]\.close\(\); return; \}/);
    // ...and `unwinding` is only ever owed by a go() of our own
    assert.match(manager, /unwinding \+= drop;/);
  });

  test("EVERY layer the phone pushes is registered -- the list with no gaps", () => {
    assert.match(mobile, /import useLayerHistory from "\.\.\/hooks\/useLayerHistory\.js";/);
    for (const [what, re] of [
      ["◈ Similar", /useLayerHistory\(simOn, clearSimilar\);/],
      ["the full-screen viewer", /useLayerHistory\(lbIndex != null, closeLightbox\);/],
      ["the picture screen", /useLayerHistory\(!!detailsFor, closeDetails\);/],
      ["the Menu destinations", /useLayerHistory\(!!screen, closeScreen\);/],
      ["the Folio", /useLayerHistory\(folioOpen, closeFolio\);/],
      ["the contact sheet", /useLayerHistory\(!!contactSheetTarget, closeContactSheet\);/],
      ["the contest entry screen", /useLayerHistory\(!!contestEntry, closeContestEntry\);/],
    ]) assert.match(mobile, re, what + " is not on the Back ledger");
    // index 0 is a REAL open viewer -- never a truthiness test, the same read App.jsx's
    // own overlay guard makes for the same reason
    assert.doesNotMatch(mobile, /useLayerHistory\(!!lbIndex/);
    // and the three drill-ins that own their own local open/closing pair
    for (const [what, file, re] of [
      ["Control's Branding", control, /useLayerHistory\(brandOpen, closeBrand\);/],
      ["the composer's Advanced", create, /useLayerHistory\(advOpen, closeAdv\);/],
      ["Health's Duplicates", health, /useLayerHistory\(dupOpen, closeDup\);/],
    ]) {
      assert.match(file, re, what + " is not on the Back ledger");
      assert.match(file, /import useLayerHistory from "\.\.\/hooks\/useLayerHistory\.js";/);
    }
  });

  test("SHEETS ARE NOT LAYERS -- they keep the scrim's own tap-outside and nothing else", () => {
    // The decision, stated where a reader of the shell will meet it.
    assert.match(mobile, /SHEETS ARE NOT LAYERS, and stay tap-out-only/);
    /* No sheet state is on the ledger, asserted as a CLOSED list rather than by hunting
       for the word: every registration in the whole phone shell, read out of the source,
       has to be one of the ten layers above. A sheet quietly joining -- `sheet === "menu"`,
       GalleryMobile's own useSheet, anything -- fails here by not being on it. */
    const registered = [];
    for (const f of [mobile, control, create, health, src("components/GalleryMobile.jsx"),
      src("components/FolioMobile.jsx"), src("components/ContestsMobile.jsx")]) {
      for (const m of f.matchAll(/useLayerHistory\(([^;]*?)\);/g)) registered.push(m[1]);
    }
    assert.deepEqual(registered.sort(), [
      "!!contactSheetTarget, closeContactSheet",
      "!!contestEntry, closeContestEntry",
      "!!detailsFor, closeDetails",
      "!!screen, closeScreen",
      "advOpen, closeAdv",
      "brandOpen, closeBrand",
      "dupOpen, closeDup",
      "folioOpen, closeFolio",
      "lbIndex != null, closeLightbox",
      "simOn, clearSimilar",
    ]);
    assert.doesNotMatch(src("components/GalleryMobile.jsx"), /useLayerHistory/);
    // ...and the two chrome primitives still say why: a sheet has a scrim that catches
    // the tap-outside, a screen states in its own file that it does not.
    assert.match(src("components/MobileSheet.jsx"), /catching the tap-outside/);
    assert.match(src("components/MobileScreen.jsx"),
      /no scrim and no onClick-outside-to-close; `onClose`\s*\n?\s*fires from the chevron alone/);
  });

  test("the listener binds once and is never removed", () => {
    assert.match(manager, /if \(!bound\) \{ bound = true; window\.addEventListener\("popstate", onPop\); \}/);
    assert.doesNotMatch(manager, /removeEventListener\("popstate"/);
  });
});

// ------------------------------------------------------------------- 2. the pager lands
describe("a page the owner asked for lands at its top", () => {
  const userLoad = mobile.slice(mobile.indexOf("const userLoad = useCallback((p, replace) => {"),
                                mobile.indexOf("  }, [lib.load]);"));

  test("the reset rides the OWNER's load, and reads the page under the scroller before it leaves", () => {
    assert.match(userLoad, /const from = shownPageRef\.current;/);
    assert.ok(userLoad.indexOf("const from = shownPageRef.current;") < userLoad.indexOf("return lib.load("),
      "the page under the scroller has to be read before the request leaves, or it is "
      + "already the page that just landed");
    assert.match(userLoad, /if \(d && d\.page !== from && bodyRef\.current\) bodyRef\.current\.scrollTop = 0;/);
    // .glm-body is the phone's real scroller, not the window (gallery-mobile.css)
    assert.match(mobile, /className="glm-body" ref=\{bodyRef\}/);
  });

  test("a superseded response lands nothing -- `d` is undefined and the winner does its own", () => {
    // useLibrary's reqSeq guard returns undefined for a request a newer one overtook.
    assert.match(src("hooks/useLibrary.js"), /if \(seq !== reqSeq\.current\) return;/);
    assert.match(userLoad, /if \(d && /);
  });

  test("the background refresh is NOT touched: it goes through the raw load, which resets nothing", () => {
    // the completion handler's own reload, and the three mutation aftermaths
    assert.match(mobile, /genLoadRef\.current\(1, true\)\.then\(/);
    assert.match(mobile, /const afterPublishOrTrain = async \(\) => \{ lib\.load\(1, true\); \};/);
    assert.doesNotMatch(mobile, /genLoadRef\.current = userLoad/);
  });

  test("shownPageRef mirrors the settled page, and is not the perch guard's read", () => {
    const mirror = mobile.slice(mobile.indexOf("  useEffect(() => {\n    genLoadRef.current = lib.load;"),
                                mobile.indexOf("  });", mobile.indexOf("genLoadRef.current = lib.load;")));
    assert.match(mirror, /shownPageRef\.current = lib\.page;/);
    // the perch still reads what the owner ASKED for -- untouched by this pass
    assert.match(mobile, /if \(nav\.inFlight \|\| nav\.want !== 1\) return;/);
  });
});

// ------------------------------------------------------------- 3. a sheet holds its own
describe("a sheet contains its scroll, the same way a screen already did", () => {
  test("both latches, matching the :has() idiom the screens use", () => {
    assert.match(glmCss, /\.glm-body:has\(\.glm-screen\) \{ overflow: hidden; \}/);   // 2026-09-05, untouched
    assert.match(glmCss, /\.glm-body:has\(\.glm-sheet\) \{ overflow: hidden; \}/);
    const sheet = glmCss.slice(glmCss.indexOf(".glm-sheet { position: fixed"),
                               glmCss.indexOf(".glm-sheet.closing"));
    assert.match(sheet, /overscroll-behavior: contain;/);
  });

  test("the two surfaces the 2026-09-05 hardening missed have it now", () => {
    const idm = idmCss.slice(idmCss.indexOf(".idm-body {"), idmCss.indexOf(".idm-frame {"));
    assert.match(idm, /overscroll-behavior: contain;/);
    const fm = fmCss.slice(fmCss.indexOf(".fm-scroll {"), fmCss.indexOf(".fm-loading"));
    assert.match(fm, /overscroll-behavior: contain;/);
    // and the ones that already had it still do
    assert.match(glmCss, /\.glm-screen-body \{[\s\S]{0,200}overscroll-behavior: contain;/);
  });
});

// --------------------------------------------------------------- 4. each tab's own place
describe("each tab keeps its own scroll", () => {
  const memo = mobile.slice(mobile.indexOf("  const tabScrollRef = useRef({});"),
                            mobile.indexOf("  }, []);", mobile.indexOf("  const tabScrollRef")));

  test("the RESTORE is a layout effect keyed on the tab", () => {
    assert.match(memo, /useLayoutEffect\(\(\) => \{\n\s+tabRef\.current = tab;/);
    assert.match(memo, /el\.scrollTop = tabScrollRef\.current\[tab\] \|\| 0;/);
    assert.match(memo, /\}, \[tab\]\);/);
  });

  test("the SAVE is a scroll listener -- an effect cleanup reads an already-clamped offset", () => {
    /* The shape that does NOT work, and the reason this guard is worth its line: React
       runs a layout effect's cleanup after the commit has swapped the tab's contents, and
       all three tabs share one scroller, so the browser has already clamped the offset to
       the incoming tab's height. Measured: leaving the Gallery at 500 recorded 30. */
    assert.match(memo, /el\.addEventListener\("scroll", onScroll, \{ passive: true \}\);/);
    assert.match(memo, /tabScrollRef\.current\[tabRef\.current\] = el\.scrollTop;/);
    assert.match(memo, /return \(\) => el\.removeEventListener\("scroll", onScroll\);/);
    // ...and no teardown-time read of the shared scroller is left anywhere
    assert.doesNotMatch(memo, /return \(\) => \{[^}]*tabScrollRef\.current\[[^\]]*\] = el\.scrollTop/);
    // ...and the reason is written down where the next reader will meet it
    assert.match(mobile, /the browser has already clamped the offset to the INCOMING tab's height/);
  });

  test("neither half fights MobileScreen's park -- a pushed screen holds this scroller at 0", () => {
    assert.match(memo, /if \(!el \|\| el\.querySelector\("\.glm-screen"\)\) return;/);
    assert.match(memo, /if \(el\.querySelector\("\.glm-screen"\)\) return;/);
    // the park itself, in the file that owns it, unchanged
    assert.match(src("components/MobileScreen.jsx"), /const was = host\.scrollTop;\n\s+host\.scrollTop = 0;/);
  });

  test("◈ Similar's own save/restore is untouched and still the library's", () => {
    assert.match(mobile, /libScrollRef\.current = bodyRef\.current \? bodyRef\.current\.scrollTop : 0;/);
    assert.match(mobile, /if \(bodyRef\.current\) bodyRef\.current\.scrollTop = y;/);
  });
});

// -------------------------------------------------------- 5. the insets are real at last
describe("viewport-fit=cover, so every safe-area inset in this app means something", () => {
  test("every shell a phone reaches asks for it, including the dev twin", () => {
    const metas = server.match(/<meta name="viewport" content="[^"]*">/g) || [];
    assert.equal(metas.length, 3, "the served shells are " + JSON.stringify(metas));
    for (const m of metas) {
      assert.match(m, /viewport-fit=cover/, m + " does not open the safe area");
      assert.match(m, /width=device-width, initial-scale=1/, m + " lost the rest of the meta");
    }
    assert.match(devShell, /<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">/);
  });

  test("the phone's top chrome now reads the top inset, as its own file already reads the bottom one", () => {
    assert.match(glmCss, /--glm-safetop: max\(0px, calc\(env\(safe-area-inset-top\) - 12px\)\);/);
    assert.match(glmCss, /height: calc\(172px \+ var\(--glm-safetop\)\);/);
    assert.match(glmCss, /\.glm-hero-icons \{[^}]*top: max\(12px, env\(safe-area-inset-top\)\);/);
    assert.match(glmCss, /\.glm-hero-stats \{[^}]*top: calc\(57px \+ var\(--glm-safetop, 0px\)\);/);
    // the bottom edges this file has always guarded, still guarded
    assert.match(glmCss, /padding: 4px 0 max\(14px, env\(safe-area-inset-bottom\)\);/);
  });
});

// ---------------------------------------------------------------- 6. the last raw trophy
test("the Folio's own title chip wears the drawn trophy, not the emoji", () => {
  assert.match(folioMobile, /<div className="fm-titlechip"><Icon name="folio" \/> Folio<\/div>/);
  assert.doesNotMatch(folioMobile, /🏆/);
  assert.match(folioMobile, /import Icon from "\.\.\/icons\/Icons\.jsx";/);
  // sized where every other icon's ratio is set, beside the note that explains it
  assert.match(iconCss, /\.fm-titlechip \.mgico \{ width: 1\.3em; height: 1\.3em;/);
  // the hero button that opens this screen wears the same one (Glyph Ledger, 2026-09-05)
  assert.match(mobile, /glm-iconbtn-gold[\s\S]{0,140}<Icon name="folio" \/><\/button>/);
});
