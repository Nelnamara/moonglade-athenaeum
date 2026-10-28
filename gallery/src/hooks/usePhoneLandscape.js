import { useEffect, useState } from "react";
import { LANDSCAPE_QUERY, TURN_SETTLE_MS, TURN_NUDGE_MS, phoneColumns, isChromeIOS, nudgeTarget } from "../lib/phoneCore.js";

/* Is the phone held sideways, and how many columns does its gallery draw? (Session Q, Q4.)

   Live, like hooks/useIsMobile.js: it follows the media query, resize and orientationchange, so a
   turn re-flows the columns on the spot. The query is lib/phoneCore.js's LANDSCAPE_QUERY -- the same
   condition phone-landscape.css is written under, so the columns and the CSS rail cannot disagree.
   It reads only; nothing here writes anywhere.

   AND AGAIN ONCE THE TURN HAS SETTLED (owner's walk, 2026-10-03): a phone can deliver a turn's events
   while the query still answers for the old way up, and fire nothing afterwards, which left the
   sideways column count on an upright phone. Every event also reads on the next frame and at
   TURN_SETTLE_MS; the visual viewport's resize (what a phone fires when its toolbars settle) counts.

   AND, ON CHROME FOR iOS ONLY, A ONE-PIXEL SCROLL ONCE A TURN HAS SETTLED (#75): Chrome on iOS can keep
   the sideways layout width after the phone turns back upright, and corrects itself on the first
   scroll. At TURN_NUDGE_MS after the turn, and only when the phone really changed way up, each of the
   gallery's scrollers moves one pixel and back on the next frame. See lib/phoneCore.js. */

function read() {
  if (typeof window === "undefined" || !window.matchMedia) return { landscape: false, cols: 2 };
  const landscape = window.matchMedia(LANDSCAPE_QUERY).matches;
  return { landscape, cols: phoneColumns(window.innerWidth, landscape) };
}

export default function usePhoneLandscape() {
  const [st, setSt] = useState(read);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const sync = () => setSt((old) => {
      const next = read();
      return old.landscape === next.landscape && old.cols === next.cols ? old : next;
    });
    let raf = 0;
    let timers = [];
    const chromeIOS = isChromeIOS(window.navigator && window.navigator.userAgent);
    let nudgedFor = window.matchMedia(LANDSCAPE_QUERY).matches;
    // ?turndebug: a live readout of the widths that matter, for a turn on a real phone (#75). Plain DOM,
    // no state: it only reads, and it leaves with the gallery.
    let debugTimer = 0, debugEl = null, nudges = 0;
    if (/[?&]turndebug\b/.test(window.location.search || "")) {
      debugEl = document.createElement("pre");
      debugEl.style.cssText = "position:fixed;left:6px;bottom:6px;z-index:99999;margin:0;padding:6px 8px;"
        + "font:11px/1.35 ui-monospace,monospace;color:#fff;background:rgba(0,0,0,.78);border-radius:6px;"
        + "pointer-events:none;white-space:pre";
      document.body.appendChild(debugEl);
      const w = (sel) => { const el = document.querySelector(sel); return el ? Math.round(el.getBoundingClientRect().width) : "-"; };
      debugTimer = setInterval(() => {
        const de = document.documentElement, vv = window.visualViewport, grid = document.querySelector(".glm-grid");
        debugEl.textContent = [
          "inner " + window.innerWidth + "  vv " + (vv ? Math.round(vv.width) : "-") + "  client " + de.clientWidth + "  scroll " + de.scrollWidth,
          "stage " + w(".glm-stage") + "  body " + w(".glm-body") + "  grid " + w(".glm-grid"),
          "cols " + (grid ? getComputedStyle(grid).gridTemplateColumns : "-"),
          "landscape " + window.matchMedia(LANDSCAPE_QUERY).matches + "  chromeIOS " + chromeIOS + "  nudges " + nudges,
        ].join("\n");
      }, 300);
    }
    const nudge = () => {
      const now = window.matchMedia(LANDSCAPE_QUERY).matches;
      if (now === nudgedFor) return;          // the phone did not change way up: nothing to correct
      nudgedFor = now;
      nudges += 1;
      document.querySelectorAll(".glm-body").forEach((el) => {
        const was = el.scrollTop;
        el.scrollTop = nudgeTarget(was);
        requestAnimationFrame(() => { el.scrollTop = was; });
      });
    };
    const settle = () => {
      sync();
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { raf = 0; sync(); });
      timers.forEach(clearTimeout);
      timers = TURN_SETTLE_MS.map((ms) => setTimeout(sync, ms));
      if (chromeIOS) timers.push(setTimeout(nudge, TURN_NUDGE_MS));
    };
    sync();
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
      if (debugTimer) clearInterval(debugTimer);
      if (debugEl) debugEl.remove();
      timers.forEach(clearTimeout);
    };
  }, []);
  return st;
}
