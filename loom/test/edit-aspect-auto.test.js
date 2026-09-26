import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* The Edit card's Auto aspect and Edit Pro's new default (SCOPE_2026-09-26 E1/E2).

   Reference Pro publishes no default aspect, so PixAI's own Edit sends NO aspectRatio for it
   ("Auto"); "auto" is that choice as a value, and the server leaves aspectRatio out for it.
   Edit Pro publishes 3:5 as its default and offers 3:5 and 5:3. PixAI's own control takes a
   model's published default when you leave Auto for it -- switchEditModel's keep-or-correct
   rule gives exactly that, and says so through the label map, never the raw value.
   (tests/test_edit_upload.py holds the Python side and the EDIT_MODELS / EDIT_CAPS parity.) */

import {
  EDIT_ASPECT_AUTO, EDIT_CAPS, EDIT_DEFAULTS, buildEditPayload, editAspectLabel, switchEditModel,
} from "../../gallery/src/gen/editCore.js";

const base = (over) => ({ ...EDIT_DEFAULTS, source: "55", instruction: "x", ...over });

describe("Auto on Reference Pro, 3:5 on Edit Pro", () => {
  test("the defaults are the models' own", () => {
    assert.equal(EDIT_CAPS["reference-pro"].def.aspect, EDIT_ASPECT_AUTO);
    assert.equal(EDIT_CAPS["reference-pro"].aspects[0], EDIT_ASPECT_AUTO);
    assert.equal(EDIT_CAPS["edit-pro"].def.aspect, "3:5");
    assert.ok(EDIT_CAPS["edit-pro"].aspects.includes("5:3"));
    assert.ok(!EDIT_CAPS["edit-pro"].aspects.includes(EDIT_ASPECT_AUTO));
    assert.equal(EDIT_DEFAULTS.aspect, "3:5");
  });

  test("switching to Reference Pro from a ratio it lacks lands on Auto, and says Auto", () => {
    const { next, clamp } = switchEditModel(base({ model: "edit-pro", resolution: "2K", aspect: "3:5" }), "reference-pro");
    assert.equal(next.aspect, EDIT_ASPECT_AUTO);
    assert.equal(clamp, "Reference Pro has no 3:5 — aspect corrected to Auto.");
  });

  test("leaving Auto for a model with a default takes that default", () => {
    const { next, clamp } = switchEditModel(base({ model: "reference-pro", resolution: "2K", aspect: EDIT_ASPECT_AUTO }), "edit-pro");
    assert.equal(next.aspect, "3:5");
    assert.equal(clamp, "Edit Pro has no Auto — aspect corrected to 3:5.");
  });

  test("a ratio both models offer is kept, as before", () => {
    const { next, clamp } = switchEditModel(base({ model: "edit-pro", aspect: "16:9" }), "reference-pro");
    assert.equal(next.aspect, "16:9");
    assert.doesNotMatch(clamp, /aspect/);        // (the resolution note is its own business)
  });

  test("the payload carries the value; the label map only dresses it", () => {
    assert.equal(buildEditPayload(base({ model: "reference-pro", aspect: EDIT_ASPECT_AUTO })).aspect, "auto");
    assert.equal(editAspectLabel(EDIT_ASPECT_AUTO), "Auto");
    assert.equal(editAspectLabel("3:5"), "3:5");
  });

  test("no Auto wording promises to keep the source frame", async () => {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const path = (await import("node:path")).default;
    const dir = path.dirname(fileURLToPath(import.meta.url));
    for (const f of ["gen/editCore.js", "components/EditTab.jsx", "components/CreateMobile.jsx"]) {
      const src = readFileSync(path.resolve(dir, "../../gallery/src", f), "utf8");
      // user-visible strings only -- the comments beside the table say what Auto is NOT
      assert.doesNotMatch(src, /"[^"\n]*keeps? (the |your )?(source|original)[^"\n]*"/i, f);
      assert.doesNotMatch(src, />[^<\n]*keeps? (the |your )?(source|original)[^<\n]*</i, f);
    }
  });
});
