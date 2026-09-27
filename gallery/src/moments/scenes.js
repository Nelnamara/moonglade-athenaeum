/* THE TWO MOMENTS' OVERLAYS, as pure functions of T -- ported number for number from their
   locked Design Handoff pages (the celebration-videos set in the private moonglade-internal
   repo, which this public file does not name more precisely than that).

   Each frame function answers "what is on the stage at time T": one plain style object per
   part, in the page's own values, or null where the page renders nothing. ClipMoment.jsx
   only maps these onto elements, so every number the parity pass measures is decided here,
   and loom/test/moment-stage.test.js pins them without a browser.

   Two adaptations, both named, neither a number:
     1. COLOURS are the moment's own tokens (styles/moments.css: --moment-lav and friends),
        defined once from the root palette's values on the moment's root. The pages write the
        same hexes as literals; the app's skins remap --lavender/--emerald, and a celebration
        keeps the design's colours in every skin (owner, 2026-09-26). The rgba() glows and
        glass stay literal, as on the pages.
     2. THE UI LAYER'S MINIMUM TYPE (review amendment 4): `mt` (momentCore.minType) raises a
        toast title, a line, the caption and the button to a readable size in a small safe
        box. At 1920 x 1080 it is exactly the page's 42 / 20 / 30 / 46, so the parity frames
        are untouched.

   No sentence lives here. The toast, caption and button copy is `copy` -- moment_copy from
   /api/achievements, sealed in the pack and present only once the feat is earned. */
import { CLIP_DUR, H, LEAD, MOTION, W, clamp, interpolate, Easing, minType } from "./momentCore.js";

export const TOKENS = {
  lav: "var(--moment-lav)", em: "var(--moment-em)", loom: "var(--moment-loom)",
  text: "var(--moment-text)", sub: "var(--moment-sub)", sfSub: "var(--moment-sub-sf)",
  s0: "var(--moment-s0)", s1: "var(--moment-s1)", ov: "var(--moment-ov)",
  ink: "var(--moment-ink)", white: "var(--moment-white)",
};
const T_ = TOKENS;

export const SANS = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
const SERIF = "Georgia, serif";
const MONO = "ui-monospace, monospace";

/* The page's piece-level fade: up from black over the lead-in, down to black at the end
   (the last .6 s for the starfall, the last .5 s for the key turn). */
export const FADE_OUT = { starfall: 0.6, keyturn: 0.5 };
export function pieceFade(T, total, outLen) {
  const fadeIn = MOTION.enter({ from: 0, to: 1, start: 0, end: LEAD + 0.4 })(T);
  const fadeOut = MOTION.enter({ from: 1, to: 0, start: total - outLen, end: total })(T);
  return fadeIn * fadeOut;
}

/* The shared flash shape of both flares: a fast rise over the first 18% of its run, then a
   long fall. */
function flareAlpha(k) {
  return k < 0.18 ? k / 0.18 : 1 - (k - 0.18) / 0.82;
}

// ---- the frost-in toast, shared ------------------------------------------------------------
function toastBox(vis, border, glow, mt) {
  return {
    position: "absolute", left: 960, bottom: 56,
    transform: `translate(-50%, 0) scale(${0.96 + 0.04 * vis})`,
    opacity: vis, filter: `blur(${(1 - vis) * 14}px)`,
    background: "rgba(10,8,24,.84)", backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)",
    border: `1px solid ${border}`, borderRadius: 18, padding: "26px 52px 24px",
    textAlign: "center", boxShadow: glow, minWidth: 620,
  };
}
function toastTitle(mt) {
  return { fontFamily: SERIF, fontStyle: "italic", fontSize: mt.title, color: T_.white, lineHeight: 1.1 };
}
function toastLine(color, mt) {
  return { fontSize: mt.line, color, marginTop: 10 };
}

// =============================================================================================
// STARFALL -- the clip is the spine; keycaps, the cast flare, falling stars and the toast
// ride on top.
// =============================================================================================
export const CASTPT = { x: 960, y: 250 };   // her raised hands at the cast
export const CODE = ["↑", "↑", "↓", "↓", "←", "→", "←", "→", "B", "A"];

/* The page's seeded star field: 110 stars, deterministic, so both sides of the parity pass
   rain the same stars in the same places. */
const seeded = (i, k) => { const x = Math.sin(i * 127.1 + k * 311.7) * 43758.5453; return x - Math.floor(x); };
export const STARS = Array.from({ length: 110 }, (_, i) => ({
  x: seeded(i, 1) * W, d: seeded(i, 2) * 5.2, dur: 1.8 + seeded(i, 3) * 2.4,
  sz: 12 + seeded(i, 4) * 30, drift: -60 + seeded(i, 5) * 120,
}));

export function starfallFrame(T, cues, total, opts = {}) {
  const { still = false, clipT = T, su = 1, greeting = "", line = "" } = opts;
  const mt = minType(su);
  const push = interpolate([0, CLIP_DUR + LEAD], [1, 1.07], Easing.linear)(clipT);
  const f = {
    fade: pieceFade(T, total, FADE_OUT.starfall),
    clip: {
      position: "absolute", left: 0, top: 0, width: W, height: H, objectFit: "cover",
      transform: `scale(${push})`, transformOrigin: "50% 40%",
    },
    gradient: {
      position: "absolute", left: 0, top: 0, right: 0, bottom: 0, pointerEvents: "none",
      background: "linear-gradient(180deg, rgba(5,4,13,.6) 0%, rgba(5,4,13,0) 18%, rgba(5,4,13,0) 74%, rgba(5,4,13,.85) 100%)",
    },
    castflare: null, stars: [], keys: null, toast: null,
  };

  // Cast flare: a white-lavender screen wash plus a bloom at her hands.
  const k = clamp((T - (cues.Cast + 0.9)) / 1.3, 0, 1);
  if (!still && k > 0 && k < 1) {
    const a = flareAlpha(k);
    f.castflare = {
      wash: { position: "absolute", left: 0, top: 0, right: 0, bottom: 0, background: "rgba(226,214,255,1)", opacity: a * 0.3, mixBlendMode: "screen" },
      bloom: {
        position: "absolute", left: CASTPT.x - 520, top: CASTPT.y - 520, width: 1040, height: 1040,
        borderRadius: "50%", opacity: a, mixBlendMode: "screen",
        background: "radial-gradient(circle, rgba(236,226,255,.95) 0%, rgba(182,146,230,.4) 24%, rgba(0,0,0,0) 60%)",
      },
    };
  }

  // The star rain, from Cast + 1.1, staggered over ~5 s so it keeps raining through the hold.
  const t0 = cues.Cast + 1.1;
  if (!still && T >= t0) {
    STARS.forEach((s, i) => {
      const kk = (T - t0 - s.d) / s.dur;
      if (kk <= 0 || kk >= 1) return;
      const y = -60 + kk * (H + 120), x = s.x + s.drift * kk;
      const op = kk < 0.1 ? kk / 0.1 : kk > 0.85 ? (1 - kk) / 0.15 : 1;
      f.stars.push({
        i,
        style: {
          position: "absolute", left: x, top: y, fontSize: s.sz, color: T_.lav, opacity: op,
          transform: `rotate(${kk * 200}deg)`,
          textShadow: "0 0 14px rgba(182,146,230,.9), 0 0 30px rgba(182,146,230,.5)",
        },
      });
    });
  }

  // The keycaps pop and light one by one, then fade as she turns. No text names them.
  const out = MOTION.enter({ from: 1, to: 0, start: cues.Turn - 0.1, end: cues.Turn + 0.5 })(T);
  if (out > 0) {
    f.keys = {
      row: { position: "absolute", left: 0, right: 0, top: 120, display: "flex", justifyContent: "center", gap: 12, opacity: out },
      caps: CODE.map((label, i) => {
        const at = LEAD + 0.15 + i * 0.2;
        const p = still ? 1 : MOTION.pop({ from: 0, to: 1, start: at, end: at + 0.35 })(T);
        const lit = still || T >= at + 0.1;
        return {
          label,
          style: {
            width: 64, height: 64, borderRadius: 12, display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: MONO, fontSize: 28, fontWeight: 600, color: lit ? T_.white : T_.sfSub,
            background: "rgba(10,8,24,.78)", backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)",
            border: `1px solid ${lit ? T_.lav : T_.s1}`,
            boxShadow: lit ? "0 0 22px rgba(182,146,230,.55)" : "none",
            opacity: p, transform: `translateY(${(1 - p) * 18}px) scale(${0.7 + 0.3 * p})`,
          },
        };
      }),
    };
  }

  // The toast frosts in from Cast + 1.4. The greeting is public; the line is sealed copy.
  const vis = MOTION.enter({ from: 0, to: 1, start: cues.Cast + 1.4, end: cues.Cast + 2.1 })(T);
  f.toast = {
    box: toastBox(vis, T_.lav, "0 0 80px rgba(182,146,230,.45)", mt),
    title: toastTitle(mt), line: toastLine(T_.sfSub, mt),
    titleText: greeting, lineText: line,
  };
  return f;
}

// =============================================================================================
// THE KEY TURN -- the clip is the spine; the Control Panel rail's unlock and the toast ride
// on top. The rail carries the REAL Control Panel tabs (the handoff's note: its General /
// Appearance / Account rows were a stand-in), keeping the page's geometry and its
// Locked -> Branding row.
// =============================================================================================
export const DOORPT = { x: 960, y: 520 };   // the rune door's centre
export const RAIL = { right: 56, top: 150, w: 360 };
export const UTH_BAND = 837;                // the clip's letterboxed height on the stage

export function keyturnFrame(T, cues, total, opts = {}) {
  const { still = false, clipT = T, su = 1, copy = {} } = opts;
  const mt = minType(su);
  const push = interpolate([0, CLIP_DUR + LEAD], [1, 1.09], Easing.linear)(clipT);
  const f = {
    fade: pieceFade(T, total, FADE_OUT.keyturn),
    clip: {
      position: "absolute", left: 0, top: (H - UTH_BAND) / 2, width: W, height: UTH_BAND, objectFit: "cover",
      transform: `scale(${push})`, transformOrigin: "50% 50%",
    },
    gradient: {
      position: "absolute", left: 0, top: 0, right: 0, bottom: 0, pointerEvents: "none",
      background: "linear-gradient(180deg, rgba(5,4,13,.85) 0%, rgba(5,4,13,0) 16%, rgba(5,4,13,0) 78%, rgba(5,4,13,.9) 100%)",
    },
    doorflare: null, rail: null, toast: null, caption: null,
  };

  // The door-open flare: a warm screen flash plus a radial bloom at the rune door.
  const k = clamp((T - (cues.Door + 1.1)) / 1.4, 0, 1);
  if (!still && k > 0 && k < 1) {
    const a = flareAlpha(k);
    f.doorflare = {
      wash: { position: "absolute", left: 0, top: 0, right: 0, bottom: 0, background: "rgba(255,240,214,1)", opacity: a * 0.35, mixBlendMode: "screen" },
      bloom: {
        position: "absolute", left: DOORPT.x - 500, top: DOORPT.y - 500, width: 1000, height: 1000,
        borderRadius: "50%", opacity: a, mixBlendMode: "screen",
        background: "radial-gradient(circle, rgba(255,220,170,.9) 0%, rgba(255,190,120,.35) 25%, rgba(0,0,0,0) 60%)",
      },
    };
  }

  // The rail: slides in, the lock pops, the Branding row slides in over the locked slot.
  const show = MOTION.enter({ from: 0, to: 1, start: cues.Door + 0.2, end: cues.Door + 0.9 })(T);
  const open = MOTION.pop({ from: 0, to: 1, start: cues.Door + 2.3, end: cues.Door + 2.75 })(T);
  const slide = MOTION.enter({ from: 0, to: 1, start: cues.Door + 2.65, end: cues.Door + 3.3 })(T);
  const glow = 0.5 + 0.5 * Math.sin(T * 3);
  const tab = (active) => ({
    row: {
      display: "flex", alignItems: "center", gap: 12, height: 54, padding: "0 18px", borderRadius: 12, fontSize: 20,
      color: active ? T_.text : T_.sub, background: active ? T_.s0 : "transparent",
      border: `1px solid ${active ? T_.s1 : "transparent"}`,
    },
    dot: { width: 10, height: 10, borderRadius: "50%", background: active ? T_.lav : T_.ov },
  });
  f.rail = {
    box: {
      position: "absolute", right: RAIL.right, top: RAIL.top, width: RAIL.w, opacity: show,
      transform: `translateX(${(1 - show) * 30}px)`, background: "rgba(10,8,24,.86)",
      backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)",
      border: `1px solid ${T_.s1}`, borderRadius: 20, padding: 24, boxSizing: "border-box",
    },
    heading: { fontFamily: SERIF, fontStyle: "italic", fontSize: 26, color: T_.text, marginBottom: 6 },
    sub: { fontSize: 16, color: T_.sub, marginBottom: 16 },
    list: { display: "flex", flexDirection: "column", gap: 8 },
    tab,
    lockRow: { position: "relative", height: 54, display: "flex", alignItems: "center", padding: "0 18px", gap: 12 },
    lock: { position: "relative", width: 22, height: 26, opacity: 1 - slide, flex: "none", transform: "scale(1.25)" },
    shackle: {
      position: "absolute", left: 3, top: 0, width: 16, height: 14, border: `3px solid ${T_.ov}`, borderBottom: "none",
      borderRadius: "8px 8px 0 0", boxSizing: "border-box", transformOrigin: "100% 100%",
      transform: `translateY(${-6 * open}px) rotate(${-28 * open}deg)`,
    },
    body: {
      position: "absolute", left: 0, top: 11, width: 22, height: 15, borderRadius: 4,
      background: open > 0 ? T_.em : T_.ov, boxShadow: `0 0 ${14 * open}px ${T_.em}`,
    },
    locked: { fontSize: 19, color: T_.ov, opacity: 1 - slide },
    branding: {
      position: "absolute", left: 0, top: 0, right: 0, height: 54, display: "flex", alignItems: "center", gap: 12,
      padding: "0 18px", borderRadius: 12, fontSize: 20, color: T_.loom, background: "rgba(71,203,195,.12)",
      border: `1px solid ${T_.loom}`, boxShadow: `0 0 ${(14 + 12 * glow) * slide}px rgba(71,203,195,.45)`,
      opacity: slide, transform: `translateX(${(1 - slide) * 50}px)`, boxSizing: "border-box", whiteSpace: "nowrap",
    },
    brandingDot: { width: 10, height: 10, borderRadius: "50%", background: T_.loom },
    fresh: { marginLeft: "auto", fontSize: 14, letterSpacing: ".08em", textTransform: "uppercase", color: T_.em, opacity: slide },
  };

  // The toast: rises with the key, dips for the flight, returns inside with its second copy
  // and the button.
  const rise = MOTION.enter({ from: 0, to: 1, start: cues.Key + 1.9, end: cues.Key + 2.6 })(T);
  const dip = MOTION.enter({ from: 1, to: 0, start: cues.Flight + 0.1, end: cues.Flight + 0.7 })(T);
  const back = MOTION.enter({ from: 0, to: 1, start: cues.Inside + 0.3, end: cues.Inside + 0.9 })(T);
  const offer = MOTION.pop({ from: 0, to: 1, start: cues.Inside + 0.9, end: cues.Inside + 1.5 })(T);
  const vis = rise * Math.max(dip, back);
  const inside = back > 0.5;
  const b = mt.button;
  f.toast = {
    box: toastBox(vis, T_.em, "0 0 80px rgba(79,201,154,.35)", mt),
    title: toastTitle(mt), line: toastLine(T_.sub, mt),
    titleText: inside ? copy.title2 || "" : copy.title1 || "",
    lineText: inside ? copy.line2 || "" : copy.line1 || "",
    offer,
    offerWrap: { height: (18 + 46 * b) * offer, overflow: "hidden", marginTop: 4 * offer },
    button: {
      display: "inline-flex", alignItems: "center", gap: 10 * b, marginTop: 14, height: 46 * b, padding: `0 ${26 * b}px`,
      borderRadius: 23 * b, background: T_.lav, color: T_.ink, fontSize: 18 * b, fontWeight: 600,
      transform: `scale(${Math.max(offer, 0.01)})`, boxShadow: "0 6px 24px rgba(182,146,230,.4)",
    },
    arrow: { fontSize: 20 * b },
    buttonText: buttonLabel(copy.button),
  };

  // The one caption, from Door + .4 until the library, with the page engine's .18 s fade.
  f.caption = caption(T, cues.Door + 0.4, cues.Inside, copy.caption || "", mt);
  return f;
}

/* The page draws the button as its label plus an arrow in its own span. The sealed label is
   taken as delivered, minus an arrow of its own if it carries one, so the arrow is drawn
   exactly once whichever way the pack writes it. */
export function buttonLabel(s) {
  return String(s || "").replace(/\s*→\s*$/, "");
}

/* The page engine's <Captions>: one element, visible from `at` until `until`, fading in and
   out over CAPTION_FADE. Null outside its window, as the page renders nothing there. */
export const CAPTION_FADE = 0.18;
export function caption(T, at, until, text, mt = minType(1)) {
  if (!text || T < at || T >= until) return null;
  let o = Math.min(1, (T - at) / CAPTION_FADE);
  o = Math.min(o, (until - T) / CAPTION_FADE);
  o = Math.max(0, Math.min(1, o));
  return {
    text,
    style: {
      position: "absolute", left: "8%", right: "8%", bottom: "7%", textAlign: "center", opacity: o,
      pointerEvents: "none", fontFamily: "Inter, system-ui, sans-serif", fontWeight: 500, fontSize: mt.caption,
      color: "var(--moment-caption)", textShadow: "0 1px 14px rgba(0,0,0,0.45)",
    },
  };
}
