import React, { useState } from "react";
import { datasetFits, roomLeft } from "../../gen/trainCore.js";

/* "Import a dataset" (Training Handoff 2a): your earlier Basic training sets with their counts
   (PixAI's own "Import from previous datasets" list: finished Basic runs). A set that won't fit
   what's left of 100 is dimmed. Importing adds its images to the one grid; the parent offers the
   set's old name, trigger and category. Read-only until Import; nothing reaches PixAI here. */
export default function DatasetImport({ datasets, items, imported, onImport, onClose, phone }) {
  const [picked, setPicked] = useState([]);
  const room = roomLeft(items);
  // what the ticked sets would add, counted against the room as each is ticked
  const pickedSets = (datasets || []).filter((d) => picked.includes(d.task_id));
  const virtual = items.concat(pickedSets.flatMap((d) => d.media_ids.map((m) => ({ media_id: String(m) }))));
  const toggle = (d, fits) => {
    if (!fits && !picked.includes(d.task_id)) return;
    setPicked((cur) => (cur.includes(d.task_id) ? cur.filter((x) => x !== d.task_id) : cur.concat([d.task_id])));
  };
  return (
    <div className={"mgtr-import" + (phone ? " phone" : "")}>
      <div className="mgtr-import-head">
        <div className="mgtr-import-title">Import from previous datasets</div>
        <div className="mgtr-mono">room for {room}</div>
      </div>
      {!datasets ? <div className="mgtr-dim">Reading your earlier sets…</div>
        : !datasets.length ? <div className="mgtr-dim">No earlier Basic sets on this account yet.</div>
          : datasets.map((d) => {
            const on = picked.includes(d.task_id);
            const done = imported.includes(d.task_id);
            const fits = on || done || datasetFits(d, virtual);
            return (
              <button type="button" key={d.task_id} disabled={done}
                className={"mgtr-import-row" + (on ? " on" : "") + (!fits ? " dim" : "") + (done ? " done" : "")}
                onClick={() => toggle(d, fits)} aria-pressed={on}
                title={!fits ? "Won't fit what's left of 100" : done ? "Imported" : ""}>
                <span className="mgtr-box">{on || done ? "✓" : ""}</span>
                {d.cover ? <img className="mgtr-import-cover" src={d.cover} alt="" /> : <span className="mgtr-import-cover" />}
                <span className="mgtr-import-name">{d.title}</span>
                <span className="mgtr-mono">{d.count}/100</span>
              </button>
            );
          })}
      <div className="mgtr-note">A dataset that won't fit the {room} left is dimmed. Importing also offers its old name, trigger and category.</div>
      <div className="mgtr-import-foot">
        {onClose && <button type="button" className="mgtr-ghost" onClick={onClose}>Close</button>}
        <button type="button" className="mgtr-go" disabled={!pickedSets.length}
          onClick={() => { onImport(pickedSets); setPicked([]); if (onClose) onClose(); }}>
          Import {pickedSets.length > 1 ? pickedSets.length + " datasets" : "dataset"}
        </button>
      </div>
    </div>
  );
}
