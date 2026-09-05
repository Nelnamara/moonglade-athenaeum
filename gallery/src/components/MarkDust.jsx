import React, { useEffect, useRef } from "react";

/* MOON DUST — the one canvas treatment on the roster (promoted from the Marks Board's
   live demo cell, which is why it is the only animation here that CSS cannot express:
   two pseudo-elements cannot be twenty-six independently drifting motes).

   The particle field is ported from the board's own implementation — same pool size,
   same seeded distribution, same orbit and twinkle math — so what the owner voted on is
   what runs. ONE adaptation, and it matters: the board drew its own stand-in crescent
   into the canvas because the demo had no real mark. Here the mark is real and sits
   above this canvas, so the stand-in is gone; drawing a second, fake moon behind
   somebody's actual mark would be a lie the board never intended.

   THE COST IS BOUNDED, deliberately:
   - one rAF for the component, cancelled on unmount;
   - a fixed pool built once, mutated in place — nothing is allocated per frame;
   - the loop STOPS when the tab is hidden (visibilitychange) rather than spinning
     invisibly, and restarts on return;
   - prefers-reduced-motion draws a single still frame and never loops at all. */

const COLORS = ["#b692e6", "#94e2d5", "#d4af37"];
const COUNT = 26;

/* The board's own seeded field: deterministic, so every install's dust is the same
   dust, and no RNG is called per frame (or at all). */
function buildField() {
  const out = [];
  for (let i = 0; i < COUNT; i++) {
    out.push({
      a: Math.PI * 2 * (i / COUNT),
      r: 34 + 18 * ((i * 7) % 13) / 13,
      s: 0.2 + ((i * 11) % 17) / 17 * 0.6,
      c: COLORS[i % 3],
      ph: (i * 5) % 10,
      sz: 0.7 + ((i * 13) % 7) / 7 * 1.3,
    });
  }
  return out;
}

export default function MarkDust({ size = 96, speed = 1 }) {
  const ref = useRef(null);
  const field = useRef(null);
  if (field.current === null) field.current = buildField();

  // The field orbits wider than the mark, so the canvas is bigger than the mark box
  // and centred on it. HOW MUCH bigger is a page-layout fact, not a taste one: the
  // hero mark sits 22px from the window edge (.mgx-navcol's right padding,
  // shell.css) and nothing clips the spill (.mgx-bnr is overflow:visible for the
  // halo), so at the old 2.4x the canvas widened the DOCUMENT by ~30px and the page
  // grew a permanent horizontal scrollbar. Owner ruling 2026-09-04: shrink the
  // field. 1.45x overhangs the mark by 0.225x a side -- 21.6px at hero, inside the
  // 22px budget -- and the orbit radius below is fitted to the box, so motes drift
  // tighter rather than clipping at the new edge. The containment test pins both.
  const box = Math.round(size * 1.45);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return undefined;
    const ctx = cv.getContext("2d");
    if (!ctx) return undefined;

    const dpr = Math.min(2, (typeof window !== "undefined" && window.devicePixelRatio) || 1);
    cv.width = Math.round(box * dpr);
    cv.height = Math.round(box * dpr);
    ctx.scale(dpr, dpr);

    const P = field.current;
    // The board's own radius rule, then clamped so the WIDEST orbit fits the box:
    // draw() reaches x = (p.r/34)*R*1.35*1.25 + wobble(3)*1.25 + the mote's own
    // radius. Solving that for R against box/2 (6px covers wobble + the largest
    // mote) keeps every mote inside the shrunken canvas instead of popping out at
    // its edge -- the field scales down with the field's new bounds.
    const maxOrbit = Math.max(...P.map((p) => p.r)) / 34;
    const R = Math.min(Math.max(20, size * 0.32),
                       (box / 2 - 6) / (maxOrbit * 1.35 * 1.25));
    const cx = box / 2;
    const cy = box / 2;
    let t = 0;
    let raf = 0;

    const draw = () => {
      ctx.clearRect(0, 0, box, box);
      for (let i = 0; i < P.length; i++) {
        const p = P[i];
        const ang = p.a + t * p.s;
        const rr = (p.r / 34) * R * 1.35 + Math.sin(t * 1.3 + p.ph) * 3;
        const x = cx + Math.cos(ang) * rr * 1.25;
        const y = cy + Math.sin(ang) * rr * 0.8;
        const tw = 0.45 + 0.55 * Math.abs(Math.sin(t * 2 + p.ph));
        ctx.globalAlpha = tw * 0.9;
        ctx.fillStyle = p.c;
        ctx.beginPath();
        ctx.arc(x, y, p.sz * (R / 30), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    let still = false;
    try {
      still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch { /* no matchMedia: animate, same as any other treatment */ }

    if (still) { draw(); return undefined; }    // one frame, no loop

    const frame = () => {
      t += 0.016 * (Number(speed) || 1);
      draw();
      raf = requestAnimationFrame(frame);
    };
    const start = () => { if (!raf) raf = requestAnimationFrame(frame); };
    const stop = () => { if (raf) { cancelAnimationFrame(raf); raf = 0; } };
    const onVis = () => (document.hidden ? stop() : start());

    start();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [box, size, speed]);

  return <canvas className="mgx-mark-dust" ref={ref} aria-hidden="true"
    style={{ width: box + "px", height: box + "px" }} />;
}
