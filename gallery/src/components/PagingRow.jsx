import React from "react";
import { usePaging, usePagingHint } from "../hooks/usePhonePrefs.js";
import { PAGINGS, PAGING_LABELS } from "../lib/phoneCore.js";
import "../styles/phone-u.css";

/* Control's "Library paging" row (Session U, U1b: "Control → Display shows a read-and-set Library paging
   row mirroring the same pref, so it can be found without the gesture"). Since the owner's walk
   (2026-10-04) it is the phone Control screen's first settings row, with Data saver beside it, in the
   same card language (its own classes, so each row stays one thing to find), and the same per-device
   value the gallery's long-press sheet sets. A tap writes -- the choice, and that the paging choice has
   been found, so the one-time dot under the gallery's layout keys goes whichever road found it.
   Opening Control writes nothing. */

const SUB = {
  pages: "‹ Prev · Next ›, a page at a time",
  continuous: "Loads as you scroll",
};

export default function PagingRow() {
  const [paging, setPaging] = usePaging();
  const [, markHintSeen] = usePagingHint();
  return (
    <div className="ctm-paging" role="group" aria-label="Library paging">
      <div className="ctm-paging-head">
        <div className="ctm-paging-title">
          <b>Library paging</b>
          <span>{SUB[paging]}</span>
        </div>
      </div>
      <div className="ctm-paging-modes" role="radiogroup" aria-label="Library paging mode">
        {PAGINGS.map((p) => (
          <button key={p} type="button" role="radio" aria-checked={paging === p}
            className={paging === p ? "on" : ""} onClick={() => { markHintSeen(); setPaging(p); }}>{PAGING_LABELS[p]}</button>
        ))}
      </div>
    </div>
  );
}
