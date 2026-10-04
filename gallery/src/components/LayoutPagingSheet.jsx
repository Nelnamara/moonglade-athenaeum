import React, { useRef } from "react";
import MobileSheet from "./MobileSheet.jsx";
import { PAGINGS, PAGING_LABELS } from "../lib/phoneCore.js";
import "../styles/phone-u.css";

/* Layout and paging share one long-press sheet (Session U, U1b; Phone Paging and Nudge Handoff.dc.html
   section 1). A long-press on either of the gallery's ▦ / ▭ keys opens it; a tap on a key still only
   switches the layout, as shipped. Two 44 px segmented rows -- Layout (Grid · Feed) and Paging (Pages ·
   Continuous) -- and a choice applies at once; the sheet stays up until a tap outside or a swipe down.
   It is the shared MobileSheet (its scrim is the tap outside, its 280 ms exit the close), with the
   page's grab handle on top and no title. Both values are per device (hooks/usePhonePrefs.js). */

const LAYOUT_CHOICES = [["grid", "▦ Grid"], ["feed", "▭ Feed"]];
const SWIPE_CLOSE_PX = 50;

function Row({ label, choices, value, onPick }) {
  return (
    <div className="glm-pgrow" role="radiogroup" aria-label={label}>
      <span className="glm-pgrow-lbl">{label}</span>
      {choices.map(([v, text]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v}
          className={value === v ? "on" : ""} onClick={() => onPick(v)}>{text}</button>
      ))}
    </div>
  );
}

export default function LayoutPagingSheet({ open, closing, onClose, layout, setLayout, paging, setPaging }) {
  const swipe = useRef(null);
  const down = (e) => { swipe.current = e.clientY; };
  const up = (e) => {
    const y0 = swipe.current;
    swipe.current = null;
    if (y0 != null && e.clientY - y0 > SWIPE_CLOSE_PX) onClose();
  };
  return (
    <MobileSheet open={open} closing={closing} onClose={onClose} className="glm-pgsheet-host">
      <div className="glm-pgsheet" onPointerDown={down} onPointerUp={up} onPointerCancel={() => { swipe.current = null; }}>
        <div className="glm-pgsheet-grab" aria-hidden="true" />
        <Row label="Layout" choices={LAYOUT_CHOICES} value={layout} onPick={setLayout} />
        <Row label="Paging" choices={PAGINGS.map((p) => [p, PAGING_LABELS[p]])} value={paging} onPick={setPaging} />
        <div className="glm-pgsheet-note">Long-press {"▦"} or {"▭"} {"·"} tap outside or swipe down to close</div>
      </div>
    </MobileSheet>
  );
}
