import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE LIBRARY STANDS STILL (owner, 2026-09-05).

   The policy in one sentence: nothing moves the owner's view of the library except his own
   hands. A generation finishing announces itself -- the completion toast, the Activity row
   whose thumbnail opens the new record -- and never restacks the grid under a reader.

   What it replaced: App.jsx's `const refresh = () => { load(1, true); ... }`, fired by
   mg-gen-done (gen/submitTask.js dispatches it for every edit / enhance / fix / scene /
   generate / upscale) and by mg-result (the video drawer). Reading page 7, a job you queued
   ten minutes ago lands, and page 1 replaces the grid you were reading.

   tests/test_render_harness.py::test_a_finished_generation_never_moves_the_page_the_owner_
   is_reading measures the DESKTOP behaviour in a real browser: page 2 stays, page 1
   refreshes. The completion-vs-navigation RACE is measured in that same real browser on
   both shells -- ..._never_out_races_the_owners_own_page_change on the desktop and
   ..._on_the_phone at a real 390px viewport, each holding the owner's page-2 request
   mid-flight and firing the completion into that window. These are the source-structure
   guards for what those cannot see -- the phone's announce-only half, the selection prune,
   and the third hard-coded jump the same policy governs (Details' onDeleted) -- plus the
   shape of the intent ref on both shells, so the two stay one idiom. Same pattern and same
   reason as loom/test/overlay-open-perf.test.js: no React test renderer here, so what can
   be pinned is the structure the behaviour rests on. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite: the repo stores LF
// (.gitattributes `* text=auto`) while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const app = src("App.jsx");
const mobile = src("components/AppMobile.jsx");
const library = src("hooks/useLibrary.js");

/** The body of the arrow function assigned to `name`, from the `=>` to the line that closes
    it at the given indent. Enough to read one handler in isolation. */
function bodyOf(source, opener, closer) {
  const i = source.indexOf(opener);
  assert.ok(i >= 0, "not found: " + opener);
  const j = source.indexOf(closer, i);
  assert.ok(j > i, "no close for: " + opener);
  return source.slice(i, j);
}

describe("the desktop shell: a completion refreshes only from the default perch", () => {
  const refresh = bodyOf(app, "const refresh = () => {", "    };");

  test("the unconditional half is the credits chip, and only the credits chip", () => {
    assert.match(refresh, /fetchAccount\(\)\.then\(setAccount\);/);
    // The bare page-1 jump is GONE. This exact line is what the policy retired.
    assert.doesNotMatch(app, /const refresh = \(\) => \{ load\(1, true\); fetchAccount\(\)/);
  });

  test("page 1 is the gate, read off what the owner ASKED for", () => {
    assert.match(refresh, /const nav = navRef\.current;/);
    assert.match(refresh, /if \(nav\.inFlight \|\| nav\.want !== 1\) return;/);
    // ...and the gate comes BEFORE the load, not after it.
    assert.ok(refresh.indexOf("nav.want !== 1") < refresh.indexOf("load(1, true)"),
      "the page-1 guard must precede the load it guards");
    assert.match(refresh, /load\(1, true\)\.then\(/);
    // The stale-page read this replaced: `page` only becomes the page the owner asked for
    // when the SERVER answers, so a completion landing mid-flight read the page he was
    // leaving, passed, and won the reqSeq race against his own request.
    assert.doesNotMatch(refresh, /if \(pageRef\.current !== 1\) return;/);
  });

  test("the intent ref is written synchronously by every hand that asks for a page", () => {
    // navRef.want starts at the page the ADDRESS asked for, so a fresh ?page=3 visit is
    // not mistaken for page 1 for the whole of its opening request.
    assert.match(app, /const navRef = useRef\(\{ want: Math\.max\(1, initialPage \| 0\), inFlight: 0 \}\);/);
    // userLoad: intent + in-flight count written BEFORE the request leaves, and the same
    // promise handed back so every caller reads the answer exactly as before.
    const userLoad = bodyOf(app, "const userLoad = useCallback((p, replace) => {", "  }, [load]);");
    assert.match(userLoad, /navRef\.current\.want = p;/);
    assert.match(userLoad, /navRef\.current\.inFlight \+= 1;/);
    assert.match(userLoad, /navRef\.current\.inFlight = Math\.max\(0, navRef\.current\.inFlight - 1\);/);
    assert.match(userLoad, /return load\(p, replace\)\.then\(\(d\) => \{ settle\(\); return d; \}, \(e\) => \{ settle\(\); throw e; \}\);/);
    assert.ok(userLoad.indexOf("navRef.current.want = p") < userLoad.indexOf("return load(p, replace)"),
      "the intent must be on the record before the request leaves");
    // The three hands: the pager/arrow-key flip (goToPage), Back/Forward, and the viewer
    // stepping across a page boundary. None of them may call the raw load any more.
    const goTo = bodyOf(app, "const goToPage = useCallback((p) => {", "  }, [setUrl, userLoad]);");
    assert.match(goTo, /setUrl\(\{ page: p \}\);/);
    assert.match(goTo, /userLoad\(p, true\);/);
    assert.doesNotMatch(app, /const goToPage = useCallback\(\(p\) => \{\n    setUrl\(\{ page: p \}\);\n    load\(p, true\);/);
    const pop = bodyOf(app, "const onPop = () => {", "    };");
    assert.match(pop, /navRef\.current\.want = p;/);
    assert.match(pop, /if \(p !== pageRef\.current\) userLoadRef\.current\(p, true\);/);
    assert.match(app, /page=\{page\} pages=\{pages\} loadPage=\{userLoad\}/);
  });

  test("`page` reconciles the intent only when nothing of the owner's is still in the air", () => {
    const mirror = bodyOf(app, "  useEffect(() => {\n    pageRef.current = page;", "  });");
    assert.match(mirror, /loadRef\.current = load;/);
    assert.match(mirror, /userLoadRef\.current = userLoad;/);
    assert.match(mirror, /if \(!navRef\.current\.inFlight && total != null\) navRef\.current\.want = page;/);
    assert.match(mirror, /viewRef\.current = \{ similar: similarFor, series: seriesFor, lb: lbIndex \};/);
  });

  test("the three untouched-library surfaces refuse the refresh, at page 1 as much as anywhere", () => {
    assert.match(app, /const viewRef = useRef\(\{ similar: null, series: null, lb: null \}\);/);
    assert.match(refresh, /const view = viewRef\.current;/);
    // lbIndex 0 is a real open viewer: `!= null`, never a truthiness test.
    assert.match(refresh, /if \(view\.similar \|\| view\.series \|\| view\.lb != null\) return;/);
    assert.ok(refresh.indexOf("view.lb != null") < refresh.indexOf("load(1, true)"),
      "the overlay guard must precede the load it guards");
    // WHY the viewer is in that list: it reads `items` POSITIONALLY, so a swap at page 1 --
    // where the new picture arrives at the TOP -- slides every index by one.
    const lightbox = src("components/Lightbox.jsx");
    assert.match(lightbox, /const it = items\[index\];/);
  });

  test("both completion channels ride the one refresh, and the dep array is intact", () => {
    const i = app.indexOf('window.addEventListener("mg-gen-done", onGenDone);');
    assert.ok(i > 0);
    assert.match(app, /const onGenDone = \(\) => \{ refresh\(\); if \(window\.Ach\) window\.Ach\.check\(\); \};/);
    const result = bodyOf(app, "const onResult = () => {", "    };");
    assert.match(result, /refresh\(\);/);
    assert.match(app.slice(i, i + 1400), /\}, \[load\]\);/);
  });

  test("the selection is pruned after the background swap, never left pointing at nothing", () => {
    assert.match(refresh, /if \(data\) pruneSelected\(setSelected, data\.items\);/);
    assert.match(app, /import useLibrary, \{ filterQueryString, pruneSelected \} from "\.\/hooks\/useLibrary\.js";/);
  });
});

describe("Details' delete reloads the page it was opened from", () => {
  const deleted = bodyOf(app, "onDeleted={() => {", "              }}");

  test("the third hard-coded jump to page 1 is gone", () => {
    assert.doesNotMatch(app, /onDeleted=\{\(\) => \{ closeDetails\(\); load\(1, true\); \}\}/);
    assert.match(deleted, /closeDetails\(\);/);
    assert.match(deleted, /const p = Math\.max\(1, pageRef\.current\);/);
    assert.match(deleted, /load\(p, true\)\.then\(/);
  });

  test("an emptied page steps DOWN one, and emptiness is read off the response", () => {
    assert.match(deleted, /if \(p > 1 && !\(data\.items \|\| \[\]\)\.length\) \{/);
    assert.match(deleted, /load\(p - 1, true\)\.then\(/);
    // never below page 1
    assert.doesNotMatch(deleted, /load\(0, true\)/);
  });

  test("and it prunes the selection against whichever page actually lands", () => {
    // The third items swap the policy governs. Without this a tick left pointing at the
    // picture just deleted -- or at anything the reflow pushed off the end -- stays armed
    // for the next bulk action while being nowhere on screen.
    assert.match(deleted, /pruneSelected\(setSelected, data\.items\);/);
    assert.match(deleted, /if \(down\) pruneSelected\(setSelected, down\.items\);/);
    assert.ok(deleted.indexOf("if (down) pruneSelected") < deleted.indexOf("pruneSelected(setSelected, data.items);"),
      "the stepped-down page prunes against ITS OWN response, not the empty one above it");
  });
});

describe("the phone learns completions exist -- announce-only", () => {
  test("AppMobile listens on BOTH channels the desktop does", () => {
    assert.match(mobile, /window\.addEventListener\("mg-gen-done", onDone\);/);
    assert.match(mobile, /document\.addEventListener\("mg-result", onDone\);/);
    assert.match(mobile, /window\.removeEventListener\("mg-gen-done", onDone\);/);
    assert.match(mobile, /document\.removeEventListener\("mg-result", onDone\);/);
  });

  test("it refreshes the credits chip and nudges the Folio, guarded like every window.* call", () => {
    const onDone = bodyOf(mobile, "const onDone = () => {", "    };");
    assert.match(onDone, /fetchAccount\(\)\.then\(setAccount\);/);
    assert.match(onDone, /if \(window\.Ach\) window\.Ach\.check\(\);/);
  });

  test("the library moves only from the phone's own default view: page 1, and not under ◈ Similar", () => {
    const onDone = bodyOf(mobile, "const onDone = () => {", "    };");
    // Read off what the owner ASKED for, exactly as the desktop's guard is.
    assert.match(onDone, /const nav = navRef\.current;/);
    assert.match(onDone, /if \(nav\.inFlight \|\| nav\.want !== 1\) return;/);
    assert.match(onDone, /if \(genSimilarRef\.current\) return;/);
    assert.ok(onDone.indexOf("nav.want !== 1") < onDone.indexOf("genLoadRef.current(1, true)"),
      "the default-view guard must precede the load it guards");
    assert.ok(onDone.indexOf("genSimilarRef.current) return") < onDone.indexOf("genLoadRef.current(1, true)"),
      "the ◈ guard must precede the load it guards");
    assert.match(onDone, /genLoadRef\.current\(1, true\)\.then\(/);
    assert.match(onDone, /if \(data\) pruneSelected\(setLibSelected, data\.items\);/);
    // The stale-page read this replaced: `lib.page` only becomes the page the owner
    // tapped for when the SERVER answers, so a completion landing mid-flight read the
    // page he was leaving, passed, and won the reqSeq race against his own request.
    assert.doesNotMatch(mobile, /genPageRef/);
  });

  test("refs, because the listeners mount once and load's identity follows the filters", () => {
    assert.match(mobile, /const genLoadRef = useRef\(lib\.load\);/);
    assert.match(mobile, /const genSimilarRef = useRef\(similarFor\);/);
    assert.match(mobile, /genLoadRef\.current = lib\.load;/);
    assert.match(mobile, /genSimilarRef\.current = similarFor;/);
  });

  test("the phone's intent ref is written synchronously by every hand that asks for a page", () => {
    // `want` starts at 1 and not at anything address-derived, because this shell keeps NO
    // page in the URL at all -- page 1 is where it always opens. That absence is also why
    // there is no Back/Forward hand to cover the way App.jsx's popstate is.
    assert.match(mobile, /const navRef = useRef\(\{ want: 1, inFlight: 0 \}\);/);
    // userLoad: intent + in-flight count written BEFORE the request leaves, and the same
    // promise handed back -- LightboxMobile's page-boundary step reads data.items off it.
    const userLoad = bodyOf(mobile, "const userLoad = useCallback((p, replace) => {", "  }, [lib.load]);");
    assert.match(userLoad, /navRef\.current\.want = p;/);
    assert.match(userLoad, /navRef\.current\.inFlight \+= 1;/);
    assert.match(userLoad, /navRef\.current\.inFlight = Math\.max\(0, navRef\.current\.inFlight - 1\);/);
    // `settle` takes the landed response as of 2026-09-06 -- the page the owner asked for
    // lands at its TOP, and that reset rides this path precisely so it can never touch a
    // background refresh (see the pager test below). Both arms still settle the count, and
    // the same promise is still handed straight back to the caller.
    assert.match(userLoad, /return lib\.load\(p, replace\)\.then\(\(d\) => \{ settle\(d\); return d; \}, \(e\) => \{ settle\(\); throw e; \}\);/);
    assert.ok(userLoad.indexOf("navRef.current.want = p") < userLoad.indexOf("return lib.load(p, replace)"),
      "the intent must be on the record before the request leaves");
    // The two hands this surface has. The pager takes `load` as a prop out of the {...lib}
    // spread, so userLoad has to be passed AFTER the spread to win it.
    assert.match(mobile, /\{\.\.\.lib\}\n\s+load=\{userLoad\}/);
    assert.match(mobile, /page=\{lib\.page\} pages=\{lib\.pages\} loadPage=\{userLoad\}/);
    // ...and neither may reach the raw load any more.
    assert.doesNotMatch(mobile, /loadPage=\{lib\.load\}/);
    // GalleryMobile's pager is the ONE thing that prop drives, and it still calls it.
    const grid = src("components/GalleryMobile.jsx");
    assert.match(grid, /onClick=\{\(\) => load\(page - 1, true\)\}/);
    assert.match(grid, /onClick=\{\(\) => load\(page \+ 1, true\)\}/);
  });

  test("`page` reconciles the intent only when nothing of the owner's is still in the air", () => {
    const mirror = bodyOf(mobile, "  useEffect(() => {\n    genLoadRef.current = lib.load;", "  });");
    assert.match(mirror, /genSimilarRef\.current = similarFor;/);
    // The same rule the desktop reconciles by, so a filter / per-page / collection change
    // resetting the grid to page 1 hands the perch back.
    assert.match(mirror, /if \(!navRef\.current\.inFlight && lib\.total != null\) navRef\.current\.want = lib\.page;/);
  });

  test("the mutation reloads stay on the RAW load, exactly as the desktop's afterMutation does", () => {
    // afterImported / afterDuplicatesResolved / afterPublishOrTrain / Details' onDeleted
    // are aftermaths, not the owner asking for a page: they jump to 1 on their own and the
    // reconciliation rule hands the perch back when they land. userLoad would claim an
    // intent he never expressed.
    assert.match(mobile, /const afterPublishOrTrain = async \(\) => \{ lib\.load\(1, true\); \};/);
    assert.match(mobile, /onDeleted=\{\(\) => \{ closeDetails\(\); lib\.load\(1, true\); \}\}/);
  });

  test("STILL no Jobs.register on the phone shell -- registration belongs to the submit road", () => {
    assert.doesNotMatch(mobile, /Jobs\.register\(/);
  });
});

describe("pruneSelected: the one prune, shared by both shells", () => {
  const fn = bodyOf(library, "export function pruneSelected(setSelected, items) {",
                    "\n}\n");

  test("it is exported from the hook that owns `selected`, and both shells import it", () => {
    assert.match(library, /export function pruneSelected\(setSelected, items\) \{/);
    assert.match(app, /pruneSelected\(setSelected, data\.items\)/);
    assert.match(mobile, /import useLibrary, \{ pruneSelected \} from "\.\.\/hooks\/useLibrary\.js";/);
  });

  test("it reads the previous Set through the updater, and returns it UNCHANGED when nothing dropped", () => {
    assert.match(fn, /setSelected\(\(old\) => \{/);
    assert.match(fn, /if \(!dropped\) return old;/);
    assert.match(fn, /const live = new Set\(\(items \|\| \[\]\)\.map\(\(it\) => it\.media_id\)\);/);
  });

  test("afterMutation is untouched: a USER-initiated mutation still clears the set outright", () => {
    assert.match(app, /const afterMutation = async \(\) => \{/);
    const after = bodyOf(app, "const afterMutation = async () => {", "  };");
    assert.match(after, /setSelected\(new Set\(\)\);/);
    assert.doesNotMatch(after, /pruneSelected/);
  });
});
