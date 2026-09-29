import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* The Tsubaki Multi-Reference aspect ratio (reference 36, lane w2-small 2026-09-28). It changes
   what a paid referenceVideo request sends; the design and its spend review are
   moonglade-internal/design/notes/small-calls/BUILD-w2-small.md. The Python half is
   tests/test_video_tsubaki.py (referenceVideo.ratio on the web road). */

import {
  VIDEO_RATIOS, applyMode, applyModelGating, applyPrefill, buildPayload, priceKey,
  ratioForPayload, ratioLabel, ratioOffered,
} from "../../gallery/src/gen/videoDrawerCore.js";

const vstate = (over) => Object.assign({
  mode: "r2v", slots: [null], imgSlots: [{ media_id: "1" }], vidSlots: [null], audSlot: null,
  model: "tbkv1.0.1", duration: 5, camera: "unset", quality: "professional", channel: "normal",
  audioGen: false, audioLanguage: "english", videoHelper: false, negative: "", modeNote: "",
  ratio: "adaptive",
}, over);

describe("the Tsubaki Multi-Reference aspect ratio (reference 36)", () => {
  test("PixAI's set and order, Auto first", () => {
    assert.deepEqual(VIDEO_RATIOS, ["adaptive", "1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]);
    assert.equal(ratioLabel("adaptive"), "Auto");
  });

  test("offered only for a Tsubaki engine in Multi-Reference", () => {
    assert.equal(ratioOffered(vstate({})), true);
    assert.equal(ratioOffered(vstate({ model: "tbkv1.0" })), true);
    assert.equal(ratioOffered(vstate({ model: "v4.0.1" })), false);
    assert.equal(ratioOffered(vstate({ mode: "i2v" })), false);
  });

  test("the payload carries it only when offered and not Auto; otherwise the key is absent", () => {
    assert.equal(buildPayload(vstate({ ratio: "16:9" }), "p").ratio, "16:9");
    for (const s of [vstate({}), vstate({ ratio: "16:9", model: "v4.0.1" }),
      vstate({ ratio: "16:9", mode: "flf", slots: [{ media_id: "1" }, null] }), vstate({ ratio: "7:3" })]) {
      assert.ok(!("ratio" in buildPayload(s, "p")), JSON.stringify(s.ratio + " " + s.model + " " + s.mode));
    }
    // no ratio -> byte-identical to a state that never had the field
    const plain = vstate({});
    delete plain.ratio;
    assert.equal(priceKey(buildPayload(vstate({}), "p")), priceKey(buildPayload(plain, "p")));
    assert.equal(ratioForPayload(vstate({ ratio: "21:9" })), "21:9");
  });

  test("the pick is held across an engine or mode switch, and re-applies on the way back", () => {
    const s = vstate({ ratio: "9:16" });
    s.model = "v4.0.1";
    applyModelGating(s, true);
    assert.equal(s.ratio, "9:16");
    assert.ok(!("ratio" in buildPayload(s, "p")));
    s.model = "tbkv1.0.1";
    applyModelGating(s, true);
    applyMode(s, "r2v", true);
    assert.equal(buildPayload(s, "p").ratio, "9:16");
  });

  test("a prefill is a new shot: the ratio it names, else Auto (review N7)", () => {
    const s = vstate({ ratio: "9:16" });
    applyPrefill(s, { mode: "r2v", video_model: "tbkv1.0.1", images: [{ media_id: "2" }] });
    assert.equal(s.ratio, "adaptive");
    applyPrefill(s, { mode: "r2v", video_model: "tbkv1.0.1", images: [{ media_id: "2" }], ratio: "3:2" });
    assert.equal(s.ratio, "3:2");
    applyPrefill(s, { ratio: "bogus" });
    assert.equal(s.ratio, "adaptive");
  });
});
