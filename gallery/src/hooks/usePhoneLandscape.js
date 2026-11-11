import { useEffect, useState } from "react";
import { LANDSCAPE_QUERY, TURN_SETTLE_MS, phoneColumns, sidesKept } from "../lib/phoneCore.js";

/* Is the phone held sideways, and how many columns does its gallery draw? (Session Q, Q4.)

   Live, like hooks/useIsMobile.js: it follows the media query, resize and orientationchange, so a
   turn re-flows the columns on the spot. The query is lib/phoneCore.js's LANDSCAPE_QUERY -- the same
   condition phone-landscape.css is written under, so the columns and the CSS rail cannot disagree.
   It reads, and writes two attributes on <html> (#73): data-mg-sides-kept -- present while the browser
   has already kept the side room the safe areas ask for (lib/phoneCore.js's sidesKept, decided from the
   window's shape), so phone-landscape.css counts the side safe areas once -- and, for 700 ms after that
   state flips while the phone was ALREADY sideways (a late correction), data-mg-slide, which lets the
   css slide the change instead of jumping. Set and cleared with the turn; nothing is stored, and the
   attributes and the probe element leave with the gallery.

   AND AGAIN ONCE THE TURN HAS SETTLED (owner's walk, 2026-10-03): a phone can deliver a turn's events
   while the query still answers for the old way up, and fire nothing afterwards, which left the
   sideways column count on an upright phone. Every event also reads on the next frame and at
   TURN_SETTLE_MS; the visual viewport's resize (what a phone fires when its toolbars settle) counts.

   ?turndebug adds a live readout of the widths that matter after a turn (#75): the viewport as the
   browser reports it, the gallery's stage, scroller and grid, and the grid's resolved tracks. It is how
   #75 was found on a real iPhone in Chrome (the tracks, not the viewport, kept the sideways width; the
   fix is in gallery-mobile.css). It also shows the four safe areas, the screen and whether the sides count
   as kept (#73), so a real phone answers "does this browser report an inset it already made room for?" in
   one look. Plain DOM, no state: it only reads, and it leaves with the gallery. */

/* The phone shell mounts this hook in more than one place (the app, the gallery, the Lightbox); the
   attribute they all write is the same, and it comes off only when the last of them goes. */
let live = 0;

function read() {
  if (typeof window === "undefined" || !window.matchMedia) return { landscape: false, cols: 2 };
  const landscape = window.matchMedia(LANDSCAPE_QUERY).matches;
  return { landscape, cols: phoneColumns(window.innerWidth, landscape) };
}

function startTurnDebug(safe) {
  const box = document.createElement("pre");
  box.style.cssText = "position:fixed;left:6px;bottom:6px;z-index:99999;margin:0;padding:6px 8px;"
    + "font:11px/1.35 ui-monospace,monospace;color:#fff;background:rgba(0,0,0,.78);border-radius:6px;"
    + "pointer-events:none;white-space:pre";
  document.body.appendChild(box);
  const w = (sel) => { const el = document.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().width) : "-"; };
  const timer = setInterval(() => {
    const de = document.documentElement, vv = window.visualViewport, grid = document.querySelector(".glm-grid");
    const sf = safe();
    box.textContent = [
      "inner " + window.innerWidth + "  vv " + (vv ? Math.round(vv.width) : "-") + "  client " + de.clientWidth + "  scroll " + de.scrollWidth,
      "stage " + w(".glm-stage") + "  body " + w(".glm-body") + "  grid " + w(".glm-grid"),
      "cols " + (grid ? getComputedStyle(grid).gridTemplateColumns : "-"),
      "landscape " + window.matchMedia(LANDSCAPE_QUERY).matches,
      "safe L T R B " + sf.l + " " + sf.t + " " + sf.r + " " + sf.b + "  screen " + screen.width + "x" + screen.height
        + "  sides kept " + (sf.kept ? "yes" : "no"),
    ].join("\n");
  }, 300);
  return () => { clearInterval(timer); box.remove(); };
}

export default function usePhoneLandscape() {
  const [st, setSt] = useState(read);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    /* The four env() insets, read from one hidden probe made once (CSS cannot hand them to script any
       other way). Where env() is unsupported the padding resolves to 0 and nothing is ever "kept". */
    const probe = document.createElement("div");
    probe.setAttribute("aria-hidden", "true");
    probe.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;visibility:hidden;pointer-events:none;"
      + "padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)";
    document.body.appendChild(probe);
    const de = document.documentElement;
    live += 1;
    let safe = { t: 0, r: 0, b: 0, l: 0, kept: false };
    let wasLandscape = false;
    let slideTimer = 0;
    const readSafe = () => {
      const cs = getComputedStyle(probe);
      const px = (v) => Math.round(parseFloat(v) || 0);
      const l = px(cs.paddingLeft), r = px(cs.paddingRight);
      const landscape = read().landscape;
      const kept = sidesKept({ landscape, innerW: window.innerWidth,
        screenW: window.screen && window.screen.width, screenH: window.screen && window.screen.height, left: l, right: r });
      safe = { t: px(cs.paddingTop), r, b: px(cs.paddingBottom), l, kept };
      // A late correction -- the state flips while the phone was already sideways at the last read -- slides
      // over half a second (phone-landscape.css, :root[data-mg-slide]); the turn itself never does.
      if (wasLandscape && landscape && de.hasAttribute("data-mg-sides-kept") !== kept) {
        de.setAttribute("data-mg-slide", "");
        clearTimeout(slideTimer);
        slideTimer = setTimeout(() => de.removeAttribute("data-mg-slide"), 700);
      }
      wasLandscape = landscape;
      de.toggleAttribute("data-mg-sides-kept", kept);
    };
    const sync = () => {
      readSafe();
      setSt((old) => {
        const next = read();
        return old.landscape === next.landscape && old.cols === next.cols ? old : next;
      });
    };
    let raf = 0;
    let timers = [];
    const settle = () => {
      sync();
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { raf = 0; sync(); });
      timers.forEach(clearTimeout);
      timers = TURN_SETTLE_MS.map((ms) => setTimeout(sync, ms));
    };
    sync();
    const stopDebug = /[?&]turndebug\b/.test(window.location.search || "") ? startTurnDebug(() => safe) : null;
    const mql = window.matchMedia(LANDSCAPE_QUERY);
    const vv = window.visualViewport;
    if (mql.addEventListener) mql.addEventListener("change", settle); else if (mql.addListener) mql.addListener(settle);
    window.addEventListener("resize", settle);
    window.addEventListener("orientationchange", settle);
    if (vv) vv.addEventListener("resize", settle);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", settle); else if (mql.removeListener) mql.removeListener(settle);
      window.removeEventListener("resize", settle);
      window.removeEventListener("orientationchange", settle);
      if (vv) vv.removeEventListener("resize", settle);
      if (raf) cancelAnimationFrame(raf);
      if (stopDebug) stopDebug();
      probe.remove();
      clearTimeout(slideTimer);
      if (--live === 0) { de.removeAttribute("data-mg-sides-kept"); de.removeAttribute("data-mg-slide"); }
      timers.forEach(clearTimeout);
    };
  }, []);
  return st;
}
