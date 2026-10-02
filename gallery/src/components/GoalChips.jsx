import React, { useRef } from "react";
import useGoalChips from "../hooks/useGoalChips.js";
import MoonGauge from "./MoonGauge.jsx";
import { GAUGE_SIZES } from "../lib/moonGaugeCore.js";
import { swipedAway } from "../folio/goalCore.js";
import "../styles/goal-chips.css";

/* THE GOAL CHIPS (Session O, O4 + O5), drawn where the credits are: the desktop's separator bar
   (gallery and the Generate dock beneath it), the Loom's header, and -- as `phone` -- the row above
   the phone's tab bar. The Folio Completionists Handoff draws them:

     pinned goal   the moon on the true fraction, the honor's name and "N to go"; a click opens that
                   row in the Folio; the x unpins. The phone chip is 32 px high and is swiped away.
     Vigil         "Vigil . day N", only when the account turned the switch on in the Folio's header.

   Everything is decided by useGoalChips (the account's pin and switch, the numbers, the celebration
   band). This file draws and forwards clicks. Hidden while a celebration is on screen; renders
   nothing at all when there is neither chip to show. */

function MoonGlyph() {
  return (
    <svg className="mgg-glyph" width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M13.2 10.4A6 6 0 0 1 5.6 2.8a6 6 0 1 0 7.6 7.6z" />
    </svg>
  );
}

export function VigilChip({ vigil, className = "" }) {
  return (
    <span className={"mgg-vigil" + (className ? " " + className : "")} title="Days in a row with a generation">
      <MoonGlyph /> {vigil.text}
    </span>
  );
}

export function PinChip({ pin, onOpen, onUnpin, phone = false }) {
  const start = useRef(null);
  const swiped = useRef(false);
  const onKey = (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); }
    else if (phone && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); onUnpin(); }
  };
  // The phone's chip is swiped away: a drag that ends far enough, and mostly sideways, unpins.
  const down = (e) => {
    if (!phone) return;
    start.current = { x: e.clientX, y: e.clientY };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* the drag still ends on the chip */ }
  };
  const up = (e) => {
    const s = start.current;
    start.current = null;
    if (!s) return;
    if (swipedAway(e.clientX - s.x, e.clientY - s.y)) {
      swiped.current = true;      // the click that follows a swipe is not a tap on the chip
      onUnpin();
    }
  };
  const tap = () => { if (swiped.current) { swiped.current = false; return; } onOpen(); };
  return (
    <span className={"mgg-pin" + (phone ? " phone" : "")} role="button" tabIndex={0}
      title={"Open in the Folio" + (phone ? " · swipe to unpin" : "")}
      aria-label={pin.text + ". Open in the Folio" + (phone ? ". Swipe sideways to unpin." : ".")}
      onClick={tap} onKeyDown={onKey}
      onPointerDown={down} onPointerUp={up} onPointerCancel={() => { start.current = null; }}>
      <MoonGauge fraction={pin.fraction} size={GAUGE_SIZES.phone} bar={false} label={pin.name} />
      <span className="mgg-pin-t">{pin.text}</span>
      {!phone && (
        <button type="button" className="mgg-x" title="Unpin" aria-label={"Unpin " + pin.name}
          onClick={(e) => { e.stopPropagation(); onUnpin(); }}>{"✕"}</button>
      )}
    </span>
  );
}

export default function GoalChips({ phone = false }) {
  const g = useGoalChips();
  if (g.hidden || (!g.pin && !g.vigil)) return null;
  return (
    <div className={"mgg-chips" + (phone ? " phone" : "")} data-goal-chips>
      {g.pin && <PinChip pin={g.pin} onOpen={g.openPinned} onUnpin={g.unpin} phone={phone} />}
      {g.vigil && <VigilChip vigil={g.vigil} />}
    </div>
  );
}
