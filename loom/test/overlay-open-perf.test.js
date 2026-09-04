import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE OVERLAY-OPEN RENDER PATH (2026-09-04). Source-level guards, the established pattern
   for this runner -- there is no React test renderer here (see contestSyncFlow.js's own
   header for why the pure logic is extracted instead), so what CAN be pinned is the
   structure the behaviour rests on. Every assertion below guards a property that silently
   stops paying the moment someone edits past it:

     · a memo that is still applied,
     · props that are still referentially stable (one inline arrow at the call site and the
       memo compares unequal every render -- strictly slower than no memo at all),
     · a scrim whose blur is still applied AFTER the fade rather than animated with it,
     · the reserved scrollbar gutter that stops the open from resizing the viewport,
     · the mutation seams that purge the read cache.

   None of these can fail loudly at runtime: the app keeps working, just slowly again. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings are normalized on read: the repo stores LF (.gitattributes `* text=auto`)
// while Windows checks out CRLF, and several assertions below are line-anchored.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const app = src("App.jsx");
const grid = src("components/Grid.jsx");
const drawer = src("components/GenerateDrawer.jsx");
const library = src("hooks/useLibrary.js");
const overlays = src("styles/overlays.css");
const styles = src("styles.css");
const contests = src("components/ContestsOverlay.jsx");
const publish = src("components/PublishOverlay.jsx");
const jobs = src("notify/jobs.js");

/** The attribute block of a single JSX element, from `<Name` to the `>` that closes the
    opening tag. The match requires an ATTRIBUTE right after the name, so a `<Grid>` written
    inside a prose comment is not mistaken for the call site. Good enough here because none
    of these call sites nest an element inside an attribute. */
function propsOf(source, name) {
  const m = source.match(new RegExp("<" + name + "\\s+\\w+=\\{"));
  assert.ok(m && m.index > 0, "no <" + name + "> call site found");
  const end = source.indexOf(">", m.index);
  assert.ok(end > m.index);
  return source.slice(m.index, end);
}

describe("the two memoized children", () => {
  test("Grid is exported through React.memo", () => {
    assert.match(grid, /export default React\.memo\(Grid\);/);
    assert.doesNotMatch(grid, /export default function Grid/);
  });

  test("GenerateDrawer is exported through React.memo", () => {
    assert.match(drawer, /export default React\.memo\(GenerateDrawer\);/);
    assert.doesNotMatch(drawer, /export default function GenerateDrawer/);
  });
});

describe("the memo only pays if the props stay referentially stable", () => {
  test("no inline arrow function is handed to <Grid>", () => {
    // The failure this catches is invisible: an inline arrow makes that prop a new value on
    // every render, so React.memo compares unequal every time and the whole grid
    // re-reconciles anyway -- plus the cost of the comparison.
    assert.doesNotMatch(propsOf(app, "Grid"), /=>/);
  });

  test("no inline arrow function is handed to <GenerateDrawer>", () => {
    assert.doesNotMatch(propsOf(app, "GenerateDrawer"), /=>/);
  });

  test("every callback <Grid> takes is useCallback'd (or a setState)", () => {
    for (const name of ["goToPage", "openDetails", "rate", "openContextMenu",
                        "filterBySeries", "filterByBatch"]) {
      assert.match(app, new RegExp("const " + name + " = useCallback\\("), name);
    }
    // openLightbox={setLbIndex} / onFocusCard={setGridFocus}: setState functions, stable by
    // React's own contract, so they need nothing.
    const props = propsOf(app, "Grid");
    assert.match(props, /openLightbox=\{setLbIndex\}/);
    assert.match(props, /onFocusCard=\{setGridFocus\}/);
  });

  test("toggleSelected is useCallback'd in useLibrary -- it is a <Grid> prop too", () => {
    assert.match(library, /const toggleSelected = useCallback\(\(mid\) =>/);
    assert.match(propsOf(app, "Grid"), /toggleSelected=\{toggleSelected\}/);
  });

  test("the three-listener effect has its dep array back", () => {
    // With no array at all it tore down and re-added mg-gen-done / mg-submit / mg-result on
    // EVERY render of the shell.
    const i = app.indexOf('window.addEventListener("mg-gen-done", onGenDone);');
    assert.ok(i > 0);
    const tail = app.slice(i, i + 1400);
    assert.match(tail, /\}, \[load\]\);/);
    assert.doesNotMatch(tail, /\}\); \/\/ eslint-disable-line react-hooks\/exhaustive-deps/);
  });
});

describe("the scrim blurs AFTER the fade, not during it", () => {
  test("the fade rule itself carries no backdrop-filter", () => {
    const rule = overlays.slice(overlays.indexOf(".mgv-scrim { position: fixed"),
                                overlays.indexOf("@keyframes mgvScrimBlur"));
    assert.doesNotMatch(rule, /backdrop-filter/,
                        "a blur under an opacity animation re-blurs the whole viewport per frame");
    assert.match(rule, /animation: mgvFade \.3s ease both, mgvScrimBlur [^;]*forwards;/);
  });

  test("the deferred keyframe fills FORWARDS only, and still lands on blur(7px)", () => {
    assert.match(overlays, /@keyframes mgvScrimBlur \{\s*to \{[^}]*backdrop-filter: blur\(7px\);/);
    // `both` would fill BACKWARDS too -- the blur would be on for the whole fade, which is
    // the exact thing being avoided.
    assert.doesNotMatch(overlays, /mgvScrimBlur [^;]*\bboth;/);
  });

  test("reduced motion still gets the blur, since it has no animation to defer behind", () => {
    const rm = overlays.slice(overlays.indexOf("@media (prefers-reduced-motion: reduce)"));
    assert.match(rm, /\.mgv-scrim, \.mgv-slab \{ animation: none; \}/);
    assert.match(rm, /\.mgv-scrim \{[^}]*backdrop-filter: blur\(7px\);/);
  });
});

describe("opening an overlay must not resize the viewport", () => {
  test("the scrollbar gutter is reserved on the document root", () => {
    // body{overflow:hidden} otherwise widens the page by the scrollbar, which fires every
    // ResizeObserver in the shell on the frame the overlay is animating in.
    assert.match(styles, /^html \{ color-scheme: dark; scrollbar-gutter: stable; \}$/m);
  });

  test("useScrollLock keeps a feature-detected padding fallback for engines without it", () => {
    const lock = src("hooks/useScrollLock.js");
    assert.match(lock, /CSS\.supports\("scrollbar-gutter", "stable"\)/);
    assert.match(lock, /document\.body\.style\.paddingRight = bar \+ "px";/);
  });
});

describe("remote images do not block the open frame", () => {
  test("every contest cover is lazy + async-decoded", () => {
    const imgs = contests.match(/<img src=\{[a-zA-Z.]*cover_url\}[^>]*>/g) || [];
    assert.equal(imgs.length, 3, "three board covers -- featured, official, community");
    for (const tag of imgs) {
      assert.match(tag, /loading="lazy"/, tag);
      assert.match(tag, /decoding="async"/, tag);
    }
  });

  test("Publish's hero decodes off the main thread -- and still loads the full-res image", () => {
    assert.match(publish, /<img src=\{"\/full\/" \+ encodeURIComponent\(mid\)\} alt="" decoding="async" \/>/);
    assert.doesNotMatch(publish, /<img src=\{"\/thumbs\//, "WHAT it loads is the owner's design");
  });
});

describe("the invalidation seams", () => {
  test("App's one mutation seam purges the read cache before it reloads", () => {
    const seam = app.slice(app.indexOf("const afterMutation = async () => {"),
                           app.indexOf("const actions = {"));
    for (const p of ["/api/your-art", "/api/myart/items", "/api/next/detail/",
                     "/api/achievements", "/api/health"]) {
      assert.ok(seam.includes(p), p);
    }
  });

  test("a finished job purges, and adds NO request to the spend-critical poller", () => {
    // jobs.js's contract at the top of that file: this module never submits and never
    // spends. invalidate() drops entries from a client-side map and issues no request --
    // which is the only reason it is allowed in here at all.
    assert.match(jobs, /invalidate\(\["\/api\/achievements", "\/api\/health", "\/api\/panel\/summary"/);
    assert.equal((jobs.match(/\bfetch\(/g) || []).length, 1,
                 "the one /api/task-status read, exactly as before");
    assert.doesNotMatch(jobs, /apiGet\(/);
  });

  test("the reads that must never be seeded from cache are named, and are not", () => {
    const panel = src("hooks/useControlPanel.js");
    // /api/panel/status is the live-job resume check; /api/ping is the restart watch.
    assert.doesNotMatch(panel, /peek\("\/api\/panel\/status"\)/);
    assert.doesNotMatch(panel, /peek\("\/api\/ping"\)/);
    assert.doesNotMatch(panel, /put\("\/api\/panel\/status"/);
    assert.doesNotMatch(panel, /put\("\/api\/ping"/);
    // Publish's per-image record: a stale artwork_id re-enables the Publish button.
    assert.doesNotMatch(publish, /peek\("\/api\/next\/detail\//);
    assert.doesNotMatch(publish, /put\("\/api\/next\/detail\//);
  });

  test("the store itself refuses to keep a csrf, so no call site has to remember", () => {
    const store = src("hooks/swrStore.js");
    assert.match(store, /if \("csrf" in data\) \{/);
    assert.match(store, /delete keep\.csrf;/);
  });
});
