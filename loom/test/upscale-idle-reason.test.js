import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { idleReason } from "../../gallery/src/components/upscaleIdle.js";

/* THE UPSCALE PANEL HAS NO MODEL BLOCKER (2026-08-23). The Upscale panel's price probe used to
   clear its badge to a single static hint -- "the cost appears once this image has a model" --
   for EVERY unpriceable state. That was the misdirection the owner hit: on an image already at
   PixAI's pixel ceiling, the real reason there was no cost was the CEILING, not a missing model,
   and an upscale needs no model at all (PixAI's upscale dialog has no model control -- see
   ../../moonglade-internal/DECISIONS.md, "An upscale does not choose a model, and the catalog's
   model_id is a VERSION id", 2026-07-27).

   idleReason is the extracted, React-free helper that gives the badge the REAL reason instead.
   These pin that it names the true blocker and NEVER a model. `mx` is the source's dynamic max
   ratio: 0 unknown, 1 at the per-mode ceiling, > 1 real headroom. */

const sized = (extra) => Object.assign({ width: 1024, height: 1024 }, extra || {});

describe("idleReason: the honest reason the upscale can't price -- never a model", () => {
  test("a source at PixAI's ceiling in Hires yields the at-ceiling sentence, naming the method", () => {
    const r = idleReason(sized(), "upscale", 1);
    assert.equal(typeof r, "string");
    assert.match(r, /already at/i);
    assert.match(r, /ceiling for Hires/, "the sentence must name the current Method (Hires)");
    assert.match(r, /nothing to upscale/);
    assert.doesNotMatch(r, /model/i, "the at-ceiling blocker must NEVER be phrased as a model problem");
  });

  test("a source at the ceiling in Upscale (enlarge) names Upscale, still no model", () => {
    const r = idleReason(sized(), "enlarge", 1);
    assert.match(r, /ceiling for Upscale/, "enlarge mode is labelled 'Upscale'");
    assert.doesNotMatch(r, /model/i);
  });

  test("missing dimensions yield the no-recorded-size sentence, not a model sentence", () => {
    const r = idleReason({ is_video: false }, "enlarge", 0);
    assert.match(r, /no recorded size/);
    assert.doesNotMatch(r, /model/i);
  });

  test("a video is told upscaling is for images, not a model prompt", () => {
    const r = idleReason(sized({ is_video: true }), "enlarge", 1.9);
    assert.match(r, /images, not videos/);
    assert.doesNotMatch(r, /model/i);
  });

  test("a page that never got the upscale limits says so, not 'pick a model'", () => {
    const r = idleReason(sized(), "enlarge", 0);
    assert.match(r, /upscale limits/);
    assert.doesNotMatch(r, /model/i);
  });

  test("a normal, priceable source (real headroom) yields null -- there IS a cost to show", () => {
    assert.equal(idleReason(sized(), "enlarge", 1.9), null);
    assert.equal(idleReason(sized(), "upscale", 1.4), null);
  });

  test("no input to the helper ever produces a string mentioning a model", () => {
    // Walk a representative matrix rather than trusting any single branch: every non-null reason
    // this helper can emit must be free of the word 'model'. A future branch that reintroduces
    // "pick a model" (the exact regression this fix removes) fails here.
    const srcs = [null, undefined, {}, sized(), sized({ is_video: true }),
      { width: 0, height: 0 }, { width: 1024 }, sized({ model_id: "" }), sized({ local_import: true })];
    const mxs = [0, 1, 1.1, 1.4, 1.9, 3];
    for (const s of srcs) {
      for (const mode of ["enlarge", "upscale"]) {
        for (const mx of mxs) {
          const r = idleReason(s, mode, mx);
          if (r != null) {
            assert.equal(typeof r, "string");
            assert.doesNotMatch(r, /model/i,
              `idleReason(${JSON.stringify(s)}, ${mode}, ${mx}) mentioned a model: "${r}"`);
          }
        }
      }
    }
  });
});
