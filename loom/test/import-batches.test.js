import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  IMPORT_BATCH_BYTES, IMPORT_BATCH_FILES, importInBatches, notImportedNote, splitImportBatches,
} from "../../gallery/src/lib/importBatches.js";

// #82: Web Import took the first 1,000 files of one request and dropped the rest without a word. The page
// now sends batches and adds the answers up; the route counts what it did not take (`not_taken`) and the
// finished message prints it.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

const fakeFile = (name, size = 10) => ({ name, size });
const many = (n) => Array.from({ length: n }, (_, i) => new File(["x"], "f" + i + ".png"));

describe("splitImportBatches", () => {
  test("a folder past the route's thousand goes in several requests, every file in exactly one, in order", () => {
    const files = many(2350);
    const batches = splitImportBatches(files);
    assert.ok(batches.length > 2);
    assert.deepEqual(batches.flat(), files);
    for (const b of batches) assert.ok(b.length <= IMPORT_BATCH_FILES);
  });

  test("the batch size sits well under the route's per-request cap of 1,000", () => {
    assert.ok(IMPORT_BATCH_FILES <= 500);
    const py = src("moonglade/gallery.py");
    const cap = Number(/^IMPORT_REQUEST_CAP = (\d+)$/m.exec(py)[1]);
    assert.equal(cap, 1000);
    assert.ok(IMPORT_BATCH_FILES < cap);
  });

  test("a byte limit closes a batch early; one oversized file travels alone", () => {
    const files = [fakeFile("a", 60), fakeFile("b", 60), fakeFile("c", 500), fakeFile("d", 10)];
    const batches = splitImportBatches(files, 100, 100);
    assert.deepEqual(batches.map((b) => b.map((f) => f.name)), [["a"], ["b"], ["c"], ["d"]]);
    assert.ok(IMPORT_BATCH_BYTES > 0);
  });

  test("nothing in, nothing out", () => {
    assert.deepEqual(splitImportBatches([]), []);
    assert.deepEqual(splitImportBatches(undefined), []);
  });
});

describe("importInBatches", () => {
  // The fake server: takes at most `cap` files of a request, counts the rest as not_taken, imports the others.
  const server = (cap, log) => async (fd) => {
    const got = fd.getAll("files");
    log.push({ n: got.length, collection: fd.get("collection") });
    const taken = Math.min(cap, got.length);
    return { ok: true, imported: taken, skipped: 0, not_taken: got.length - taken, collection: fd.get("collection") || null };
  };

  test("1,200 files reach the server in full: nothing past 1,000 is lost to one request", async () => {
    const log = [];
    const r = await importInBatches(many(1200), "Imports", server(1000, log));
    assert.equal(r.ok, true);
    assert.equal(r.imported, 1200);
    assert.equal(r.notTaken, 0);
    assert.equal(r.sent, 1200);
    assert.equal(r.collection, "Imports");
    assert.ok(log.length > 1, "more than one request");
    assert.ok(log.every((c) => c.n <= 1000 && c.collection === "Imports"));
    assert.equal(log.reduce((a, c) => a + c.n, 0), 1200);
  });

  test("skipped counts from every batch add up", async () => {
    let call = 0;
    const r = await importInBatches(many(450), "", async (fd) => {
      call += 1;
      const n = fd.getAll("files").length;
      return { ok: true, imported: n - 1, skipped: 1, not_taken: 0, collection: null };
    });
    assert.equal(call, 3);
    assert.equal(r.skipped, 3);
    assert.equal(r.imported, 447);
  });

  test("whatever the server reports it did not take is carried, so the page can say so", async () => {
    const r = await importInBatches(many(10), "", server(4, []), { maxFiles: 100 });
    assert.equal(r.ok, true);
    assert.equal(r.imported, 4);
    assert.equal(r.notTaken, 6);
  });

  test("no collection is sent when none was chosen", async () => {
    const log = [];
    await importInBatches(many(3), "", server(1000, log));
    assert.equal(log[0].collection, null);
  });

  test("a first-batch failure reads exactly as the single request did, and nothing counts as sent", async () => {
    const r = await importInBatches(many(450), "", async () => ({ error: "no usable files" }));
    assert.deepEqual(r, { ok: false, error: "no usable files", imported: 0, skipped: 0, notTaken: 0, sent: 0 });
  });

  test("a later failure says how far it got, and `sent` is the files the earlier batches carried", async () => {
    let call = 0;
    const r = await importInBatches(many(450), "", async (fd) => {
      call += 1;
      if (call === 3) return { error: "disk full" };
      return { ok: true, imported: fd.getAll("files").length, skipped: 0, not_taken: 0 };
    });
    assert.equal(r.ok, false);
    assert.equal(r.sent, 400);
    assert.equal(r.imported, 400);
    assert.equal(r.error, "Stopped after 400 of 450 files (400 imported): disk full");
  });

  test("a dropped connection is a network error, with the same progress rule", async () => {
    let call = 0;
    const r = await importInBatches(many(450), "", async (fd) => {
      call += 1;
      if (call === 2) throw new Error("boom");
      return { ok: true, imported: fd.getAll("files").length, skipped: 0, not_taken: 0 };
    });
    assert.equal(r.ok, false);
    assert.equal(r.error, "Stopped after 200 of 450 files (200 imported): network error");
    const first = await importInBatches(many(3), "", async () => { throw new Error("x"); });
    assert.equal(first.error, "network error");
  });
});

describe("notImportedNote: the finished message's tail", () => {
  test("silent when nothing was left out, names the count when something was", () => {
    assert.equal(notImportedNote({ notTaken: 0 }), "");
    assert.equal(notImportedNote({}), "");
    assert.equal(notImportedNote(null), "");
    assert.equal(notImportedNote({ notTaken: 200 }), " · 200 not imported (over the server's per-request limit)");
  });
});

describe("the hook and both screens use them", () => {
  test("useImport sends through importInBatches, never one FormData of every file", () => {
    const s = src("gallery/src/hooks/useImport.js");
    assert.match(s, /importInBatches\(files, coll,/);
    assert.doesNotMatch(s, /files\.forEach\(\(f\) => fd\.append/);
  });

  test("the desktop overlay and the phone screen both print the not-imported note", () => {
    for (const f of ["gallery/src/components/ImportOverlay.jsx", "gallery/src/components/ImportMobile.jsx"]) {
      const s = src(f);
      assert.match(s, /import \{ notImportedNote \} from "\.\.\/lib\/importBatches\.js";/, f);
      assert.match(s, /\{notImportedNote\(result\)\}/, f);
    }
  });
});
