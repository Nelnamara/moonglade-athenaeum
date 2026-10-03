import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The Lightbox's Tsubaki edit bar, the owner's call on the 2026-10-03 walk: it no longer sits over
   the foot of the picture on every still. It is hidden until the Lightbox's own ✎ Edit opens it,
   and it opens BELOW the picture (the stage gives up the room; the bar never covers the image).
   ✎ Edit again, or Esc, closes it. It gains one link at its end, "More options in the Edit drawer ↗",
   which does what ✎ Edit used to do. A picture the bar cannot edit (a video) still gets the drawer.

   The bar sends a PAID generation. Only its placement and its trigger changed; the send path, its
   gate and its spend latch did not. The first block below pins those three pieces of
   TsubakiEditBar.jsx byte for byte (the hashes were taken from the file before this change), on top
   of price-probe-structure.test.js's latch checks. The render harness measures the placement. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");
const sha = (t) => createHash("sha256").update(t).digest("hex");
// the source just before `mark` (a button's opening tag and its handlers, up to its label)
const before = (s, mark, n = 600) => {
  const at = s.indexOf(mark);
  return at > 0 ? s.slice(Math.max(0, at - n), at + mark.length) : "";
};
const slice = (s, from, to) => {
  const a = s.indexOf(from);
  const b = a >= 0 ? s.indexOf(to, a) : -1;
  return a >= 0 && b > a ? s.slice(a, b + to.length) : "";
};

describe("the bar's send path is untouched", () => {
  const bar = src("components/TsubakiEditBar.jsx");
  test("price, gate, latch and send(): byte for byte", () => {
    const send = slice(bar, "  const ready = ", "}, [words, ready, state, probe]);");
    assert.ok(send, "TsubakiEditBar.jsx: the ready ... send() block moved -- re-point this test, never drop it");
    assert.equal(sha(send), "add3fdc4ad7714ac2fdffdaf9757d6e6c3042e06f9e8209adf2bcec2ef737f4a");
  });
  test("Enter sends through the same guard", () => {
    const enter = slice(bar, '    if (e.key === "Enter" && !e.shiftKey) {', "      return;\n    }");
    assert.equal(sha(enter), "254f8627a6b580ba6be1a6dbf7ea597b16b2ce27c6894842ac10ad8063d2534e");
  });
  test("the ↑ button sends through the same gate", () => {
    const go = slice(bar, '        <button type="button" className="mgteb-go"', ">↑</button>");
    assert.equal(sha(go), "5241ae2bcc3b8ab9e6135855016c78b7cfde5cd0c51da024a9f32f3609866a6e");
  });
  test("the link it gains only opens the drawer: it is not the send button", () => {
    const more = slice(bar, '<button type="button" className="mgteb-more"', "</button>");
    assert.ok(more, "the bar has its More options link");
    assert.match(more, /onClick=\{onMore\}/);
    assert.match(more, /More options in the Edit drawer ↗/);
    assert.doesNotMatch(more, /send|submitTask|probe/);
  });
});

describe("desktop: ✎ Edit opens the bar below the picture", () => {
  const lbx = src("components/Lightbox.jsx");
  test("✎ Edit opens the bar for a picture it can edit, else the drawer as before", () => {
    const chip = before(lbx, "✎ Edit</button>", 400);
    assert.match(chip, /it\.tsubaki_edit \? toggleEdit\(\) : onEdit\(it\.media_id\)/);
  });
  test("the bar is drawn only while open, in the bottom band, never in the stage", () => {
    const stageAt = lbx.indexOf('<div className="lbx-stage"');
    const bottomAt = lbx.indexOf('<div className="lbx-bottom">');
    const barAt = lbx.indexOf("<TsubakiEditBar");
    assert.ok(stageAt > 0 && bottomAt > stageAt && barAt > bottomAt, "the bar sits below the stage");
    assert.equal(lbx.split("<TsubakiEditBar").length, 2, "one mount");
    assert.match(lbx, /\{editOpen && it\.tsubaki_edit \? \(\s*<TsubakiEditBar ref=\{barRef\} item=\{it\} member=\{member\} below/);
    assert.match(lbx, /onMore=\{\(\) => onEdit\(it\.media_id\)\}/);
    assert.match(lbx, /onDismiss=\{closeEdit\}/);
  });
  test("Esc closes an open bar before anything else in the chain", () => {
    const esc = slice(lbx, 'else if (e.key === "Escape") {', "else close();");
    assert.match(esc, /if \(editOpen\) closeEdit\(\);/);
    assert.ok(esc.indexOf("editOpen") < esc.indexOf("slideOn"), "the bar closes first");
  });
});

describe("phone: the same trigger", () => {
  const lbm = src("components/LightboxMobile.jsx");
  test("✎ Edit opens the bar on a still; anything else keeps today's note", () => {
    const chip = before(lbm, "✎ Edit</button>", 400);
    assert.match(chip, /it\.tsubaki_edit \? setEditOpen\(\(v\) => !v\)/);
    assert.match(chip, /toast\("Edit", "Its own mobile wiring — coming later\."\)/);
  });
  test("the bar is drawn only while open, first in the lower panel, right under the picture", () => {
    const bottomAt = lbm.indexOf('<div className="lbm-bottom">');
    const barAt = lbm.indexOf("<TsubakiEditBar");
    const placardAt = lbm.indexOf("<PlacardMobile");
    assert.ok(bottomAt > 0 && barAt > bottomAt && barAt < placardAt, "first in .lbm-bottom");
    assert.match(lbm, /\{editOpen && it\.tsubaki_edit \? \(\s*<TsubakiEditBar ref=\{barRef\} item=\{it\} member=\{member\} phone/);
  });
});
