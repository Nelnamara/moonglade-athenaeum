import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { autoSync, fmtCadence } from "../../gallery/src/lib/livingRow.js";

/* Owner, 2026-11-18, on "99.4% Backed up": "I have asked this question myself and you once
   told me to just run sync again. I gave up caring." The pill now carries the server's plain
   line (moonglade.gallery.backup_coverage, dev/tests/test_api_bulk_json.py) on hover and on
   tap; and the Control Panel's Sync line says the same thing about auto-sync as the
   Runs-itself row above it. */

test("the Backed up pill carries the server's note, on hover and on tap", () => {
  const src = readFileSync(new URL("../../gallery/src/components/Banner.jsx", import.meta.url), "utf8");
  assert.match(src, /label="Backed up" emerald note=\{s\.coverage_note\}/);
  assert.match(src, /title=\{note \|\| undefined\}/);
  assert.match(src, /onClick: tell/);
});

test("auto-sync reads as one truth", () => {
  const living = { enabled: false, action: "sync", interval_hours: 6,
                   jobs: [{ action: "sync", enabled: true, interval_s: 43200 }],
                   catalog: [{ action: "sync", deferred: false }] };
  // the owner's C: state: the standing order off, the living Sync row on every 12 hours
  assert.deepEqual(autoSync(living), { on: true, every: "12 hours", by: "" });
  const standing = { ...living, enabled: true, catalog: [{ action: "sync", deferred: true }] };
  assert.deepEqual(autoSync(standing), { on: true, every: "6 hours", by: "the standing order" });
  const off = { ...living, jobs: [{ action: "sync", enabled: false, interval_s: 43200 }] };
  assert.equal(autoSync(off).on, false);
  assert.equal(autoSync(null).on, false);
  assert.equal(fmtCadence(900), "15 min");
  assert.equal(fmtCadence(86400), "1 day");
});

test("the Sync line asks autoSync, not the standing order alone", () => {
  const src = readFileSync(new URL("../../gallery/src/components/ControlPanelOverlay.jsx", import.meta.url), "utf8");
  const meta = src.slice(src.indexOf('className="mgcp-syncmeta"'), src.indexOf("Tend — care for the files"));
  assert.match(meta, /autoSync\(schedule\)/);
  assert.ok(!/schedule\.enabled \?/.test(meta), "the Sync line reads the standing order alone again");
});
