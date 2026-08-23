import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Image Details' LAYOUT (#31), rebuilt 2026-08-23 to the pixel source,
// design_handoff/design_handoff_moonglade_suite/Image Details.dc.html, after the owner's
// verdict on the previous build: "Does not follow the design's layout. There should be NO
// page scrolling. The image stays static and the details pane scrolls if needed."
//
// Source guards, short and literal, like details-actions.test.js: the shapes that make
// that verdict impossible to re-break -- no wide-image stacking branch, two equal columns
// always, the DC's frame formula, one scroller (the record) inside a shell that never
// scrolls, the DC's eleven ledger rows in the DC's order, and the file actions under the
// hero in the picture column. Pixel measurements against the built app.css are the live
// check's job (the report that shipped this), not this file's.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");
const details = src("gallery/src/components/DetailsView.jsx");
const css = src("gallery/src/styles.css");

// one CSS rule's body by its exact selector at line start (the first such rule)
function rule(selector) {
  const i = css.indexOf("\n" + selector + " {");
  assert.ok(i >= 0, "rule exists: " + selector);
  return css.slice(i, css.indexOf("}", i));
}

describe("(a) the wide-image stacking branch is gone -- no aspect-ratio door into a one-column layout", () => {
  test("no `placard-wide` anywhere in styles.css or DetailsView.jsx", () => {
    assert.doesNotMatch(css, /placard-wide/);
    assert.doesNotMatch(details, /placard-wide/);
  });
  test("no 40vh cap outside the narrow-window fallback, and DetailsView no longer takes the hook's `wide`", () => {
    const shell = css.indexOf(".detail-wrap {");
    const narrow = css.indexOf("@media (max-width: 860px)", shell);
    assert.ok(shell > 0 && narrow > shell);
    assert.doesNotMatch(css.slice(shell, narrow), /40vh/);
    // the hook still derives `wide` for the mobile record; the desktop view must not
    // destructure it or branch on it
    assert.doesNotMatch(details, /\bwide[,}]|\(wide \?/);
  });
});

describe("(b) the body grid: two equal columns, always (DC:345-346 bodyGridStyle)", () => {
  test(".placard is minmax(0, 1fr) minmax(0, 1fr), flex-filling, min-height 0, the DC's gap + padding", () => {
    const r = rule(".placard");
    assert.match(r, /grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\);/);
    assert.match(r, /flex: 1 1 auto; min-height: 0; display: grid; gap: 34px; padding: 26px 26px 34px;/);
    assert.match(r, /align-items: stretch;/);
  });
  test("Focus collapses the record's column to 0px and fades the record (DC:346-348), never unmounts it", () => {
    assert.match(css, /\.focus-mode \.placard \{ grid-template-columns: minmax\(0, 1fr\) 0px; \}/);
    assert.match(rule(".focus-mode .placard-record"), /opacity: 0;/);
    assert.match(rule(".placard"), /transition: grid-template-columns \.45s/);
    assert.match(rule(".placard-record"), /transition: opacity \.3s ease/);
    // the record is always rendered -- no `{!focusMode && (<aside` gate any more
    assert.doesNotMatch(details, /\{!focusMode && \(\s*<aside/);
    assert.match(details, /<aside className="placard-record" ref=\{recordRef\}>/);
  });
});

describe("(c) the frame: the DC's formula (DC:357-358 frameStyle)", () => {
  test(".placard-frame carries width: min(100%, calc(72vh * AR)) and an aspect-ratio, centred, 16px radius", () => {
    const r = rule(".placard-frame");
    assert.match(r, /width: min\(100%, calc\(72vh \* var\(--ar\)\)\); height: auto;/);
    assert.match(r, /align-self: center; aspect-ratio: var\(--ar\);/);
    assert.match(r, /border-radius: 16px; overflow: hidden;/);
    assert.match(r, /box-shadow: 0 40px 110px rgba\(0, 0, 0, \.72\), 0 0 90px rgba\(100, 58, 172, \.2\);/);
  });
  test("the media fills the frame absolutely with object-fit: contain (DC:52)", () => {
    assert.match(css, /\.placard-frame img, \.placard-frame video \{ position: absolute; inset: 0; width: 100%; height: 100%;\r?\n\s*object-fit: contain;/);
  });
  test("DetailsView sets --ar as 'W / H' from the row, and a row with no size gets .no-dims (media sizes the frame, 72vh cap)", () => {
    assert.match(details, /const W = Number\(row\.width\) \|\| 0, H = Number\(row\.height\) \|\| 0;/);
    assert.match(details, /if \(hasDims\) frameStyle\["--ar"\] = W \+ " \/ " \+ H;/);
    assert.match(details, /className=\{"placard-frame" \+ \(hasDims \? "" : " no-dims"\)\} style=\{frameStyle\}/);
    assert.match(rule(".placard-frame.no-dims"), /width: auto; max-width: 100%; max-height: 72vh; aspect-ratio: auto;/);
    assert.match(css, /\.placard-frame\.no-dims img, \.placard-frame\.no-dims video \{ position: static; width: auto; height: auto;\r?\n\s*max-width: 100%; max-height: 72vh; \}/);
  });
  test("the narrow-window fallback caps the frame at 40vh so it cannot overlap the stacked record", () => {
    const narrow = css.slice(css.indexOf("@media (max-width: 860px)", css.indexOf(".detail-wrap {")));
    const block = narrow.slice(0, narrow.indexOf("\n}"));
    assert.match(block, /\.placard \{ grid-template-columns: 1fr; overflow-y: auto;/);
    assert.match(block, /\.placard-frame \{ width: min\(100%, calc\(40vh \* var\(--ar\)\)\); \}/);
    assert.match(block, /\.placard-frame\.no-dims, \.placard-frame\.no-dims img, \.placard-frame\.no-dims video \{ max-height: 40vh; \}/);
  });
});

describe("(d) one scroller: the record; the shell never scrolls (DC:36, :347)", () => {
  test(".detail-wrap is fixed inset-0, 100vh, overflow hidden, a flex column", () => {
    const r = rule(".detail-wrap");
    assert.match(r, /position: fixed; inset: 0; z-index: 40; height: 100vh; overflow: hidden;/);
    assert.match(r, /display: flex; flex-direction: column;/);
  });
  test(".detail-nav is flex: none; .placard-record is the flex column with overflow-y: auto / overflow-x: hidden", () => {
    assert.match(rule(".detail-nav"), /flex: none;/);
    const r = rule(".placard-record");
    assert.match(r, /display: flex; flex-direction: column; gap: 16px; min-width: 0; min-height: 0;/);
    assert.match(r, /overflow-y: auto; overflow-x: hidden;/);
  });
  test("the picture column is the DC's centred flex column (DC:50), and nothing in it scrolls", () => {
    const r = rule(".placard-picture");
    assert.match(r, /min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 12px;/);
    assert.match(r, /justify-content: center;/);
    assert.doesNotMatch(r, /overflow/);
  });
  test("the prompt editor, the suggestions and the Upscale float never sit in the shell's flow outside the record", () => {
    const aside = details.slice(details.indexOf('<aside className="placard-record"'), details.indexOf("</aside>"));
    assert.match(aside, /<div id="prompt-editor">/);
    assert.match(aside, /<div id="suggest-box">/);
    // the Upscale panel is the fixed float (DC:143-146), not the in-flow `inline` mount
    assert.match(details, /<UpscalePanel ref=\{upEl\} \/>/);
    assert.doesNotMatch(details, /<UpscalePanel[^>]*inline/);
  });
});

describe("(e) the ledger: exactly the DC's eleven rows, in the DC's order (DC:375-387)", () => {
  const LABELS = ["Full prompt", "Natural", "Negative", "Model", "LoRAs", "Seed",
    "Steps · CFG", "Sampler", "Task ID", "Media ID", "Filename"];

  test("the eleven labels appear in order inside the first .p-ledger, nothing else in it", () => {
    const start = details.indexOf('<div className="p-ledger">');
    const ledger = details.slice(start, details.indexOf("</div>", start));
    const found = [...ledger.matchAll(/<LedgerRow label="([^"]+)"/g)].map((m) => m[1]);
    assert.deepEqual(found, LABELS);
  });
  test("the DC's faces: mono on Seed/Task ID/Media ID/Filename, dim on Natural/Negative/Task ID/Media ID/Filename, warm on Model; copy on the four ids", () => {
    assert.match(details, /<LedgerRow label="Natural" value=\{row\.natural_prompt\} dim /);
    assert.match(details, /<LedgerRow label="Negative" value=\{row\.negative_prompt\} dim /);
    assert.match(details, /<LedgerRow label="Model" value=\{row\.model_name \|\| row\.model_id\} warm /);
    assert.match(details, /<LedgerRow label="Seed" value=\{row\.seed\} mono copyKey="seed" /);
    assert.match(details, /<LedgerRow label="Task ID" value=\{row\.task_id\} mono dim copyKey="task" /);
    assert.match(details, /<LedgerRow label="Media ID" value=\{row\.media_id\} mono dim copyKey="mid" /);
    assert.match(details, /<LedgerRow label="Filename" value=\{row\.filename\} mono dim copyKey="fname" /);
    // an empty value renders the DC's dash, never an absent row
    assert.match(details, /\{has \? text : "—"\}/);
  });
  test("the row's CSS is the DC's (DC:93, :331-338): 118px right-aligned label, wrapping 11.5px value, the three faces", () => {
    assert.match(rule(".p-ledger"), /display: flex; flex-direction: column; gap: 3px;/);
    assert.match(rule(".p-row"), /display: flex; gap: 12px; align-items: flex-start; padding: 5px 9px; border-radius: 8px;/);
    const k = rule(".p-row-k");
    assert.match(k, /flex: none; width: 118px; text-align: right; font-size: 10px; font-weight: 700;/);
    assert.match(k, /letter-spacing: \.1em; text-transform: uppercase; color: var\(--overlay0\); padding-top: 2px;/);
    const v = rule(".p-row-v");
    assert.match(v, /flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; word-break: break-word;/);
    assert.match(v, /font-size: 11\.5px; line-height: 1\.65; color: rgba\(226, 222, 238, \.86\);/);
    assert.match(css, /\.p-row-v\.mono \{ font-family: ui-monospace, Menlo, monospace; \}/);
    assert.match(css, /\.p-row-v\.dim \{ color: rgba\(214, 210, 226, \.45\); \}/);
    assert.match(css, /\.p-row-v\.warm \{ color: var\(--lavender, var\(--accent\)\); \}/);
    assert.match(css, /\.p-row\.copied \{ background: rgba\(79, 201, 154, \.1\); \}/);
  });
  test("the app's extra fields (#18) fold under a collapsed 'More details' disclosure below the ledger, remembered in mg_details_more", () => {
    assert.match(details, /const MORE_KEY = "mg_details_more";/);
    assert.match(details, /<details className="p-more p-fact" open=\{moreOpen\}/);
    assert.match(details, /localStorage\.setItem\(MORE_KEY, moreOpen \? "1" : ""\)/);
    const ledger = details.indexOf('<div className="p-ledger">');
    const more = details.indexOf('<details className="p-more');
    const recordActions = details.indexOf('className="p-actions p-actions-record"');
    assert.ok(ledger > 0 && more > ledger && recordActions > more, "ledger, then More details, then the record actions");
    for (const f of ["inference_profile", "quality_tag", "prompt_helper", "control_nets", "priority",
      "render_seconds", "backend", "started_at", "ended_at", "updated_at", "retry_count", "moderation",
      "video_mode", "video_model", "clip_skip", "liked_count", "nsfw"]) {
      assert.ok(details.includes(f), "the " + f + " field is still surfaced");
    }
  });
});

describe("(f) the picture column: frame, file actions, stars row -- before the record opens (DC:50-71)", () => {
  test("the file-actions row renders inside .placard-picture, under the frame, before the record column", () => {
    const picture = details.indexOf('<div className="placard-picture">');
    const frame = details.indexOf('className={"placard-frame"');
    const actions = details.indexOf('className="p-actions p-actions-primary"');
    const stars = details.indexOf('className="p-stars-row"');
    const record = details.indexOf('<aside className="placard-record"');
    assert.ok(picture >= 0 && frame > picture && actions > frame && stars > actions && record > stars);
  });
  test("the stars row is the DC's (DC:61-70): 15px stars at gap 3, 'N / 5' or 'unrated', dims · the LOCAL day pushed right", () => {
    assert.match(rule(".p-stars-row"), /display: flex; align-items: center; gap: 9px; padding-top: 2px;/);
    assert.match(rule(".p-stars-row .stars .st"), /font-size: 15px;/);
    assert.match(css, /\.p-stars-row \.stars \.st:hover \{ transform: scale\(1\.18\); \}/);
    assert.match(css, /\.p-stars-row \.rating-label \{ font-size: 10\.5px; color: rgba\(214, 210, 226, \.45\); \}/);
    assert.match(css, /\.p-stamp \{ font-size: 10px; color: rgba\(214, 210, 226, \.3\);/);
    assert.match(details, /\{row\.rating \? row\.rating \+ " \/ 5" : "unrated"\}/);
    assert.match(details, /const day = localDay\(row\.created_at\);/);
    assert.match(details, /<span className="p-stamp">\{\[dims, day\]\.filter\(Boolean\)\.join\(" · "\)\}<\/span>/);
  });
  test("the top bar is the DC's order (DC:38-46): Back · divider · ⛶ Lightbox · spacer · N of M · Prev · Next, Focus last", () => {
    const nav = details.slice(details.indexOf('<div className="detail-nav">'), details.indexOf('<div className="placard">'));
    const order = ['className="back-link"', 'className="detail-div"', 'className="detail-lb"', '<span className="sp" />',
      'className="detail-index"', "&lsaquo; Prev", "Next &rsaquo;", 'className="focus-btn"'];
    let last = -1;
    for (const o of order) { const i = nav.indexOf(o); assert.ok(i > last, o + " in order"); last = i; }
    assert.match(nav, /onClick=\{\(\) => onOpenLightbox\(row\.media_id\)\}>&#9974; Lightbox<\/button>/);
    assert.match(css, /\.detail-div \{ flex: none; width: 1px; height: 12px; background: rgba\(255, 255, 255, \.14\); \}/);
    assert.match(css, /\.detail-index \{ font-size: 11px; color: rgba\(214, 210, 226, \.45\); font-variant-numeric: tabular-nums; \}/);
    assert.match(rule(".nav-arrow, .nav-disabled, .focus-btn"), /font-size: 11px; font-weight: 600; padding: 6px 12px;\r?\n\s*border-radius: 8px;/);
  });
});
