/* =========================================================================
   loom-ribbon-core.js — THE CONTINUITY RIBBON (Session P, NOTES P9), as pure views.

   The page (Loom Handoff.dc.html, section B, P9): "This shows in the full timeline mode,
   under the reel. There's one pair per cut: shot N's close frame beside shot N+1's open
   frame, both from the selected takes. A peach dot marks either a stale P2 anchor or a
   strong colour jump (mean Lab ΔE over 25, a heuristic, labelled as such). Clicking a pair
   opens both shots." NOTES P9: "compute in Lab, not RGB" (the prototype's stand-in used an
   RGB distance; this build does not).

   BUILD-w5-p §5.2: the pairs come from the RENDERED shots in board order (an unrendered shot is
   skipped, as Play skips it), each read through selectedTakeView -- the ★ take with the card's
   authoritative trims laid over it (review F9), never a stored copy. The frames themselves are
   GET /api/loom/frame (a local ffmpeg still; no upload, never PixAI).

   THE COLOUR JUMP: each frame is drawn small (RIBBON_GRID) and compared pixel for pixel:
   sRGB -> linear -> XYZ (D65) -> CIELAB, the CIE76 ΔE*ab (plain Euclidean distance in Lab) per
   pixel, averaged. Over RIBBON_DE_THRESHOLD is a "strong colour jump" -- a heuristic, never a
   verdict. CIE76, not CIEDE2000: the threshold is the page's, and the page names mean Lab ΔE.

   Same discipline as loom-core.js: NO React, no DOM, no window, no fetch.
   ========================================================================================= */
import { selectedTakeView, anchorState } from "./loom-takes-core.js";

export const RIBBON_DE_THRESHOLD = 25;
export const RIBBON_FPS = 24;
/** The grid each frame is drawn into before the comparison (a 16:9 downsample). */
export const RIBBON_GRID = { w: 32, h: 18 };

const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : null; };

/**
 * ribbonPairs(entries, byId) -> [{key, a, b, stale}]
 *   entries  flat(project), board order
 *   a        the cut's outgoing shot: {cardId, code, mid, take, at: trimOut ?? dur ?? null (its end)}
 *   b        the incoming shot:       {cardId, code, mid, take, at: trimIn}
 *   stale    the incoming shot's anchor is stale (P2)
 * One pair per consecutive pair of RENDERED shots; an unrendered shot between them is skipped.
 */
export const ribbonPairs = (entries, byId) => {
  const list = entries || [];
  const map = byId || new Map(list.map((e) => [e.c.id, e.c]));
  const rendered = list.map((e) => ({ e, v: selectedTakeView(e.c) })).filter((x) => x.v && x.v.mid);
  const out = [];
  for (let i = 0; i + 1 < rendered.length; i++) {
    const A = rendered[i], B = rendered[i + 1];
    // The close: the trim, else the clip's recorded length, else THE END (null): a length that
    // was never recorded is not estimated from the planned one (GitHub #63) -- frameUrl asks the
    // server for the clip's true last frame instead.
    const aAt = A.v.trimOut != null ? A.v.trimOut : (A.v.dur != null ? A.v.dur : null);
    out.push({
      key: A.e.c.id + ">" + B.e.c.id,
      a: { cardId: A.e.c.id, code: A.e.code, mid: String(A.v.mid), take: A.v.n, at: aAt == null ? null : (num(aAt) || 0) },
      b: { cardId: B.e.c.id, code: B.e.code, mid: String(B.v.mid), take: B.v.n, at: num(B.v.trimIn) || 0 },
      stale: anchorState(B.e.c, map) === "stale",
    });
  }
  return out;
};

/** The frame's address: the time quantised to a 24 fps frame, as the server names its cache.
 *  No time (null) is the clip's true last frame: `&end=1` (GitHub #63). */
export const frameUrl = (mid, at) => "/api/loom/frame?mid=" + encodeURIComponent(String(mid || ""))
  + (at == null ? "&end=1" : "&at=" + (Math.round(Math.max(0, num(at) || 0) * RIBBON_FPS) / RIBBON_FPS).toFixed(4));

/* ---------- colour: sRGB -> linear -> XYZ (D65) -> CIELAB ---------- */

const toLinear = (c) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
const D65 = [0.95047, 1.0, 1.08883];
const labF = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);

/** [r, g, b] (0-255, sRGB) -> [L, a, b] (CIELAB, D65 white). */
export const rgbToLab = (rgb) => {
  const R = toLinear(rgb[0]), G = toLinear(rgb[1]), B = toLinear(rgb[2]);
  const X = R * 0.4124564 + G * 0.3575761 + B * 0.1804375;
  const Y = R * 0.2126729 + G * 0.7151522 + B * 0.0721750;
  const Z = R * 0.0193339 + G * 0.1191920 + B * 0.9503041;
  const fx = labF(X / D65[0]), fy = labF(Y / D65[1]), fz = labF(Z / D65[2]);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
};

/** CIE76 ΔE*ab: the Euclidean distance between two Lab colours. */
export const deltaE76 = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);

/**
 * meanDeltaE(pixA, pixB) -> mean ΔE over the grid, or null when there is nothing to compare.
 * pixA / pixB: RGBA byte arrays of the SAME grid (a canvas's getImageData().data). A pixel
 * that is transparent in either frame is left out.
 */
export const meanDeltaE = (pixA, pixB) => {
  if (!pixA || !pixB) return null;
  const n = Math.min(pixA.length, pixB.length);
  let sum = 0, count = 0;
  for (let i = 0; i + 3 < n; i += 4) {
    if (pixA[i + 3] === 0 || pixB[i + 3] === 0) continue;
    sum += deltaE76(rgbToLab([pixA[i], pixA[i + 1], pixA[i + 2]]), rgbToLab([pixB[i], pixB[i + 1], pixB[i + 2]]));
    count += 1;
  }
  return count ? sum / count : null;
};

/** A strong colour jump? (null = not measured: no flag.) */
export const colourJump = (mean) => mean != null && mean > RIBBON_DE_THRESHOLD;

/** The pair's title, in the page's words. `frames` is "ok" once both frames were measured,
 *  "missing" when one could not be produced here, anything else while they load. */
export const pairTitle = (pair, mean, frames) => {
  if (pair && pair.stale) return pair.b.code + ": anchor changed";
  if (frames === "missing") return "No frame to compare here (the clip isn't on this machine, or ffmpeg isn't installed)";
  if (colourJump(mean)) return "Strong colour jump (a heuristic, not a verdict)";
  if (frames !== "ok") return "Comparing the frames…";
  return "Matches";
};

/** The peach dot: a stale anchor, or a colour jump that was measured. */
export const pairFlagged = (pair, mean) => !!(pair && pair.stale) || colourJump(mean);
