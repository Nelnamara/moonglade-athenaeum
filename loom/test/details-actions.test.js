import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Image Details' actions (#31, "Where the Refit Broke" #5): the refit shipped them as
// one flat strip of equal chips; the locked design (design_handoff/.../Image
// Details.dc.html:318-324 btn(), :389-403 fileActions + recordActions) has ten actions
// in TWO groups in TWO places, Download promoted to the metal button. Source guards,
// short and literal, like placard.test.js: the two designed groups carry exactly the
// designed labels in the designed order, the faces are right, and the app's own extra
// actions -- the ones the DC never drew -- kept every one of their handlers in a
// quieter third row, with the irreversible one last.
//
// The two PLACES, per the 2026-08-23 rebuild to the DC (details-layout.test.js has the
// layout itself): fileActions sit UNDER THE HERO in the picture column (DC:56-60), and
// recordActions sit in the record directly under the ledger, BEFORE lineage (DC:102-108).

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");
const details = src("gallery/src/components/DetailsView.jsx");

// the text of one <div className="p-actions p-actions-X"> ... </div> group: from its
// opening tag to the first </div> back at the container's OWN indent (every chip inside
// sits deeper), so the slice is exactly that group and nothing after it.
function group(name) {
  const open = '<div className="p-actions p-actions-' + name + '">';
  const i = details.indexOf(open);
  assert.ok(i >= 0, "the " + name + " group exists: " + open);
  const indent = i - (details.lastIndexOf("\n", i) + 1);
  const rest = details.slice(i + open.length);
  const close = rest.search(new RegExp("\\r?\\n {" + indent + "}</div>"));
  assert.ok(close >= 0, "the " + name + " group closes");
  return rest.slice(0, close);
}

// the labels rendered by a group, in source order. A label is the text right before a
// closing </a> or </button> (or the is-off </span>); a ternary label like
// {copied === "prompt" ? "Copied!" : "⧉ Copy prompt"} counts by its resting text.
function labels(txt) {
  const out = [];
  const re = /(?:>|: ")([^<>{}"]+?)"?\}?<\/(?:a|button|span)>/g;
  let m;
  while ((m = re.exec(txt))) out.push(m[1].trim());
  return out;
}

describe("the primary group: the DC's fileActions, under the hero in the picture column", () => {
  const g = group("primary");

  test("(a) exactly the five designed labels, in the designed order", () => {
    assert.deepEqual(labels(g).filter((l) => l !== "☁ Published"), [
      "⬇ Download", "☁ Publish", "⧉ Copy prompt", "⇱ Upscale", "Delete locally",
    ]);
  });
  test("it sits in the PICTURE column, under the frame and before the stars row -- never in the record", () => {
    const picture = details.indexOf('<div className="placard-picture">');
    const frame = details.indexOf('className={"placard-frame"');
    const primary = details.indexOf('className="p-actions p-actions-primary"');
    const stars = details.indexOf('className="p-stars-row"');
    const record = details.indexOf('<aside className="placard-record"');
    assert.ok(picture >= 0 && frame > picture, "the picture column opens, then the frame");
    assert.ok(primary > frame, "primary comes after the frame");
    assert.ok(stars > primary, "primary comes before the stars row");
    assert.ok(record > stars, "all of it before the record column opens");
  });
  test("(c) Download carries the shared metal face; Delete locally is the danger chip", () => {
    assert.match(g, /<a className="btn mgx-metal"[\s\S]*?>⬇ Download<\/a>/);
    assert.match(g, /<button className="btn btn-danger" disabled=\{busy\}[\s\S]*?onClick=\{deleteLocal\}>Delete locally<\/button>/);
    // the metal recipe is shell.css's one class, not a second gradient in styles.css
    const shell = src("gallery/src/styles/shell.css");
    assert.match(shell, /\.mgx-metal \{[\s\S]*?--mm-grad: linear-gradient\(100deg/);
    const css = src("gallery/src/styles.css");
    assert.match(css, /\.p-actions \.btn\.mgx-metal[^{]*\{[^}]*background: var\(--mm-grad\)/);
    assert.doesNotMatch(css, /\.p-actions[^{]*\{[^}]*linear-gradient\(100deg/);
  });
});

describe("the record group: the DC's recordActions, under the ledger, before lineage", () => {
  const g = group("record");

  test("(b) exactly the five designed labels, in the designed order", () => {
    // Suggest prompt's resting label (its busy text "Reading…" is the other branch)
    assert.deepEqual(labels(g).filter((l) => l !== "Reading…"), [
      "✎ Edit prompt", "▶ Send to Video", "Find similar (model)", "View batch", "Suggest prompt",
    ]);
  });
  test("it comes after the ledger and BEFORE lineage (DC:102-108)", () => {
    const ledger = details.indexOf('<div className="p-ledger">');
    const lineage = details.indexOf('className="p-lineage"');
    const record = details.indexOf('className="p-actions p-actions-record"');
    assert.ok(ledger >= 0 && record > ledger, "record actions come after the ledger");
    assert.ok(lineage > record, "record actions come before the lineage card");
  });
  test("Find similar (model) is the DC's 'every image from this model' -- the model filter", () => {
    assert.match(g, /onClick=\{\(\) => onFilterByModel\(row\.model_name\)\}>Find similar \(model\)<\/button>/);
  });
  test("the record handlers are the real ones", () => {
    assert.match(g, /onClick=\{\(\) => setEditingPrompt\(\(v\) => !v\)\}>✎ Edit prompt<\/button>/);
    assert.match(g, /onVideo && onVideo\(svid,[\s\S]*?>▶ Send to Video<\/button>/);
    assert.match(g, /onClick=\{\(\) => onFilterByBatch\(row\.task_id\)\}>View batch<\/button>/);
    assert.match(g, /onClick=\{runSuggest\}>\{suggestBusy \? "Reading…" : "Suggest prompt"\}<\/button>/);
  });
});

describe("the More row: the app's actions the DC never drew, every handler kept", () => {
  const g = group("more");

  test("(d) all nine undesigned actions are still here, with their handlers", () => {
    const kept = [
      ["Open Full Size", /href=\{"\/full\/" \+ encodeURIComponent\(row\.media_id\)\} target="_blank"[^>]*>Open Full Size<\/a>/],
      ["Open on PixAI", /href=\{row\.url\} target="_blank"[^>]*>Open on PixAI<\/a>/],
      ["Print", /onClick=\{\(\) => window\.print\(\)\}>🖨 Print<\/button>/],
      ["4×6 photo", /format=photo"[^>]*>4×6 photo<\/a>/],
      ["Photo strip", /format=strip"[^>]*>Photo strip<\/a>/],
      ["Edit this", /onClick=\{\(\) => \{ onClose\(\); onEdit\(row\.media_id\); \}\}>✧ Edit this<\/button>/],
      ["Remix", /onClick=\{\(\) => \{ onClose\(\); onRemix && onRemix\(row\.media_id\); \}\}>↺ Remix<\/button>/],
      ["Rebuild poster", /const d = await rebuildPoster\(row\.media_id\);[\s\S]*?"🖼 Rebuild poster"\}<\/button>/],
      ["Delete from PixAI", /<button className="btn btn-danger" disabled=\{busy\} onClick=\{deleteCloud\}>Delete from PixAI<\/button>/],
    ];
    for (const [name, re] of kept) assert.match(g, re, name + " kept its handler in the More row");
  });
  test("(e) Delete from PixAI is the last chip of all, still danger-styled", () => {
    const all = labels(g);
    assert.equal(all[all.length - 1], "Delete from PixAI");
    // and the More row is the LAST thing in the record: after the record actions,
    // lineage and the Similar strip, closed by the record's own </aside>
    const more = details.indexOf('className="p-actions p-actions-more"');
    assert.ok(more > details.indexOf('className="p-actions p-actions-record"'));
    assert.ok(more > details.indexOf('className="p-lineage"'));
    assert.ok(more > details.indexOf('className="p-similar"'));
    assert.match(details.slice(more), /<\/div>\r?\n\s*<\/aside>/);
  });
  test("Rebuild poster stays video-only", () => {
    assert.match(g, /\{row\.is_video === "1" \? \(\s*<button className="btn" disabled=\{posterBusy\}/);
  });
});

describe("the strip is gone: three groups, styled as groups, and the reveal still lands on them", () => {
  test("no flat .p-footer remains anywhere in the gallery", () => {
    assert.doesNotMatch(details, /p-footer/);
    assert.doesNotMatch(src("gallery/src/styles.css"), /p-footer/);
  });
  test("the three containers, the DC's chip metrics, the danger outline, the quieter More row", () => {
    const css = src("gallery/src/styles.css");
    assert.match(css, /\.p-actions \{ display: flex; flex-wrap: wrap; gap: 7px; padding-top: 4px;/);
    // only the RECORD's groups start hidden for the reveal; the file actions under the
    // hero are drawn unanimated (DC:56-60) and must never sit at opacity 0
    assert.match(css, /\.placard-record \.p-actions \{ opacity: 0; \}/);
    assert.doesNotMatch(css, /\n\.p-actions \{[^}]*opacity: 0/);
    assert.match(css, /\.p-actions \.btn \{ font-size: 11px; font-weight: 700; white-space: nowrap; padding: 8px 14px;\r?\n\s*border-radius: 9px;/);
    assert.match(css, /\.p-actions \.btn-danger[^{]*\{ border: 1px solid rgba\(243,139,168,\.35\);\r?\n\s*background: rgba\(243,139,168,\.1\); color: var\(--red\);/);
    assert.match(css, /\.p-actions-more \.btn \{ font-size: 10px;/);
    assert.match(css, /\.p-actions-more \.btn:not\(\.mgx-metal\):not\(\.btn-danger\) \{ color: var\(--overlay0\);/);
    // the existing .btn base is untouched
    assert.match(css, /\n\.btn \{ border-radius: 8px; border: 1px solid var\(--surface1\); color: var\(--text\);/);
  });
  test("the reveal's closing beat pops every group in (and reduced-motion/print cover them)", () => {
    assert.match(details, /qa\("\.p-actions"\)\.forEach\(\(g, i\) => play\(g, \[/);
    assert.match(details, /qa\("\.p-kicker, \.p-title, \.p-fact, \.p-tag, \.p-actions"\)/);
    const css = src("gallery/src/styles.css");
    assert.match(css, /header, \.detail-nav, \.p-actions, \.p-stars-row \{ display: none !important; \}/);
    assert.match(css, /\.p-kicker, \.p-title, \.p-fact, \.p-tag, \.p-actions \{ opacity: 1; \}/);
    assert.match(css, /\.placard-record \.p-actions \{ opacity: 1; \}/);
  });
});
