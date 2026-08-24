import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The card placard (#30): the Accession Stamp (direction A) + Sibling Strip (direction E)
// from the owner's locked "Placard identity -- five directions" artifact, replacing the
// word-salad filename "title". Source guards, short and literal, like mg-dock-history's:
// the filename line is gone for good, the title slot is gated on a REAL title only, the
// siblings fetch is one batched POST per page (never per card), and the strip's self ring
// is the artifact's.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");

describe("Accession Stamp replaces the filename line (Grid.jsx)", () => {
  const grid = src("gallery/src/components/Grid.jsx");
  const cap = grid.slice(grid.indexOf('<figcaption className="mgg-cap">'), grid.indexOf("</figcaption>"));

  test("(a) .mgg-file is no longer rendered -- no filename, no truncated shortName", () => {
    assert.doesNotMatch(grid, /mgg-file/);
    assert.doesNotMatch(grid, /shortName/);
    assert.doesNotMatch(cap, /it\.filename/);
  });
  test("(b) the title renders ONLY under a truthiness check -- never filename-derived", () => {
    // #34 direction B: the gated variable is now `stampTitle` (the series title when
    // this is a series stack, else it.title exactly as before) -- still ONE render,
    // still never filename-derived. See stackKind/stampTitle in Grid.jsx.
    assert.match(cap, /\{stampTitle \? <span className="mgg-title">\{stampTitle\}<\/span> : null\}/);
    // exactly one .mgg-title render, and it is the gated one
    assert.equal((cap.match(/mgg-title/g) || []).length, 1);
  });
  test("the stamp: local day · time lead line, then the model with the not-grouped flag", () => {
    assert.match(cap, /<span className="mgg-stamp lead">\{localDayTime\(it\.created_at\) \|\| it\.date \|\| ""\}<\/span>/);
    // #34: the model stamp now appends the dial-in suffix (· v3 · 2/4) via the shared helper.
    assert.match(cap, /<span className="mgg-stamp">\{\(it\.model \|\| "no model"\) \+ \(it\.task_id \? "" : " · not grouped"\) \+ \(stack \? "" : seriesSuffix\(it, seriesByTask\)\)\}<\/span>/);
    assert.match(grid, /import \{ localDay, localDayTime \} from "\.\.\/gen\/dates\.js";/);
    // the stars/Open/Details row is untouched, below the stamp and strip
    assert.ok(cap.indexOf('className="mgg-stamp"') < cap.indexOf("{strip}"));
    assert.ok(cap.indexOf("{strip}") < cap.indexOf('<span className="mgg-caprow">'));
    assert.match(cap, /<Stars mediaId=\{it\.media_id\} rating=\{it\.rating\} onRate=\{onRate\} \/>/);
  });
});

describe("Sibling Strip: one batched fetch per page, never per card", () => {
  const grid = src("gallery/src/components/Grid.jsx");
  const api = src("gallery/src/api.js");

  test("(c) fetchSiblings is called ONCE, inside an items-keyed effect, with a batched array", () => {
    const calls = grid.match(/fetchSiblings\(/g) || [];
    assert.equal(calls.length, 1, "exactly one call site");
    const i = grid.indexOf("fetchSiblings(taskIds)");
    assert.ok(i > 0, "called with the page's collected taskIds array");
    // the call lives in a useEffect keyed on [items], not in the per-card renderer
    const effectStart = grid.lastIndexOf("useEffect(() => {", i);
    const effectEnd = grid.indexOf("}, [items]);", i);
    assert.ok(effectStart > 0 && effectEnd > i, "inside useEffect(..., [items])");
    const renderCard = grid.indexOf("const renderCard = (cell, i) => {");
    assert.ok(renderCard > effectEnd, "the per-card map comes AFTER the effect; no fetch inside it");
    assert.doesNotMatch(grid.slice(renderCard), /fetchSiblings|fetch\(/);
    // stale-response guard, the prefillSeq pattern
    const effect = grid.slice(effectStart, effectEnd);
    assert.match(effect, /const my = \+\+siblingsSeq\.current;/);
    assert.match(effect, /if \(siblingsSeq\.current !== my\) return;/);
    assert.match(grid, /import \{ fetchSiblings, fetchSeriesBatch \} from "\.\.\/api\.js";/);
  });
  test("api.fetchSiblings posts {task_ids} to /api/siblings through apiPost, fail-soft", () => {
    // Re-anchored 2026-08-23: postJSON was one of four diverging copies and became api.js's
    // apiPost. Same call, same fail-soft answer, one name.
    assert.match(api, /export async function fetchSiblings\(taskIds\) \{\s*const d = await apiPost\("\/api\/siblings", \{ task_ids: taskIds \}\);/);
    assert.match(api, /\{ by_task: \{\} \}/);
  });
  test("the strip renders only for a task with >= 2 members; four shown + '+N'", () => {
    // >= 2 members AND the size gate (owner call (a), 2026-08-22): below STRIP_MIN_THUMB the
    // fixed-height grid cell can't hold the slab + strip, so the strip steps aside.
    assert.match(grid, /if \(Array\.isArray\(sibs\) && sibs\.length >= 2 && \(thumb \|\| 210\) >= STRIP_MIN_THUMB\) \{/);
    assert.match(grid, /const STRIP_MIN_THUMB = 190;/);
    assert.match(grid, /const shown = sibs\.slice\(0, 4\);/);
    assert.match(grid, /\{sibs\.length > 4 \? <span className="more">\+\{sibs\.length - 4\}<\/span> : null\}/);
    assert.match(grid, /className=\{s\.media_id === it\.media_id \? "self" : undefined\}/);
  });
});

describe("grid.css: the artifact's stamp + strip rules; the filename rules are gone", () => {
  const css = src("gallery/src/styles/grid.css");

  test("(d) .mgg-strip img.self exists with opacity: 1 and the lavender ring", () => {
    const i = css.indexOf(".mgg-strip img.self {");
    assert.ok(i > 0, ".mgg-strip img.self rule present");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /opacity: 1;/);
    assert.match(rule, /border-color: var\(--lavender, var\(--accent\)\);/);
    assert.match(rule, /box-shadow: 0 0 0 1px color-mix\(in srgb, var\(--lavender, var\(--accent\)\) 70%, transparent\);/);
  });
  test("strip geometry verbatim: flex gap 4 / margin-top 9 / wrap; 30×30 cover, radius 3, .5 dimmed", () => {
    assert.match(css, /\.mgg-strip \{ display: flex; gap: 4px; margin-top: 9px; flex-wrap: wrap; \}/);
    const i = css.indexOf(".mgg-strip img {");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /width: 30px; height: 30px; object-fit: cover; border-radius: 3px;/);
    assert.match(rule, /opacity: \.5; display: block;/);
    assert.match(css, /\.mgg-strip \.more \{[^}]*font-size: 9\.5px;[^}]*align-self: center; padding-left: 3px; letter-spacing: \.06em;/);
  });
  test("stamp verbatim (mono 10.5 / .13em / uppercase / 0 0 4px); title italic serif at the 13px adaptation", () => {
    const i = css.indexOf(".mgg-stamp {");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 10\.5px;/);
    assert.match(rule, /letter-spacing: \.13em; text-transform: uppercase;/);
    assert.match(rule, /margin: 0 0 4px; overflow-wrap: anywhere;/);
    assert.match(css, /\.mgg-stamp\.lead \{ color: rgba\(255, 255, 255, \.6\); \}/);
    const t = css.indexOf(".mgg-title {");
    const title = css.slice(t, css.indexOf("}", t));
    assert.match(title, /font-family: Georgia, 'Times New Roman', serif; font-style: italic; font-weight: 400;/);
    assert.match(title, /font-size: 13px; line-height: 1\.2; margin: 0 0 7px; color: #d6d2e2;/);
    assert.match(title, /overflow-wrap: anywhere; text-wrap: balance;/);
  });
  test("the dead rules went with the filename line", () => {
    assert.doesNotMatch(css, /^\.mgg-file \{/m);
    assert.doesNotMatch(css, /^\.mgg-model \{/m);
    assert.doesNotMatch(css, /^\.mgg-date \{/m);
  });
});
