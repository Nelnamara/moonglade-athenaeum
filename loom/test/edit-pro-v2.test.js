import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* PixAI Edit Pro V2.0 in the Edit card (#67, PROBE_2026-10-02_site "Edit Pro V2.0 -- the facts").
   A new VERSION of Edit Pro, offered beside v1.0 (which stays: the Edit Pro AI Tools scenes run
   on it). The Python half is dev/tests/test_edit_upload.py (the EDIT_MODELS / EDIT_CAPS parity, the
   max_refs slice and the chat block). */

import {
  EDIT_CAPS, EDIT_DEFAULTS, buildEditPayload, editAspectGroups, editModelIsNew, switchEditModel,
} from "../../gallery/src/gen/editCore.js";
const base = (over) => ({ ...EDIT_DEFAULTS, source: "55", instruction: "x", ...over });
const refs = (n) => Array.from({ length: n }, (_, i) => ({ media_id: String(100 + i) }));

describe("Edit Pro V2.0 (#67)", () => {
  test("its own row, right after v1.0, labelled as PixAI labels it", () => {
    const keys = Object.keys(EDIT_CAPS);
    assert.equal(keys.indexOf("edit-pro-v2"), keys.indexOf("edit-pro") + 1);
    const c = EDIT_CAPS["edit-pro-v2"];
    assert.equal(c.label, "Edit Pro (v2.0)");
    assert.equal(c.max_refs, 10);
    assert.deepEqual(c.resolutions, ["1K", "2K"]);
    assert.deepEqual(c.qualities, ["low", "medium", "high"]);
    assert.deepEqual(c.aspects, ["16:9", "9:16", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "3:5", "5:3"]);
    assert.deepEqual(c.def, { resolution: "1K", quality: "medium", aspect: "3:5" });
    // v1.0 is unchanged and is still the card's default
    assert.equal(EDIT_CAPS["edit-pro"].max_refs, 4);
    assert.equal(EDIT_DEFAULTS.model, "edit-pro");
  });

  test("no extremes: V2.0 dropped 1:3 and 3:1, so nothing sits under More", () => {
    assert.deepEqual(editAspectGroups("edit-pro-v2").extreme, []);
    assert.deepEqual(editAspectGroups("edit-pro").extreme, ["1:3", "3:1"]);
  });

  test("the new tag, as PixAI marks it new, for thirty days", () => {
    assert.equal(editModelIsNew("edit-pro-v2", Date.parse("2026-10-02T12:00:00Z")), true);
    assert.equal(editModelIsNew("edit-pro-v2", Date.parse("2026-11-01T23:00:00Z")), true);
    assert.equal(editModelIsNew("edit-pro-v2", Date.parse("2026-11-02T00:30:00Z")), false);
  });

  test("v1.0 -> V2.0 keeps a 1:3 frame out and every reference in", () => {
    const { next, clamp } = switchEditModel(base({ model: "edit-pro", aspect: "1:3", refs: refs(3) }), "edit-pro-v2");
    assert.equal(next.aspect, "3:5");
    assert.match(clamp, /Edit Pro \(v2\.0\) has no 1:3/);
    assert.equal(next.refs.length, 3);
  });

  test("V2.0 -> v1.0 says what it dropped (ten images down to four)", () => {
    const { next, notice } = switchEditModel(base({ model: "edit-pro-v2", refs: refs(9) }), "edit-pro");
    assert.equal(next.refs.length, 3);
    assert.match(notice.note, /6 of your 9/);
  });

  test("the payload names the V2.0 row by key and carries every reference", () => {
    const p = buildEditPayload(base({ model: "edit-pro-v2", refs: refs(9), resolution: "2K", quality: "high", aspect: "16:9" }));
    assert.equal(p.edit_model, "edit-pro-v2");
    assert.equal(p.sources.length, 10);
    assert.equal(p.quality, "high");
  });
});
