import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { friendlyGenErr } from "../src/loom-mutations.js";
import { friendlyGenErr as localFriendlyGenErr } from "../../gallery/src/gen/videoDrawerCore.js";

// The video Generate drawer carries a deliberate, hand-maintained LOCAL COPY of
// friendlyGenErr (gallery/src/gen/videoDrawerCore.js) so a video generation rejected by PixAI
// reads identically whether it surfaced via the Loom's own poll path or the drawer's independent
// submit/poll cycle. There is no shared module the Loom bundle and the gallery build can both
// import at build time without pulling in loom-core, so the mapping is intentionally duplicated
// (see videoDrawerCore.js's own duplication-risk comment next to the function). The only guard
// against the two silently drifting apart on a future edit to either one is this test.
//
// Before the no-vanilla port (2026-08-08) the copy lived inline in static/mg-generate-drawer.js
// (a build-free <script>), so this test regex-extracted it as text. Now videoDrawerCore.js is a
// real ES module with no DOM/React dependency, so the copy is imported directly and compared
// across the same fixed case list. If this ever fails, someone edited one copy without the other.
//
// (There used to be a THIRD hand-copy in moonglade_gallery.py's classic Image-tab inline
// <script>, checked here too; that whole classic surface was removed in the 2026-08-08 classic
// cut, so only the drawer's copy remains to keep in parity with the real one.)

const CASES = [
  "INSUFFICIENT_BALANCE", "insufficient balance for this task", "40300010",
  "content policy violation", "flagged as sensitive content", "Sensitive content.",
  "prohibited content detected", "not allowed here", "violates our terms",
  'unknown inferenceProfile "ultra" for model type "SDXL_MODEL"', "InferenceProfile rejected",
  "some other random failure", "task failed", "cancelled", "rejected",
  "", null, undefined, 0, false,
];

describe("videoDrawerCore.js's local friendlyGenErr stays in parity with loom-mutations.js's real one", () => {
  CASES.forEach((c) => {
    test(`matches real friendlyGenErr for input ${JSON.stringify(c)}`, () => {
      assert.equal(localFriendlyGenErr(c), friendlyGenErr(c));
    });
  });
});
