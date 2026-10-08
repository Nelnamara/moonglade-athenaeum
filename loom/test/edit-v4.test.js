import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* PixAI Edit v4.0 in the Edit card (Session L decision 6, lane w2-small 2026-09-28). It adds a
   model to a paid submit; the design and its spend review are moonglade-internal/design/notes/
   small-calls/BUILD-w2-small.md. The Python half is dev/tests/test_edit_upload.py (the EDIT_MODELS /
   EDIT_CAPS parity and the chat block). */

import {
  EDIT_ASPECT_AUTO, EDIT_CAPS, EDIT_DEFAULTS, buildEditPayload, editAspectExtreme,
  editAspectGroups, editModelIsNew, switchEditModel,
} from "../../gallery/src/gen/editCore.js";
const base = (over) => ({ ...EDIT_DEFAULTS, source: "55", instruction: "x", ...over });

describe("Edit v4.0 (L6)", () => {
  test("first in the list, its own record, and the card's default stays Edit Pro", () => {
    assert.equal(Object.keys(EDIT_CAPS)[0], "edit-v4");
    const c = EDIT_CAPS["edit-v4"];
    assert.equal(c.max_refs, 10);
    assert.deepEqual(c.resolutions, ["1K", "2K", "4K"]);
    assert.deepEqual(c.qualities, []);
    assert.equal(c.def.aspect, EDIT_ASPECT_AUTO);
    assert.equal(EDIT_DEFAULTS.model, "edit-pro");
  });

  test("labelled as PixAI labels it: PixAI Edit (v4.0) (owner's walk, 2026-10-03)", () => {
    assert.equal(EDIT_CAPS["edit-v4"].label, "PixAI Edit (v4.0)");
  });

  test("the extremes sit under More: long side at least twice the short", () => {
    assert.deepEqual(editAspectGroups("edit-v4").extreme, ["21:9", "1:4", "4:1", "1:8", "8:1"]);
    assert.ok(editAspectGroups("edit-v4").common.includes(EDIT_ASPECT_AUTO));
    assert.deepEqual(editAspectGroups("edit-pro").extreme, ["1:3", "3:1"]);
    assert.deepEqual(editAspectGroups("reference-pro").extreme, ["21:9"]);
    assert.equal(editAspectExtreme("16:9"), false);
    assert.equal(editAspectExtreme("auto"), false);
  });

  test("the new tag lasts thirty days", () => {
    assert.equal(editModelIsNew("edit-v4", Date.parse("2026-09-28T12:00:00Z")), true);
    assert.equal(editModelIsNew("edit-v4", Date.parse("2026-10-28T23:00:00Z")), true);
    assert.equal(editModelIsNew("edit-v4", Date.parse("2026-10-29T00:30:00Z")), false);
    assert.equal(editModelIsNew("edit-pro", Date.parse("2026-09-28T12:00:00Z")), false);
  });

  test("switching to it keeps ten refs and corrects what it cannot take, with the notes", () => {
    const refs = Array.from({ length: 9 }, (_, i) => ({ media_id: String(100 + i) }));
    const { next, notice, clamp } = switchEditModel(
      base({ model: "reference-pro", resolution: "4K", aspect: "21:9", refs }), "edit-v4");
    assert.equal(next.refs.length, 9);
    assert.equal(notice, null);
    assert.equal(next.resolution, "4K");
    assert.equal(next.aspect, "21:9");
    assert.equal(clamp, "");
    const back = switchEditModel({ ...next, aspect: "1:8" }, "edit-pro");
    assert.equal(back.next.refs.length, 3);
    assert.match(back.notice.note, /Only 3 reference images kept/);
    assert.equal(back.next.resolution, "1K");
    assert.equal(back.next.aspect, "3:5");
    assert.match(back.clamp, /Edit Pro offers 1K\/2K only/);
  });

  test("its payload names the model and sends no quality", () => {
    const p = buildEditPayload(base({ model: "edit-v4", quality: "high", resolution: "4K", aspect: "8:1" }));
    assert.equal(p.edit_model, "edit-v4");
    assert.equal(p.quality, "");
    assert.equal(p.resolution, "4K");
    assert.equal(p.aspect, "8:1");
  });
});

