import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// B3 of the 2026-09-04 Gallery Chrome handoff changed where a stack OPENS. It used to
// be a navigation -- the sid went into the library's own `series` filter and the whole
// gallery re-loaded as that series' members, with Clear as the only way back. It opens a
// MODAL over the gallery now (SeriesModal.jsx), the library underneath is untouched, and
// Esc goes straight back. The (c) group below pins the new wiring; everything else about
// stacking -- the fold, the badges, the deck, the not-selectable rules -- is unchanged.
//
// Issue #34 direction B -- grid stacking, the UI half. Source guards, short and
// literal like placard.test.js: the front-end can't be booted headless here (React
// + a live login-gated API), so these pin the exact wiring the build depends on --
// the persisted group toggle only sends group=series when it's on, a series||batch
// unit renders the stack markup + the right badge, opening a stack NAVIGATES (series
// -> the series filter, batch -> the existing View-batch path), hero never features a
// stack, a stack is not selectable, and a plain singleton is byte-for-byte today.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");

const grid = src("gallery/src/components/Grid.jsx");
const app = src("gallery/src/App.jsx");
const { buildUrl } = await import("../../gallery/src/gen/urlState.js");
const useLib = src("gallery/src/hooks/useLibrary.js");
const tray = src("gallery/src/components/FiltersPanel.jsx");
const css = src("gallery/src/styles/grid.css");

describe("(a) group=series rides the query ONLY when the toggle is on (useLibrary + App)", () => {
  test("the Stack-sessions toggle is a persisted view-setting, default off, like layout", () => {
    // App owns it, persists to mg_gallery_group, defaults to '' (off), and hands it
    // to the hook -- the exact shape `layout` uses (mg_gallery_layout).
    assert.ok(app.includes('localStorage.getItem("mg_gallery_group") === "series"'));
    assert.ok(app.includes('localStorage.setItem("mg_gallery_group", v)'));
    assert.ok(app.includes("useLibrary({ initialPage, group })"));
    // the hook's own default is off
    assert.ok(useLib.includes('export default function useLibrary({ initialPage = 1, group = "" } = {})'));
  });
  test("load() sends group=series ONLY when on AND no drill-down is active; series always rides", () => {
    // the exact conditional: grouping is suppressed while a series/batch drill-down is
    // open (opening a stack IS the ungrouped members view), so the fold never fights it.
    assert.ok(useLib.includes(
      'group: (group === "series" && !adv.series && !adv.batch) ? "series" : "",'));
    assert.ok(useLib.includes("series: adv.series,"));
    // flipping the toggle re-fetches page 1: group is a load() dependency, so the
    // mount effect re-fires (the same path media/sort/rating take).
    assert.ok(useLib.includes("[applied, media, shelf, perPage, adv, group]"));
    // series is a real adv field (mirrors batch) so Reset/Clear drop it
    assert.ok(useLib.includes('series: "",'));
  });
});

describe("(b) a series||batch unit renders the stack markup + the right badge (Grid.jsx)", () => {
  test("stackKind classifies a unit; the card gains .mgg-stack and the deck layers", () => {
    assert.ok(grid.includes(
      'const stackKind = (it) => (it.series ? "series" : it.batch ? "batch" : null);'));
    assert.ok(grid.includes("const stack = stackKind(it);"));
    assert.ok(grid.includes('(stack ? " mgg-stack" : "")'));
    // two offset shadow layers, behind the cover (DOM before .mgg-art)
    assert.ok(grid.includes('<span className="mgg-stack-layer back" aria-hidden="true" />'));
    assert.ok(grid.includes('<span className="mgg-stack-layer mid" aria-hidden="true" />'));
    assert.ok(grid.indexOf("mgg-stack-layer back") < grid.indexOf('<img className="mgg-art"'));
  });
  test("the badge: SERIES · Nv · M (SERIES-only on a video cover); BATCH · N", () => {
    assert.ok(grid.includes(
      '? (it.is_video ? "SERIES" : "SERIES · " + it.series.count_tasks + "v · " + it.series.count_images)'));
    assert.ok(grid.includes(': stack === "batch" ? "BATCH · " + it.batch.count'));
    // badge element class resolves to .mgg-series-badge / .mgg-batch-badge, top-left
    assert.ok(grid.includes('className={"mgg-" + stack + "-badge"}'));
  });
  test("the stamp prefers the SERIES title; a singleton keeps it.title exactly", () => {
    assert.ok(grid.includes(
      'const stampTitle = (stack === "series" && it.series.title) ? it.series.title : it.title;'));
    assert.ok(grid.includes("{stampTitle ? <span className=\"mgg-title\">{stampTitle}</span> : null}"));
  });
  test("badge-only on a stack (finding 2): no sibling strip, no ·vN suffix on a stacked face", () => {
    // the strip is redundant on a batch and misleading on a series (it lists only the
    // cover task's versions) -- so it's gated OFF for stacks; the badge is the only signal.
    assert.ok(grid.includes("const sibs = (it.task_id && !stack) ? siblings[it.task_id] : null;"));
    // the dial-in suffix likewise steps aside on a stack cover (the badge carries counts).
    assert.ok(grid.includes('(stack ? "" : seriesSuffix(it, seriesByTask))'));
  });
});

describe("(c) opening a stack: series -> the B3 modal, batch -> View-batch", () => {
  test("Grid routes a stack open to onOpenSeries(sid) / onOpenBatch(task_id)", () => {
    assert.ok(grid.includes("if (kind === \"series\" && onOpenSeries) onOpenSeries(it.series.sid);"));
    assert.ok(grid.includes("else if (kind === \"batch\" && onOpenBatch) onOpenBatch(it.batch.task_id);"));
  });
  test("B3: a series opens the MODAL -- openSeries, not the retired ?series= takeover", () => {
    // openSeries is useCallback'd like filterByBatch beside it: both are props on the
    // memoized <Grid>, and a fresh identity per render would defeat that memo.
    assert.ok(app.includes("const openSeries = useCallback((sid) => {"));
    assert.ok(app.includes("const closeSeries = useCallback(() => {"));
    // it opens the modal and addresses it -- it does NOT push the sid into the filters
    assert.ok(app.includes("setSeriesFor(sid);"));
    assert.ok(app.includes("setUrl({ series: sid });"));
    assert.ok(!app.includes("setAdv((old) => ({ ...old, series, batch:"),
      "the ?series= drill-down must no longer be SET from a stack click");
    assert.ok(!app.includes("filterBySeries"), "filterBySeries is retired");
    // the batch open is the EXISTING path, reused exactly and untouched
    assert.ok(app.includes("const filterByBatch = useCallback((batch) => {"));
    // both handed to the grid
    assert.ok(app.includes("onOpenSeries={openSeries}"));
    assert.ok(app.includes("onOpenBatch={filterByBatch}"));
    // ...and the modal is mounted on the sid, closing straight back
    assert.ok(app.includes("<SeriesModal sid={seriesFor} onClose={closeSeries}"));
  });
  test("B3: the modal is a place -- ?series=<sid> is read, written and popstate-restored", () => {
    const url = src("gallery/src/gen/urlState.js");
    assert.ok(url.includes("export function readSeries(search)"));
    assert.ok(url.includes('p.set("series", String(patchObj.series));'));
    assert.ok(app.includes("useState(() => readSeries(window.location.search))"));
    assert.ok(app.includes("setSeriesFor(readSeries(window.location.search));"));
  });
  test("B3: the rail, the sort and the run badge are the handoff's own (SeriesModal.jsx)", () => {
    const modal = src("gallery/src/components/SeriesModal.jsx");
    // the LINEAGE rail: an "All runs" head, then the runs on an indented descent line
    assert.ok(modal.includes("All runs"));
    assert.ok(modal.includes("marginLeft: 8 + i * 7"));
    assert.ok(modal.includes("Run {s.v}"));
    assert.ok(modal.includes("{s.n} img"));
    // facet chips AND with the run pick, rather than replacing it
    assert.ok(modal.includes("(run < 0 || t.rn === run + 1)"));
    assert.ok(modal.includes("active.every(([, , test]) => test(t.it))"));
    // the header sort pair, and the r-number badge that makes its order legible
    assert.ok(modal.includes(">run \u2116</button>"));
    assert.ok(modal.includes(">newest</button>"));
    assert.ok(modal.includes('badge: "r" + rn + "\u00b7" + i'));
    // Esc goes STRAIGHT back -- one key, one level
    assert.ok(modal.includes('if (e.key !== "Escape") return;'));
    assert.ok(modal.includes("Esc \u21a9 gallery"));
    // it reads the series itself; the library's own state is never touched
    assert.ok(modal.includes("fetchSeriesStack(sid)"));
  });
  test("the tray toggle flips group and lights when on", () => {
    assert.ok(tray.includes('onClick={() => setGroup(group !== "series")}'));
    assert.ok(tray.includes('active={group === "series"}'));
    assert.ok(tray.includes('label="Stack sessions"'));
    // B1 moved the layout picker OUT of this tray (it is the separator bar's glyph trio
    // now), so the chip leads the tray rather than following the picker.
    assert.ok(!tray.includes("<LayoutPicker"), "the layout picker left the tray in B1");
    assert.ok(!tray.includes("mgl-laybtn"));
  });
});

describe("(c1) opening a picture from the stack leaves exactly ONE history entry", () => {
  /* The shell's own history writer, reproduced from App.jsx (~L313) against the REAL
     builder: one URL per write, and a write that would not change the address is
     skipped. That skip is what makes the transition atomic -- the address is written
     once with both keys, and the two verbs that follow re-assert an address that is
     already correct, so neither of them pushes. */
  const makeShell = (search) => {
    const state = { path: "/", search };
    const pushed = [];
    const setUrl = (patch, replace) => {
      const url = buildUrl(patch, state.search, state.path);
      if (url === state.path + state.search) return;
      const q = url.indexOf("?");
      state.search = q < 0 ? "" : url.slice(q);
      if (!replace) pushed.push(url);
    };
    return { state, pushed, setUrl };
  };

  test("openDetailsFromSeries: one push, and the address carries both changes", () => {
    const { state, pushed, setUrl } = makeShell("?page=3&series=s7");
    // App.jsx's openDetailsFromSeries, in its own order
    setUrl({ series: null, image: "m9" });   // the ONE navigation
    setUrl({ series: null });                // closeSeries's own write -> no-op
    setUrl({ image: "m9" });                 // openDetails's own write -> no-op
    assert.deepEqual(pushed, ["/?page=3&image=m9"]);
    // ...and the page the library was on is still there, as ever
    assert.equal(state.search, "?page=3&image=m9");
  });

  test("the retired two-step pushed TWICE, and the middle entry was a place nobody visited", () => {
    // closeSeries() then openDetails(mid) -- what the modal used to be handed. Back from
    // the record landed on the bare library, with neither the stack nor the picture up.
    const { pushed, setUrl } = makeShell("?page=3&series=s7");
    setUrl({ series: null });
    setUrl({ image: "m9" });
    assert.equal(pushed.length, 2);
    assert.equal(pushed[0], "/?page=3");
  });

  test("App hands the modal the atomic handler, not the two-call arrow", () => {
    assert.ok(app.includes("const openDetailsFromSeries = useCallback((mid) => {"));
    assert.ok(app.includes("setUrl({ series: null, image: mid });"));
    assert.ok(app.includes("onOpenDetails={openDetailsFromSeries}"));
    assert.ok(!app.includes("onOpenDetails={(mid) => { closeSeries(); openDetails(mid); }}"),
      "the two-push series -> details transition is gone");
    // both verbs still run for their non-URL state work
    const h = app.slice(app.indexOf("const openDetailsFromSeries = useCallback((mid) => {"));
    const body = h.slice(0, h.indexOf("}, ["));
    assert.ok(body.includes("closeSeries();"));
    assert.ok(body.includes("openDetails(mid);"));
  });
});

describe("(c2) B1: the layout switcher is the separator bar's glyph strip", () => {
  const sep = src("gallery/src/components/SeparatorBar.jsx");
  const shell = src("gallery/src/styles/shell.css");
  test("four 28x28 cells, the handoff's own glyphs plus Hero's, no labels, beside SIZE", () => {
    assert.ok(sep.includes('["masonry", "\u25a4", "Masonry \u2014 aspect-true, no crop"]'));
    assert.ok(sep.includes('["grid", "\u25a6", "Grid \u2014 4:3, smart-cropped"]'));
    assert.ok(sep.includes('["hero", "\u25a3", "Hero \u2014 a large feature, the rest in a grid"]'));
    assert.ok(sep.includes('["timeline", "\u2261", "Timeline \u2014 date-banded, newest first"]'));
    assert.ok(sep.includes('className="mgx-lay"'));
    // it sits immediately before the SIZE pill
    assert.ok(sep.indexOf('className="mgx-lay"') < sep.indexOf('className="mgx-size"'));
    // 122px all in: 4 x 28 cells + three 2px gaps + 2px padding a side
    assert.match(shell, /\.mgx-laycell \{[^}]*width: 28px; height: 28px;/);
    assert.match(shell, /\.mgx-lay \{[^}]*gap: 2px; padding: 2px;/);
  });
  test("Hero is a CELL, not palette-only -- and the palette wears the cell's mark", () => {
    // 2026-09-05 (owner): the first B1 build shipped three cells and left Hero reachable
    // only from the command palette. Every layout the gallery renders is in the strip now.
    const cells = sep.slice(sep.indexOf("const LAYOUT_CELLS = ["), sep.indexOf("];", sep.indexOf("const LAYOUT_CELLS = [")));
    for (const key of ["masonry", "grid", "hero", "timeline"]) {
      assert.ok(cells.includes('"' + key + '"'), key + " has a cell in the strip");
    }
    assert.ok(!sep.includes("LAYOUT_TRIO"), "the trio is a quartet now");
    // the palette's Hero row carries the SAME glyph the cell does (\u25a3, not the old \u25a7)
    assert.ok(app.includes('["hero", "Hero", "\u25a3"]'));
    assert.ok(!app.includes('["hero", "Hero", "\u25a7"]'));
  });
  test("NO mobile switcher -- the control does not render below the desktop breakpoint", () => {
    assert.match(shell, /@media \(max-width: 860px\) \{ \.mgx-lay \{ display: none; \} \}/);
  });
  test("selection still persists in localStorage beside the size value (App owns both)", () => {
    assert.ok(app.includes('localStorage.setItem("mg_gallery_layout", v);'));
    assert.ok(app.includes('localStorage.setItem("mg_gallery_density", String(v));'));
    assert.ok(app.includes("layout={layout} setLayout={setLayout}"));
  });
});

describe("(d) hero never features a stack (Grid.jsx)", () => {
  test("the hero feature-pick skips a stack, like it already skips a video", () => {
    assert.ok(grid.includes(
      "const hero = (i % HERO_EVERY === 0) && !it.is_video && !stackKind(it);"));
  });
  test("the masonry feature-slot skips a stack too, for the same reason as hero", () => {
    // a stacked cover is a proxy for many, not a single showcase -- so it must not be
    // promoted into a 2-col feature cell any more than into a hero slot.
    assert.ok(grid.includes("if (arr[k].is_video || stackKind(arr[k])) continue;"));
  });
});

describe("(e) a stack is NOT selectable; clicking it opens its view (Grid.jsx)", () => {
  test("the cover click short-circuits to openStackFor BEFORE any select branch", () => {
    // the guard is the first line of the click handler -- no shift/ctrl/select path
    // can run for a stack, and it never reaches openLightbox.
    assert.ok(grid.includes("if (stack) { openStackFor(it); return; }"));
    const click = grid.indexOf("if (stack) { openStackFor(it); return; }");
    assert.ok(click < grid.indexOf("if (selectMode) { togglePick(i); return; }"));
  });
  test("shift-range, marquee hit-test, and marquee commit all skip stacks", () => {
    assert.ok(grid.includes("if (it && !stackKind(it) && !selectedRef.current.has(it.media_id)) toggleSelected(it.media_id);"));
    assert.ok(grid.includes("if (it && !stackKind(it)) hits.add(it.media_id);"));
    assert.ok(grid.includes("if (stackKind(it)) return;"));
  });
  test("a stack renders NO checkbox: the mgg-check button lives only in the non-stack branch", () => {
    // the badge branch (stack) vs the mgg-top branch (not stack) are the two arms of
    // one ternary; the checkbox is inside the second arm, after the badge branch.
    assert.ok(grid.indexOf('className={"mgg-" + stack + "-badge"}') < grid.indexOf('className="mgg-check"'));
    // exactly one mgg-check render (the singleton one), not one per arm
    assert.equal((grid.match(/className="mgg-check"/g) || []).length, 1);
  });
});

describe("(f) a plain singleton is unchanged (Grid.jsx)", () => {
  test("no stack markup for a singleton, and the plain click still opens the lightbox", () => {
    // stackKind returns null for a unit with neither key, so .mgg-stack / the deck /
    // the badge never render, and the click falls through to the lightbox exactly as
    // before -- the singleton branch is byte-for-byte today.
    assert.ok(grid.includes("openLightbox(origIndexByMid.get(it.media_id));"));
    // the reveal-gated top row (checkbox + source pill) is still the non-stack arm
    assert.ok(grid.includes('<span className="mgg-top">'));
    assert.ok(grid.includes('className={"mgg-pill" + pillClass}'));
  });
});

describe("grid.css: the stack deck + badges, contained inside the clipped card", () => {
  test("the card clips (overflow hidden) so the deck can never spill into a neighbour", () => {
    const i = css.indexOf(".mgg-card {");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /overflow: hidden;/);
  });
  test("the cover insets within the card; the two layers are absolute, behind it", () => {
    // .mgg-art is a REPLACED <img>: the inset alone doesn't size it (left+right+width
    // over-constrains, the browser drops `right` and paints full-width, 9px clipped off
    // the bottom). The width/height calc is what actually frees the top-right sliver --
    // pin it so a regression to the bare `inset` (or to width:auto -> intrinsic) fails here.
    assert.match(css, /\.mgg-card\.mgg-stack \.mgg-art \{[^}]*inset: 9px 9px 0 0; width: calc\(100% - 9px\); height: calc\(100% - 9px\);[^}]*z-index: 1;/);
    const i = css.indexOf(".mgg-stack-layer {");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /position: absolute; z-index: 0;/);
    assert.match(css, /\.mgg-stack-layer\.back \{/);
    assert.match(css, /\.mgg-stack-layer\.mid \{/);
  });
  test("the badges sit top-left, mono, above the deck (z-index 3)", () => {
    const i = css.indexOf(".mgg-series-badge, .mgg-batch-badge {");
    assert.ok(i > 0, ".mgg-series-badge, .mgg-batch-badge rule present");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /position: absolute; top: 7px; left: 7px; z-index: 3;/);
    assert.match(rule, /font-family: ui-monospace, Menlo, Consolas, monospace;/);
    assert.match(css, /\.mgg-batch-badge \{ border-color:/);
  });
});
