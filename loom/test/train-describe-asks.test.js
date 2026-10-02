import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* Advanced training's "Describe automatically (N images) · price" ASKS ONCE before it spends
   (BUILD-w3-train.md section 5). Owner walk 2026-09-30: on the desktop the press sent the paid
   describe at once (1,500 credits on a draft of 10). The press now opens the Training
   Handoff's ask (3c's gold-priced confirm card: the question, PixAI's quote, the line, a way
   back, "Describe · price"), and only that card's button sends. The phone already asked, in its
   DESCRIBE AUTOMATICALLY sheet; that is held here too. tests/test_render_harness.py walks the
   desktop flow in a real browser against a faked PixAI. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

/** The Descriptions step of the desktop wizard, through the end of its component. */
function descriptions() {
  const s = src("components/train/TrainAdvanced.jsx");
  const at = s.indexOf("function Descriptions(");
  assert.ok(at >= 0, "Descriptions moved? re-point this test, never drop it");
  return s.slice(at, s.indexOf("\nfunction ", at + 1));
}

describe("the desktop describe press asks before it sends", () => {
  const d = descriptions();
  test("the entry button (describeLabel's words and price) only opens the ask", () => {
    assert.match(d, /onClick=\{\(\) => setAsking\(true\)\}>\s*\{describeLabel\(q\)\}<\/button>/);
  });
  test("the paid describe is called once, from the ask card's own priced button, after a way back", () => {
    assert.equal((d.match(/a\.describe\(/g) || []).length, 1, "one send site");
    const card = d.indexOf('<div className="mgtr-capask"');
    const back = d.indexOf('onClick={() => setAsking(false)}>Back</button>', card);
    const send = d.indexOf("await a.describe();", card);
    assert.ok(card >= 0 && back > card && send > back, "card -> Back -> Describe · price");
    assert.ok(d.lastIndexOf("setAsking(true)", send) < card, "the send is inside the ask, not the entry");
    assert.match(d.slice(send - 200, send + 400), /"Describe · " \+ credits\(q\.total_price\)/,
      "the button that sends names the amount it sends");
    assert.match(d.slice(0, card), /a\.enough && !asking \?/, "the card shows only once the owner has pressed");
  });
  test("a new quote closes the ask, so what was confirmed is what the button sends", () => {
    assert.match(d, /const askTotal = q && typeof q\.total_price === "number" \? q\.total_price : null;/);
    assert.match(d, /useEffect\(\(\) => \{ setAsking\(false\); \}, \[askTotal\]\);/);
  });
  test("the ask is drawn with the panel's existing pieces, nothing new", () => {
    const card = d.slice(d.indexOf('<div className="mgtr-capask"'));
    for (const cls of ["mgtr-capask-head", "mgtr-ghost", "mgtr-go"]) assert.ok(card.includes(cls), cls);
    const css = src("styles/train.css");
    for (const cls of [".mgtr-capask ", ".mgtr-ghost ", ".mgtr-row-go "]) assert.ok(css.includes(cls), cls + " is an existing rule");
  });
});

describe("the phone asks in its sheet (unchanged, held)", () => {
  const m = src("components/TrainMobile.jsx");
  test("its describe button opens the sheet; the sheet's button sends", () => {
    assert.match(m, /onClick=\{\(\) => openSheet\("describe"\)\}>\s*\{describeLabel\(q\)\}<\/button>/);
    assert.equal((m.match(/a\.describe\(/g) || []).length, 1);
    const sheet = m.indexOf('open={sheet === "describe"}');
    assert.ok(sheet >= 0 && m.indexOf("await a.describe();") > sheet);
  });
});
