import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { mediaRefIndex, bundleMissingReport } from "../src/loom-core.js";

/* M24 -- "Bundle exported, but 2 referenced file(s) couldn't be found on disk."
   /api/loom/export-bundle knew exactly which media_ids it could not find; the client was
   handed len(missing) and nothing else, so the owner learned a NUMBER and had no way to tell
   which act/shot lost a file short of unzipping the bundle and reading project.json by hand.
   The first repair added the server half -- X-Bundle-Missing, the ids themselves -- and left
   the client reading only X-Bundle-Missing-Count, so nothing in the app consumed the new
   header and the owner's experience did not change at all.

   This suite pins BOTH halves of the client side:
     - bundleMissingReport()/mediaRefIndex(): pure, so they can be exercised here. The labels
       are re-derived from the project the client just posted rather than sent in the header,
       because the header is deliberately length-capped (a header that grows with the project
       is how a bundle downloads fine on one machine and gets rejected by a proxy on the next).
       That makes this walk a second implementation of the server's _loom_collect_media_ids,
       so the last test reads moonglade_gallery.py and fails if its label shapes move.
     - the wiring in master-storyboard.jsx, by source assertion: this runner has no jsdom (see
       mg-generate-drawer-concurrent.test.js's comment on why real interaction verification
       needs a real browser), and the defect being guarded here is precisely "the header is
       never read", which is a source-level fact. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8").replace(/\r\n/g, "\n");
const gallery = readFileSync(path.join(__dirname, "../../moonglade_gallery.py"), "utf8").replace(/\r\n/g, "\n");

const project = {
  name: "Test", target: 60, look: "",
  assets: [{ id: "nel", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "mid-nel" }],
  acts: [
    { id: "a1", name: "Act one", cards: [
      { id: "s1", title: "The gate", resultMid: "mid-r1",
        openFrame: { mediaId: "mid-open" }, closeFrame: { mediaId: "mid-close" }, refs: [] },
      { id: "s2", title: "", resultMid: "mid-r2", openFrame: {}, closeFrame: {}, refs: [] },
    ] },
    { id: "a2", name: "Act two", cards: [
      { id: "s3", title: "Coda", resultMid: "", openFrame: { mediaId: "mid-nel" }, closeFrame: {}, refs: [] },
    ] },
  ],
};

describe("M24 -- the missing-media report names WHERE each id was referenced", () => {
  test("every media_id the bundle can carry is mapped to a shot code the owner can find on screen", () => {
    const idx = mediaRefIndex(project);
    assert.deepEqual(idx["mid-r1"], ["A·01 The gate (shot result)"]);
    assert.deepEqual(idx["mid-open"], ["A·01 The gate (openFrame)"]);
    assert.deepEqual(idx["mid-close"], ["A·01 The gate (closeFrame)"]);
    assert.deepEqual(idx["mid-r2"], ["A·02 (shot result)"], "an untitled shot is still located by its code");
    // One file used in two places is reported in both -- the owner needs to fix both.
    assert.deepEqual(idx["mid-nel"], ["B·01 Coda (openFrame)", "cast/asset Nelnamara"]);
  });

  test("a report built from both headers lists the ids WITH their places", () => {
    const rep = bundleMissingReport(project, "2", "mid-open,mid-nel");
    assert.equal(rep.total, 2);
    assert.equal(rep.hidden, 0);
    assert.deepEqual(rep.rows, [
      { mid: "mid-open", where: ["A·01 The gate (openFrame)"] },
      { mid: "mid-nel", where: ["B·01 Coda (openFrame)", "cast/asset Nelnamara"] },
    ]);
  });

  test("the server's bounded header: '+N more' is counted, never rendered as an id", () => {
    // _bundle_missing_header caps the value at ~900 bytes and collapses the overflow into a
    // trailing "+N more" element. Treating that as an id would put a fake file in the list.
    const rep = bundleMissingReport(project, "9", "mid-open,mid-r1,+7 more");
    assert.deepEqual(rep.rows.map((r) => r.mid), ["mid-open", "mid-r1"]);
    assert.equal(rep.hidden, 7, "the count header is authoritative, so the remainder is derived from it");
  });

  test("no list header at all degrades to the honest count, not to an empty or wrong list", () => {
    // An older gallery, or a project whose every missing id was dropped by the server's ASCII
    // sanitiser: the count still arrives and must still be reported.
    const rep = bundleMissingReport(project, "3", null);
    assert.equal(rep.total, 3);
    assert.deepEqual(rep.rows, []);
    assert.equal(rep.hidden, 3);
  });

  test("an id the project walk cannot place is shown bare, never guessed at", () => {
    const rep = bundleMissingReport(project, "1", "mid-unknown");
    assert.deepEqual(rep.rows, [{ mid: "mid-unknown", where: [] }]);
  });

  test("a clean export reports nothing (the dialog must not open on a complete bundle)", () => {
    const rep = bundleMissingReport(project, "0", "");
    assert.equal(rep.total, 0);
    assert.deepEqual(rep.rows, []);
    assert.equal(rep.hidden, 0);
  });
});

describe("M24 -- the client actually reads the header and shows the list", () => {
  const exportBundle = (() => {
    const m = jsx.match(/\n  const exportBundle = async \(\) => \{\n[\s\S]*?\n  \};\n/);
    assert.ok(m, "expected an `const exportBundle = async () => {` in master-storyboard.jsx");
    return m[0];
  })();

  test("exportBundle reads X-Bundle-Missing, not only the count", () => {
    assert.match(exportBundle, /X-Bundle-Missing-Count/);
    assert.match(exportBundle, /headers\.get\("X-Bundle-Missing"\)/,
      "the server sends the ids; reading only the count is the defect M24 was filed about");
    assert.match(exportBundle, /bundleMissingReport\(project,/);
  });

  test("the bare-count alert is gone -- a count with no names is what the finding is", () => {
    assert.doesNotMatch(jsx, /couldn't be found on disk and were left out/);
    assert.doesNotMatch(exportBundle, /alert\(`Bundle exported/);
  });

  test("the report is rendered as a list of places, and only when something is missing", () => {
    assert.match(exportBundle, /if \(report\.total\) setBundleMissing\(report\)/);
    assert.match(jsx, /\{bundleMissing && \(/, "the dialog must actually be mounted in App");
    assert.match(jsx, /bundleMissing\.rows\.map\(\(row\) =>/);
    assert.match(jsx, /row\.where/, "each row must show WHERE the id was referenced, not just the id");
    assert.match(jsx, /bundleMissing\.hidden > 0/, "a truncated header must say so rather than under-report");
  });
});

describe("M24 -- the client's label walk must stay faithful to the server's", () => {
  // mediaRefIndex() re-derives, client-side, the labels _loom_collect_media_ids builds
  // server-side, because they cannot ride in a length-capped header. Two implementations of
  // one naming scheme: if the server's shapes move and this one doesn't, the same file gets
  // two different names -- one in this dialog, one in the zip's missing_media manifest.
  test("the four label shapes this walk mirrors are still the ones the server writes", () => {
    assert.match(gallery, /"%s·%02d" % \(letter, ci \+ 1\)/);
    assert.match(gallery, /"%s \(shot result\)" % code/);
    assert.match(gallery, /"%s \(%s\)" % \(code, slot\)/);
    assert.match(gallery, /"cast\/asset %s" % who/);
    assert.match(gallery, /for slot in \("openFrame", "closeFrame"\)/);
  });

  test("the server still sends both headers, and still truncates with the marker this parses", () => {
    assert.match(gallery, /resp\.headers\["X-Bundle-Missing-Count"\]/);
    assert.match(gallery, /resp\.headers\["X-Bundle-Missing"\]/);
    assert.match(gallery, /"\+%d more" % \(len\(safe\) - i\)/);
  });
});
