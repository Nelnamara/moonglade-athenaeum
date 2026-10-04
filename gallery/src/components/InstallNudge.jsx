import React, { useEffect, useState } from "react";
import { STRIP_TEXT, bubbleText } from "../lib/installNudge.js";
import "../styles/phone-u.css";

/* The Home Screen nudge, drawn (Session U; Phone Paging and Nudge Handoff.dc.html sections 6 and 7). The
   rules are lib/installNudge.js's and the state hooks/useInstallNudge.js's; this only draws.

   NudgeStrip -- section 6: directly under the gallery's pill row, full width, 36 px: "Add to Home Screen
   for full screen ›" in lavender and a ✕ with a 44 px hit area. It pushes the grid down rather than
   covering it; it comes in over .42 s and goes over .34 s.

   NudgeBubble -- section 7, iOS Safari: a card pinned 12 px above Safari's toolbar, centred, with ▼ at
   the Share button below it; held sideways it pins 12 px under the top with ▲ instead. */

const EXIT_MS = 340;

export function NudgeStrip({ show, onOpen, onDismiss }) {
  const [mounted, setMounted] = useState(!!show);
  const [leaving, setLeaving] = useState(false);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (show) { setMounted(true); setLeaving(false); return undefined; }
    if (!mounted) return undefined;
    setLeaving(true);
    const t = setTimeout(() => { setMounted(false); setLeaving(false); }, EXIT_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show]);
  if (!mounted) return null;
  return (
    <div className={"glm-nudge" + (leaving ? " leaving" : settled ? " settled" : "")}
      onAnimationEnd={() => { if (!leaving) setSettled(true); }}>
      <button type="button" className="glm-nudge-go" onClick={onOpen} disabled={leaving}>{STRIP_TEXT}</button>
      <button type="button" className="glm-nudge-x" aria-label="Don't show this again on this phone"
        onClick={onDismiss} disabled={leaving}>{"✕"}</button>
    </div>
  );
}

export function NudgeBubble({ side }) {
  if (!side) return null;
  const top = side === "top";
  return (
    <div className={"mgnudge-bubble " + (top ? "top" : "bottom")} role="note">
      {top ? <span className="mgnudge-arrow" aria-hidden="true">{"▲"}</span> : null}
      <div className="mgnudge-card">{bubbleText(side)}</div>
      {!top ? <span className="mgnudge-arrow" aria-hidden="true">{"▼"}</span> : null}
    </div>
  );
}
