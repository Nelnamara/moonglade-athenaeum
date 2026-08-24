import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

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
});

describe("(c) opening a stack NAVIGATES: series -> series filter, batch -> View-batch", () => {
  test("Grid routes a stack open to onOpenSeries(sid) / onOpenBatch(task_id)", () => {
    assert.ok(grid.includes("if (kind === \"series\" && onOpenSeries) onOpenSeries(it.series.sid);"));
    assert.ok(grid.includes("else if (kind === \"batch\" && onOpenBatch) onOpenBatch(it.batch.task_id);"));
  });
  test("App mirrors filterByBatch as filterBySeries (sets the series drill-down) and wires both", () => {
    // filterBySeries is the mirror: it sets adv.series (the ?series filter)
    assert.ok(app.includes("const filterBySeries = (series) => {"));
    assert.ok(app.includes("setAdv((old) => ({ ...old, series, batch: \"\" }));"));
    // the batch open is the EXISTING path, reused exactly
    assert.ok(app.includes("const filterByBatch = (batch) => {"));
    // both handed to the grid
    assert.ok(app.includes("onOpenSeries={filterBySeries}"));
    assert.ok(app.includes("onOpenBatch={filterByBatch}"));
  });
  test("the tray toggle flips group and lights when on (next to the layout picker)", () => {
    assert.ok(tray.includes('onClick={() => setGroup(group !== "series")}'));
    assert.ok(tray.includes('active={group === "series"}'));
    assert.ok(tray.includes('label="Stack sessions"'));
    // it sits right after the LayoutPicker in the tray
    assert.ok(tray.indexOf("<LayoutPicker") < tray.indexOf('label="Stack sessions"'));
  });
});

describe("(d) hero never features a stack (Grid.jsx)", () => {
  test("the hero feature-pick skips a stack, like it already skips a video", () => {
    assert.ok(grid.includes(
      "const hero = (i % HERO_EVERY === 0) && !it.is_video && !stackKind(it);"));
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
    assert.match(css, /\.mgg-card\.mgg-stack \.mgg-art \{[^}]*inset: 9px 9px 0 0;[^}]*z-index: 1;/);
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
