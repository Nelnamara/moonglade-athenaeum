import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// SESSION strip in the desktop Image Details (issue #34, direction C): the dial-in
// series this image belongs to, task-by-task, drawn under LINEAGE as its sibling.
// Source guards, short and literal, like placard.test.js's: the panel is gated on a
// REAL series (never an empty rail), the strip inner-scrolls on its own, the lit step
// is the one whose task is THIS image's, consecutive rerolls collapse, and the fetch
// is one stale-guarded effect -- never per-render.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");

describe("SESSION panel gating + placement (DetailsView.jsx)", () => {
  const dv = src("gallery/src/components/DetailsView.jsx");

  test("(a) the panel renders ONLY under a series truthiness gate -- no empty panel", () => {
    // the whole card is gated on series && series.steps && series.steps.length
    assert.match(dv, /\{series && series\.steps && series\.steps\.length \? \(/);
    // ...and the ternary closes to null (the LINEAGE/SIMILAR "never an empty rail" idiom)
    const gate = dv.indexOf("{series && series.steps && series.steps.length ? (");
    assert.match(dv.slice(gate, gate + 2200), /\) : null\}/);
    // exactly one SESSION panel
    assert.equal((dv.match(/className="p-session"/g) || []).length, 1);
    // and it never renders without the gate: no bare <div className="p-session"> outside it
    assert.ok(dv.indexOf('className="p-session"') > gate);
  });

  test("placement: the SESSION card sits AFTER the LINEAGE card and BEFORE SIMILAR", () => {
    const lineage = dv.indexOf('className="p-lineage"');
    const session = dv.indexOf('className="p-session"');
    const similar = dv.indexOf('className="p-similar"');
    assert.ok(lineage > 0 && session > lineage, "SESSION comes after LINEAGE");
    assert.ok(similar > session, "SESSION comes before SIMILAR");
  });

  test("header: the SESSION kicker + the series title + a muted N tasks / M images count", () => {
    assert.match(dv, /<span className="k">⟲ SESSION<\/span>/);
    assert.match(dv, /\{series\.title \? <span className="t" title=\{series\.title\}>\{series\.title\}<\/span> : null\}/);
    assert.match(dv, /<span className="s">\{series\.count_tasks\} tasks · \{series\.count_images\} images<\/span>/);
  });
});

describe("SESSION strip: own scroller, lit step, reroll collapse (DetailsView.jsx + styles.css)", () => {
  const dv = src("gallery/src/components/DetailsView.jsx");
  const css = src("gallery/src/styles.css");

  test("(b) the strip has its OWN overflow-x container (inner-scroll, like LINEAGE/SIMILAR)", () => {
    const i = css.indexOf(".p-session-strip {");
    assert.ok(i > 0, ".p-session-strip rule present");
    assert.match(css.slice(i, css.indexOf("}", i)), /overflow-x: auto;/);
    // the card chrome matches LINEAGE's exactly (padding 13px 15px, radius 13, the border/bg)
    const c = css.indexOf(".p-session {");
    const card = css.slice(c, css.indexOf("}", c));
    assert.match(card, /padding: 13px 15px; border-radius: 13px;/);
    assert.match(card, /border: 1px solid rgba\(255, 255, 255, \.08\); background: rgba\(9, 7, 22, \.6\);/);
  });

  test("(c) the lit step keys off g.step.task_id === row.task_id, with the lavender ring", () => {
    assert.match(dv, /g\.step\.task_id === row\.task_id \? " this" : ""/);
    const i = css.indexOf(".p-ses-step.this .thumb {");
    assert.ok(i > 0, ".p-ses-step.this .thumb rule present");
    assert.match(css.slice(i, css.indexOf("}", i)), /border-color: var\(--lavender, var\(--accent\)\);/);
  });

  test("(d) reroll-run collapse: a helper groups consecutive rerolls into one chip", () => {
    // a named helper exists...
    assert.match(dv, /function groupSeriesSteps\(steps, currentTaskId\)/);
    // ...it walks a run of consecutive rerolls...
    assert.match(dv, /while \(i < list\.length && list\[i\]\.reroll && !pinned\(i\)\) \{/);
    // ...collapses 2+ into a "rerolls" node, keeps a lone one as a step...
    assert.match(dv, /if \(run\.length >= 2\) \{/);
    assert.match(dv, /kind: "rerolls"/);
    // ...and NEVER collapses the current step OR the last step
    assert.match(dv, /const pinned = \(i\) => i === lastIdx \|\| list\[i\]\.task_id === currentTaskId;/);
    // the collapsed run renders as a "N rerolls" chip
    assert.match(dv, /className="p-ses-rerolls"/);
    assert.match(dv, /\{g\.count\} rerolls/);
    // and the helper actually builds the strip
    assert.match(dv, /groupSeriesSteps\(series\.steps, row\.task_id\)/);
  });

  test("each step navigates to that task's first image; arrows between steps", () => {
    assert.match(dv, /onClick=\{\(\) => onNavigate\(g\.step\.first_media_id\)\}/);
    assert.match(dv, /src=\{"\/thumbs\/" \+ encodeURIComponent\(g\.step\.first_media_id\) \+ "\.jpg"\}/);
    assert.match(dv, /<span className="p-lin-arrow">→<\/span>/);
  });
});

describe("fetchSeries: one stale-guarded effect, never per-render (DetailsView.jsx + api.js)", () => {
  const dv = src("gallery/src/components/DetailsView.jsx");
  const api = src("gallery/src/api.js");

  test("(e) fetchSeries is imported and called ONCE from an effect, stale-guarded on a seq ref", () => {
    assert.match(dv, /import \{ rebuildPoster, fetchSeries \} from "\.\.\/api\.js";/);
    // exactly one call site, and it is inside a useEffect (not the render body)
    assert.equal((dv.match(/fetchSeries\(/g) || []).length, 1, "exactly one fetchSeries call site");
    const i = dv.indexOf("fetchSeries(seriesTaskId)");
    assert.ok(i > 0, "called with the derived task id");
    const effectStart = dv.lastIndexOf("useEffect(() => {", i);
    const effectEnd = dv.indexOf("}, [seriesTaskId]);", i);
    assert.ok(effectStart > 0 && effectEnd > i, "inside useEffect(..., [seriesTaskId])");
    // the seq guard, the Similar path's pattern
    const effect = dv.slice(effectStart, effectEnd);
    assert.match(effect, /const mine = \+\+seriesSeq\.current;/);
    assert.match(effect, /if \(mine === seriesSeq\.current\) setSeries\(d\);/);
    assert.match(dv, /const seriesSeq = useRef\(0\);/);
    // the effect keys on the TASK id, so sibling-to-sibling navigation costs no refetch
    assert.match(dv, /const seriesTaskId = row \? row\.task_id : "";/);
  });

  test("api.fetchSeries: membership POST then the series GET, both fail-soft to null", () => {
    assert.match(api, /export async function fetchSeries\(taskId\) \{/);
    // membership: POST the one task_id to /api/series via postJSON
    assert.match(api, /postJSON\("\/api\/series", \{ task_ids: \[taskId\] \}\)/);
    // only a task that IS in a multi-task series continues (singletons -> null)
    assert.match(api, /if \(!hit \|\| !hit\.sid\) return null;/);
    // the series itself: GET /api/series/<sid>, null on any miss
    assert.match(api, /"\/api\/series\/" \+ encodeURIComponent\(hit\.sid\)/);
    assert.match(api, /Array\.isArray\(d\.steps\)/);
  });
});
