import React, { useEffect, useRef, useState } from "react";
import Icon from "../icons/Icons.jsx";
import useCollectionOrder, { pictureLabel } from "../hooks/useCollectionOrder.js";
import { orderNote } from "../curation/collectionOrderCore.js";
import "../styles/curation.css";
import "../styles/collection-order.css";

/* THE ORDER EDITOR, desktop (Session P, P6 + P5; Loom Handoff.dc.html section A's
   "LOOM STILLS · MANUAL ORDER" panel -- its "P6 + P5 ·" label prefix is the page's own
   annotation and is not drawn, and the page's collection mark is the gallery's own collection
   icon here: the glyph ledger keeps that one character for the Folio's skin flag alone). A hand-picked collection's pictures as numbered rows: index,
   thumbnail, name, ▲ ▼. On desktop the rows DRAG (the page's ▲ ▼ "stand in for the drag"); the
   ▲ ▼ buttons stay, and so does the keyboard (a row focused: ↑ ↓ move between rows, Alt+↑ /
   Alt+↓ move the row). Save writes the order once. Under it, P5's two sends exactly as the page's
   panel has them: "as shots, in order" (lavender, primary) and "as cast" (outline).

   Opened from the collections manager's row slot (renderRowSlot, "Order") and from the
   collection view's Manual sort. It rides the manager's own layer (.mgcu-scrim / .mgcu-mgr,
   drawn after it, so it sits on top of it) -- no new z-index rung. Local catalog only: nothing
   here reaches PixAI, and neither send renders anything. */
export default function CollectionOrderEditor({ name, csrf, onClose }) {
  const o = useCollectionOrder(name, csrf);
  const [over, setOver] = useState(-1);
  const [dragging, setDragging] = useState(-1);
  const [focusAt, setFocusAt] = useState(-1);
  const rows = useRef([]);
  useEffect(() => {
    if (focusAt >= 0 && rows.current[focusAt]) rows.current[focusAt].focus();
  }, [focusAt, o.ids]);
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", esc, true);
    return () => window.removeEventListener("keydown", esc, true);
  }, [onClose]);

  const list = o.ids || [];
  const key = (i) => (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    const d = e.key === "ArrowUp" ? -1 : 1;
    const j = Math.max(0, Math.min(list.length - 1, i + d));
    if (e.altKey) o.nudge(i, d);
    setFocusAt(j);
  };
  const note = o.msg.text || orderNote({ manual: o.manual, count: list.length, dirty: o.dirty });

  return (
    <>
      <div className="mgcu-scrim" onMouseDown={onClose} />
      <div className="mgcu-mgr mgco" role="dialog" aria-modal="true" aria-label={"Manual order of " + name}>
        <div className="mgco-hd">
          <div className="mgco-cap"><Icon name="collection" /> {name}{" · MANUAL ORDER"}</div>
          <button type="button" className="mgcu-x" onClick={onClose} aria-label="Close">{"✕"}</button>
        </div>
        {o.ids === null ? <div className="mgco-empty">Reading the order…</div> : null}
        {o.ids && !list.length ? <div className="mgco-empty">No pictures in this collection yet.</div> : null}
        <div className="mgco-list" role="list" aria-label="Pictures, in order">
          {list.map((id, i) => (
            <div key={id} role="listitem" tabIndex={0} ref={(el) => { rows.current[i] = el; }}
              className={"mgco-row" + (over === i && dragging !== i ? " over" + (dragging > i ? " up" : " down") : "")
                + (dragging === i ? " dragging" : "")}
              aria-label={"Picture " + (i + 1) + " of " + list.length + ": " + pictureLabel(o.facts, id)
                + ". Drag, or Alt+Up and Alt+Down, to move it."}
              draggable
              onDragStart={(e) => { setDragging(i); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", id); } catch (err) { /* ok */ } }}
              onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (over !== i) setOver(i); }}
              onDragLeave={() => setOver((v) => (v === i ? -1 : v))}
              onDrop={(e) => { e.preventDefault(); if (dragging >= 0) o.move(dragging, i); setDragging(-1); setOver(-1); }}
              onDragEnd={() => { setDragging(-1); setOver(-1); }}
              onKeyDown={key(i)}>
              <span className="mgco-n">{i + 1}</span>
              <span className="mgco-thumb" style={{ backgroundImage: "url(/thumbs/" + encodeURIComponent(id) + ".jpg)" }} />
              <span className="mgco-name" title={pictureLabel(o.facts, id)}>{pictureLabel(o.facts, id)}</span>
              <button type="button" className="mgco-mv" aria-label={"Move picture " + (i + 1) + " up"} disabled={i === 0}
                onClick={() => o.nudge(i, -1)}>{"▲"}</button>
              <button type="button" className="mgco-mv" aria-label={"Move picture " + (i + 1) + " down"} disabled={i === list.length - 1}
                onClick={() => o.nudge(i, 1)}>{"▼"}</button>
            </div>
          ))}
        </div>
        <div className="mgco-foot">
          <div className={"mgco-note" + (o.msg.err ? " err" : "")} role="status">{note}</div>
          <button type="button" className={"mgcu-btn" + (o.dirty ? " primary" : "")} disabled={!o.dirty || o.busy}
            onClick={o.save}>Save order</button>
        </div>
        <div className="mgco-sends">
          <button type="button" className="mgco-send primary" disabled={o.busy || !list.length} onClick={o.sendShots}
            title="A new act of image-to-video shots, one per picture, in this order. Nothing is rendered.">
            {"▮ Send to The Loom · as shots, in order"}</button>
          <button type="button" className="mgco-send" disabled={o.busy || !list.length} onClick={o.sendCast}
            title="Today's hand-off: the pictures join the Loom's cast as @image references">
            {"▮ Send to The Loom · as cast"}</button>
        </div>
      </div>
    </>
  );
}
