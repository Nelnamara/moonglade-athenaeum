import React from "react";
import { storageBars } from "../curation/storageCore.js";
import "../styles/curation.css";

/* COLLECTION HEALTH: STORAGE USED (Session N, N6). The single "Storage used" number became
   three stacked bars -- by type, by model, by collection -- each a row of segments with its
   legend beneath (Curation Handoff, section A2). A segment (or its legend entry) opens the
   gallery filtered to it: `onPick(filter)` gets the filter the segment stands for
   (storageCore.storageFilterPatch turns it into the gallery's own patch) and the shell closes
   the overlay or the screen and applies it.

   The numbers are the server's -- bytes on disk per catalogued picture, the health walk's own
   stats -- and the collections bar says "can overlap" because a picture in two collections
   counts in both. Desktop and phone draw this same component; `compact` stacks each label over
   its bar for the narrow screen, and nothing else differs.

   Read-only: opening Health reads these, nothing is written. */
export default function StorageBars({ storage, onPick, compact }) {
  const bars = storageBars(storage);
  if (!bars.length) return null;
  return (
    <section className={"mgcu-stor" + (compact ? " compact" : "")} aria-label="Storage used">
      <div className="mgcu-stor-hd">
        <div className="mgcu-stor-cap">STORAGE USED</div>
        <div className="mgcu-stor-total">{storage.total_h}</div>
        <div className="mgcu-stor-hint">{compact ? "tap" : "click"} a segment to filter the library to it</div>
      </div>
      {bars.map((b) => (
        <div className="mgcu-stor-row" key={b.id}>
          <div className="mgcu-stor-lbl">
            {b.label}
            {b.note ? <span className="mgcu-stor-note">{b.note}</span> : null}
          </div>
          <div className="mgcu-stor-body">
            <div className="mgcu-stor-track" role="group" aria-label={b.label.toLowerCase()}>
              {b.segments.map((s) => (
                <button key={s.key} type="button" className="mgcu-stor-seg"
                  style={{ flexBasis: s.pct + "%", background: s.hue }}
                  title={s.title} aria-label={s.title}
                  disabled={!s.filter} onClick={() => s.filter && onPick && onPick(s.filter)} />
              ))}
            </div>
            <div className="mgcu-stor-legend">
              {b.segments.map((s) => (
                <button key={s.key} type="button" className="mgcu-stor-key" title={s.title}
                  disabled={!s.filter} onClick={() => s.filter && onPick && onPick(s.filter)}>
                  <span className="mgcu-stor-dot" style={{ background: s.hue }} />
                  {s.title}
                </button>
              ))}
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}
