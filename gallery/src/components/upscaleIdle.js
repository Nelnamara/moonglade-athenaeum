/* upscaleIdle -- the one honest reason the Upscale panel can't price/submit right now, as a
   short line for the cost badge. Extracted out of UpscalePanel.jsx (which imports React and a
   stylesheet, so it can't be loaded by a plain node test) into this pure, React-free module so
   the reasons are node-testable in isolation -- see loom/test/upscale-idle-reason.test.js.

   usePriceProbe renders build().idle when it is a STRING (badge.clear(String(idle))), so this is
   what the user reads underneath the panel when Go is not possible.

   The one thing this NEVER returns is a "pick a model" / "needs a model" sentence. An upscale
   takes the source image's OWN model version automatically -- PixAI's upscale dialog has no
   model control at all (../moonglade-internal/DECISIONS.md, "An upscale does not choose a model,
   and the catalog's model_id is a VERSION id", 2026-07-27) -- so a missing model is never the
   blocker here, and the price probe's old single "the cost appears once this image has a model"
   hint was a misdirection on images whose real blocker was the pixel ceiling.

   `mx` is the source's dynamic max ratio (UpscalePanel.maxRatio): 0 == unknown (no server limits,
   or no recorded size), 1 == already at PixAI's per-mode pixel ceiling, > 1 == real headroom.
   Passed in rather than recomputed so this stays free of window.MG_UPSCALE and testable in node.

   Returns null when the panel CAN price (a sized image, not a video, with real ratio headroom);
   otherwise a plain-language reason. */
export function idleReason(src, mode, mx) {
  if (!src) return "Open a picture to upscale.";
  if (src.is_video) return "Upscaling applies to images, not videos.";
  const w = parseInt(src.width, 10) || 0;
  const h = parseInt(src.height, 10) || 0;
  if (!w || !h) return "This image has no recorded size, so it can’t be priced.";
  if (mx > 1) return null;   // real headroom -> there is a cost to show
  if (!mx) {
    return "This page did not receive the upscale limits, so the cost can’t be checked here.";
  }
  // mx is 1 (or, defensively, any truthy value <= 1): the source is already at PixAI's
  // per-method pixel ceiling, so there is nothing left to enlarge. Name the current Method.
  return "This picture is already at PixAI’s size ceiling for "
    + (mode === "enlarge" ? "Upscale" : "Hires") + " — nothing to upscale.";
}

export default idleReason;
