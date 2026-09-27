/* THE CLIP MOMENT'S PLAYER MODEL -- no DOM, no React, so loom/test can pin it without a
   browser (moment-stage.test.js).

   Two feats celebrate with a video clip and a UI ceremony laid over it. Each has a locked
   Design Handoff page (the celebration-videos set in the private moonglade-internal repo)
   that renders a fixed 1920 x 1080 stage in which every overlay value is a pure function of
   ONE authored clock, T. This file is that page's player model, ported number for number:

     T        authored seconds. The clip plays from T = LEAD, so the video's own time is
              T - LEAD, and the page shows the clip frame clamp(T - LEAD, 0, CLIP_DUR - .05)
              -- the last .05 s is never shown, and the Hold beat freezes on that frame.
     CUES     each scene's start, the running sum of the scene lengths (the page derives the
              same table from its OM_SCENES list and rounds it to the millisecond).
     easings  the page engine's own curves (Popmotion-style, hand-rolled) -- copied, not
              approximated, because an easeOutBack that overshoots 0.1% differently is a
              keycap in a different place on the parity sheet.

   What is NOT here is copy. Every sentence a moment says arrives at runtime from
   /api/achievements (moment_copy), and the scene list carries names and lengths only. */

export const W = 1920;
export const H = 1080;
export const LEAD = 0.5;          // the lead-in before the clip's first frame
export const CLIP_DUR = 15.04;    // both delivered clips are this long

/* The two scene lists, in the pages' own order and lengths (OM_SCENES). */
export const SCENES = {
  starfall: [
    { name: "Code", dur: 3 }, { name: "Turn", dur: 3 }, { name: "Gather", dur: 4.5 },
    { name: "Cast", dur: 1.8 }, { name: "Starfall", dur: 3.24 }, { name: "Hold", dur: 2.5 },
  ],
  keyturn: [
    { name: "Rise", dur: 3.5 }, { name: "Key", dur: 3.7 }, { name: "Flight", dur: 2.6 },
    { name: "Door", dur: 3.4 }, { name: "Inside", dur: 6 },
  ],
};

/* The page engine's cue derivation (ccDerive): starts are the running sum of the lengths,
   rounded to the millisecond, and the total is rounded the same way. */
export function cuesFrom(scenes) {
  const table = {};
  let at = 0;
  for (const s of scenes) {
    if (!Object.prototype.hasOwnProperty.call(table, s.name)) table[s.name] = Math.round(at * 1000) / 1000;
    at += s.dur;
  }
  return { cues: table, total: Math.round(at * 1000) / 1000 };
}

// ---- the page engine's motion helpers, verbatim --------------------------------------------
export const Easing = {
  linear: (t) => t,
  easeOutCubic: (t) => (--t) * t * t + 1,
  easeInOutCubic: (t) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
  easeOutBack: (t) => {
    const c1 = 1.70158, c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },
};

export const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

export function interpolate(input, output, ease = Easing.linear) {
  return (t) => {
    if (t <= input[0]) return output[0];
    if (t >= input[input.length - 1]) return output[output.length - 1];
    for (let i = 0; i < input.length - 1; i++) {
      if (t >= input[i] && t <= input[i + 1]) {
        const span = input[i + 1] - input[i];
        const local = span === 0 ? 0 : (t - input[i]) / span;
        const easeFn = Array.isArray(ease) ? (ease[i] || Easing.linear) : ease;
        return output[i] + (output[i + 1] - output[i]) * easeFn(local);
      }
    }
    return output[output.length - 1];
  };
}

export function animate({ from = 0, to = 1, start = 0, end = 1, ease = Easing.easeInOutCubic }) {
  return (t) => {
    if (t <= start) return from;
    if (t >= end) return to;
    return from + (to - from) * ease((t - start) / (end - start));
  };
}

/* The pages' three motion helpers (MOTION): enter, pop, draw. */
export const MOTION = {
  enter: (a) => animate({ ...a, ease: Easing.easeOutCubic }),
  pop: (a) => animate({ ...a, ease: Easing.easeOutBack }),
  draw: (a) => animate({ ...a, ease: Easing.easeInOutCubic }),
};

/* THE PAGE'S CLAMP, the one frame rule. `clipEnd` is the clip's real length, capped at
   CLIP_DUR: for the delivered clips it IS CLIP_DUR, so this is the page's
   clamp(T - LEAD, 0, CLIP_DUR - .05) exactly; a shorter file (the test fixture) freezes on
   its own last frame instead of asking the decoder for one past its end on every tick. */
export function clipEndOf(duration) {
  const d = Number(duration);
  return d > 0 && isFinite(d) ? Math.min(CLIP_DUR, d) : CLIP_DUR;
}
export function clipTime(T, clipEnd = CLIP_DUR) {
  return clamp(T - LEAD, 0, clipEnd - 0.05);
}
/* The page re-seeks a paused clip only when it is more than 20 ms off (its Clip effect's
   `Math.abs(v.currentTime - ct) > .02`). The harness seek uses the same rule, so a frame the
   page would not have moved for is not moved here either. */
export const SEEK_EPSILON = 0.02;
export function needsSeek(currentTime, ct) {
  return Math.abs(Number(currentTime) - ct) > SEEK_EPSILON;
}

/* THE LIVE CLOCK, one step per animation frame. Three phases, the page's own:
     lead  0 <= T < LEAD on the page clock, the clip paused on its first frame;
     clip  T = video.currentTime + LEAD -- the VIDEO is the clock while it plays, so the
           overlay stays registered to the picture through a stall or a slow decode;
     hold  from the clip's last shown frame (the page pauses once the clip time reaches
           clipEnd - .1) T runs on the page clock again from where the video left off, and
           the clip is held on clipTime(T), which stops moving at clipEnd - .05.
   Returns the next state plus what the caller must do to the <video> this frame. */
export function startClock(now) {
  return { phase: "lead", t0: now, T: 0, holdBase: 0, holdAt: 0 };
}
export function stepClock(s, { now, videoTime = 0, ended = false, clipEnd = CLIP_DUR, total }) {
  const out = { ...s, play: false, pause: false, seekTo: null, done: false };
  if (s.phase === "lead") {
    const T = (now - s.t0) / 1000;
    if (T < LEAD) { out.T = Math.max(0, T); return out; }
    out.phase = "clip";
    out.T = LEAD;
    out.play = true;
    return out;
  }
  if (s.phase === "clip") {
    out.T = Math.max(s.T, videoTime + LEAD);
    if (ended || videoTime >= clipEnd - 0.1) {
      out.phase = "hold";
      out.holdBase = out.T;
      out.holdAt = now;
      out.pause = true;
      const ct = clipTime(out.T, clipEnd);
      if (needsSeek(videoTime, ct)) out.seekTo = ct;
    }
    return out;
  }
  if (s.phase === "hold") {
    const T = s.holdBase + (now - s.holdAt) / 1000;
    out.T = Math.min(T, total);
    const ct = clipTime(out.T, clipEnd);
    if (needsSeek(videoTime, ct)) out.seekTo = ct;
    if (T >= total) { out.phase = "done"; out.done = true; }
    return out;
  }
  out.done = s.phase === "done";
  return out;
}

/* THE TWO LAYERS (review amendment 4). The clip and the effects registered to it (the
   flares, the star rain) scale as ONE stage: cover on a landscape screen, contain -- the
   whole composition, letterboxed on the moment's dark ground -- on a portrait one (owner,
   2026-09-26). The UI (keycaps, rail, toast, caption, button) is laid out in a SAFE BOX at
   the same 1920 x 1080 coordinates, always contain-fitted so nothing of it is ever cropped.
   At 1920 x 1080 both are scale 1 at the origin, which is what makes the parity pass exact. */
export function fitStage(vw, vh) {
  const portrait = vh > vw;
  const scale = portrait ? Math.min(vw / W, vh / H) : Math.max(vw / W, vh / H);
  return { scale, x: (vw - W * scale) / 2, y: (vh - H * scale) / 2, mode: portrait ? "contain" : "cover" };
}
export function fitSafe(vw, vh) {
  const scale = Math.min(vw / W, vh / H);
  return { scale, x: (vw - W * scale) / 2, y: (vh - H * scale) / 2 };
}

/* THE MINIMUM TYPE SIZE on a small screen: a toast title never renders under 20 px, a line
   under 13 px, the button under 36 px tall. Returned in STAGE units for a safe box at scale
   `su`, so the pages' own sizes stand wherever the box is big enough -- at 1920 x 1080 this
   answers exactly the page's 42 / 20 / 46 and a factor of 1. */
export const MIN_TYPE = { title: 20, line: 13, button: 36 };
export function minType(su) {
  const s = su > 0 ? su : 1;
  return {
    title: Math.max(42, MIN_TYPE.title / s),
    line: Math.max(20, MIN_TYPE.line / s),
    caption: Math.max(30, MIN_TYPE.line / s),
    button: Math.max(1, MIN_TYPE.button / (46 * s)),   // a factor on the whole button
  };
}

/* REDUCED MOTION AND NO VIDEO (review amendment 11). No playback: the clip -- when there is
   one -- is paused on ONE still, and the overlay is drawn at its SETTLED state, which is a
   different time from the still's. No flare, no stars, no keycap animation. It lasts the
   moment's own length and ends early on Esc or a click like any other moment.
     starfall  still: arms raised (Cast + .5)   overlay: the toast settled (Cast + 2.1)
     keyturn   still: the library (Inside + 1)  overlay: final toast and button (Inside + 1.5) */
export const STILL = {
  starfall: { still: (c) => c.Cast + 0.5, overlay: (c) => c.Cast + 2.1 },
  keyturn: { still: (c) => c.Inside + 1, overlay: (c) => c.Inside + 1.5 },
};

/* The moment kinds the roster can name (the sealed `moment` flag). Anything else is not a
   clip moment and plays no stage. */
export const MOMENT_KINDS = Object.keys(SCENES);

/* How long a moment waits for its clip to be ready to play through before it gives up on
   the video and plays its no-video fallback instead (the same ceiling the key-sequence
   trigger already had for a beacon that never answers). */
export const LOAD_CEILING_MS = 20000;
/* The skip, and the exit after a natural end: one short fade of the whole moment. */
export const FADE_OUT_MS = 300;
