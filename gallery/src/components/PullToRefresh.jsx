import React, { useEffect, useRef, useState } from "react";
import MoonGauge from "./MoonGauge.jsx";
import {
  PULL_HOLD, pullArmed, pullDistance, pullFraction, pullLabel, pullMayStart,
} from "../lib/phoneCore.js";
import "../styles/phone-q.css";

/* Pull to refresh (Session Q, Q6; Phone Handoff.dc.html, the gallery's pull moon).

   WHAT IT IS. A thin wrapper around a phone screen's content. Pull down at the very top of the scroller
   and the moon fills with the pull -- a TRUE fraction, the distance travelled over the 72 px release
   line (DECISIONS: the moon gauge fills only on a true fraction) -- and letting go past the line runs
   `onRefresh`, which resolves when it is done; the moon spins meanwhile and the page rests one notch
   down. Below the line, letting go does nothing at all.

   WHAT IT NEVER DOES. It does not own what refresh means (the caller does: the gallery's is the same
   "Sync now" job the Control tab runs, My Art's is a re-read of the list), it writes nothing of its own,
   and it does not start while the scroller is off the top or while a refresh is already running. A pull
   is an explicit request, so it works under Data saver.

   THE SCROLLER is found, not passed: the nearest .glm-screen-body (a pushed screen such as My Art) or
   .glm-body (a tab), the two real scrollers this shell has. `overscroll-behavior-y: contain` on .glm-body
   (gallery-mobile.css) keeps the browser's own pull-to-reload out of the way, and the touch move is
   cancelled here while a pull is being tracked so the page does not also rubber-band.

   INPUT. Touch (the phone) and a mouse drag (a narrow desktop window, and how the tests drive it): the
   same gesture, the same numbers (lib/phoneCore.js). A gesture that starts by moving up or sideways is
   left to the browser to scroll. */

const SCROLLERS = ".glm-screen-body, .glm-body";

export default function PullToRefresh({ onRefresh, enabled = true, labels, className = "", children }) {
  const root = useRef(null);
  const [px, setPx] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const live = useRef({ enabled, syncing: false, onRefresh, px: 0 });
  live.current.enabled = enabled;
  live.current.onRefresh = onRefresh;

  useEffect(() => {
    const el = root.current;
    const host = el && el.closest(SCROLLERS);
    if (!host) return undefined;
    let g = null;                        // the gesture in flight: {x0, y0, mode: "?" | "pull"}
    let mouseOn = false;

    const set = (v) => { live.current.px = v; setPx(v); };
    const finish = async () => {
      live.current.syncing = true;
      setSyncing(true);
      setDragging(false);
      try {
        if (typeof live.current.onRefresh === "function") await live.current.onRefresh();
      } catch { /* the caller reports its own failure; the pull just ends */ }
      live.current.syncing = false;
      setSyncing(false);
      set(0);
    };
    const start = (x, y, target) => {
      if (!live.current.enabled || !pullMayStart(host.scrollTop, live.current.syncing)) return;
      // Only a touch that lands on THIS content pulls it. A pushed screen (My Art) and a bottom sheet
      // both sit inside the tab's scroller in the DOM, so their touches bubble up to it -- and neither
      // is the thing being refreshed. (The sheets are rendered outside the wrapper for this reason.)
      if (!target || !el.contains(target)) return;
      g = { x0: x, y0: y, mode: "?" };
    };
    const move = (x, y, ev) => {
      if (!g) return;
      const dy = y - g.y0, dx = x - g.x0;
      if (g.mode === "?") {
        if (Math.abs(dy) < 6 && Math.abs(dx) < 6) return;
        if (dy > 0 && Math.abs(dy) > Math.abs(dx)) { g.mode = "pull"; setDragging(true); }
        else { g = null; return; }       // up or sideways: the browser's to scroll
      }
      if (host.scrollTop > 0) { g = null; setDragging(false); set(0); return; }
      if (ev && ev.cancelable) ev.preventDefault();
      set(pullDistance(dy));
    };
    const end = () => {
      if (!g) return;
      const pulled = g.mode === "pull";
      g = null;
      if (!pulled) return;
      if (pullArmed(live.current.px)) finish();
      else { setDragging(false); set(0); }
    };

    const tStart = (e) => { const t = e.touches[0]; if (t && e.touches.length === 1) start(t.clientX, t.clientY, e.target); };
    const tMove = (e) => { const t = e.touches[0]; if (t) move(t.clientX, t.clientY, e); };
    const tEnd = () => end();
    const mDown = (e) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      start(e.clientX, e.clientY, e.target);
      mouseOn = !!g;
    };
    const mMove = (e) => { if (mouseOn && e.pointerType === "mouse") move(e.clientX, e.clientY, e); };
    const mUp = (e) => { if (mouseOn && e.pointerType === "mouse") { mouseOn = false; end(); } };

    host.addEventListener("touchstart", tStart, { passive: true });
    host.addEventListener("touchmove", tMove, { passive: false });
    host.addEventListener("touchend", tEnd, { passive: true });
    host.addEventListener("touchcancel", tEnd, { passive: true });
    host.addEventListener("pointerdown", mDown);
    window.addEventListener("pointermove", mMove);
    window.addEventListener("pointerup", mUp);
    window.addEventListener("pointercancel", mUp);
    return () => {
      host.removeEventListener("touchstart", tStart);
      host.removeEventListener("touchmove", tMove);
      host.removeEventListener("touchend", tEnd);
      host.removeEventListener("touchcancel", tEnd);
      host.removeEventListener("pointerdown", mDown);
      window.removeEventListener("pointermove", mMove);
      window.removeEventListener("pointerup", mUp);
      window.removeEventListener("pointercancel", mUp);
    };
  }, []);

  const shown = syncing ? PULL_HOLD : px;
  const fraction = syncing ? 1 : pullFraction(px);
  const text = (labels && (syncing ? labels.busy : pullArmed(px) ? labels.armed : labels.idle))
    || pullLabel({ syncing, px });
  const active = syncing || px > 0;
  return (
    <div ref={root} className={"ptr" + (syncing ? " syncing" : "") + (className ? " " + className : "")}>
      <div className="ptr-ind" style={{ opacity: active ? (syncing ? 1 : Math.max(.15, fraction)) : 0 }}
        role="status" aria-live="polite">
        <MoonGauge fraction={active ? fraction : null} size={18} bar={false} className="ptr-moon"
          label="Pull to refresh" />
        <span className="ptr-txt">{active ? text : ""}</span>
      </div>
      <div className="ptr-body"
        style={{
          transform: shown > 0 ? "translateY(" + shown + "px)" : undefined,
          transition: dragging ? "none" : "transform .25s ease",
        }}>
        {children}
      </div>
    </div>
  );
}
