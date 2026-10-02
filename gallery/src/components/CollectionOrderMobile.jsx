import React, { useEffect, useRef, useState } from "react";
import Icon from "../icons/Icons.jsx";
import useCollectionOrder, { pictureLabel } from "../hooks/useCollectionOrder.js";
import { dropIndex, orderNote } from "../curation/collectionOrderCore.js";
import "../styles/curation.css";
import "../styles/collection-order.css";

/* THE ORDER EDITOR, phone (Session P, P6 + P5; the page's Phone line: "on N2's Collections
   screen, long-press a picture to drag it"). Shown IN the Collections screen, in place of the
   list, for one hand-picked collection -- the screen's own sub-view, back with ‹ Collections.
   LONG-PRESS a row to pick it up, drag it, let go to drop it; the tap twin (▲ ▼, the app's phone
   is tap-first) does the same one step at a time. Save writes the order once; the two Loom sends
   sit under it as on the page's panel. Local catalog only; nothing is rendered. */
const HOLD_MS = 420;          // how long a press is before it picks the row up
const SLOP = 8;               // px of movement before the hold that makes it a scroll instead

export default function CollectionOrderMobile({ name, csrf, onBack }) {
  const o = useCollectionOrder(name, csrf);
  const [drag, setDrag] = useState(null);        // {from, over, dy}
  const press = useRef(null);                    // {id, x, y, timer, from, tops, heights, y0}
  const rows = useRef([]);
  const listRef = useRef(null);
  const dragRef = useRef(null);
  dragRef.current = drag;

  // A picked-up row must not scroll the page under the finger.
  useEffect(() => {
    const el = listRef.current;
    if (!el) return undefined;
    const stop = (e) => { if (dragRef.current) e.preventDefault(); };
    el.addEventListener("touchmove", stop, { passive: false });
    return () => el.removeEventListener("touchmove", stop);
  }, []);

  const list = o.ids || [];
  const down = (i) => (e) => {
    if (e.target.closest && e.target.closest("button")) return;
    const p = { id: e.pointerId, x: e.clientX, y: e.clientY, from: i };
    p.timer = setTimeout(() => {
      const els = rows.current.slice(0, list.length);
      p.tops = els.map((r) => (r ? r.getBoundingClientRect().top : 0));
      p.heights = els.map((r) => (r ? r.getBoundingClientRect().height : 0));
      p.y0 = p.y;
      try { if (navigator.vibrate) navigator.vibrate(12); } catch (err) { /* no haptics */ }
      setDrag({ from: i, over: i, dy: 0 });
    }, HOLD_MS);
    press.current = p;
  };
  const move = (e) => {
    const p = press.current;
    if (!p || p.id !== e.pointerId) return;
    if (!dragRef.current) {
      if (Math.abs(e.clientX - p.x) > SLOP || Math.abs(e.clientY - p.y) > SLOP) { clearTimeout(p.timer); press.current = null; }
      return;
    }
    e.preventDefault();
    const at = dropIndex(p.tops, p.heights, e.clientY, p.from);
    setDrag((d) => (d ? { ...d, over: at, dy: e.clientY - p.y0 } : d));
  };
  const up = (e) => {
    const p = press.current;
    press.current = null;
    if (!p) return;
    clearTimeout(p.timer);
    const d = dragRef.current;
    if (d && p.id === e.pointerId) o.move(d.from, d.over);
    setDrag(null);
  };
  const cancel = () => { const p = press.current; if (p) clearTimeout(p.timer); press.current = null; setDrag(null); };
  const note = o.msg.text || orderNote({ manual: o.manual, count: list.length, dirty: o.dirty });

  return (
    <div className="mgco-m">
      <div className="mgco-m-bar">
        <button type="button" className="mgco-m-back" onClick={onBack}>{"‹ Collections"}</button>
        <span className="mgco-cap"><Icon name="collection" /> {name}{" · MANUAL ORDER"}</span>
      </div>
      <div className={"mgco-m-hint" + (o.msg.err ? " err" : "")} role="status">
        {o.msg.text || (list.length > 1 ? "Long-press a picture to drag it · ▲ ▼ move it one place" : note)}</div>
      {o.ids === null ? <div className="mgco-empty">Reading the order…</div> : null}
      <div className="mgco-list mgco-m-list" ref={listRef} role="list" aria-label="Pictures, in order">
        {list.map((id, i) => {
          const lifted = drag && drag.from === i;
          const shift = drag && !lifted ? (drag.from < i && drag.over >= i ? -1 : drag.from > i && drag.over <= i ? 1 : 0) : 0;
          return (
            <div key={id} role="listitem" ref={(el) => { rows.current[i] = el; }}
              className={"mgco-row mgco-m-row" + (lifted ? " lifted" : "")}
              style={lifted ? { transform: "translateY(" + drag.dy + "px)" }
                : shift ? { transform: "translateY(" + (shift * 100) + "%)" } : undefined}
              aria-label={"Picture " + (i + 1) + " of " + list.length + ": " + pictureLabel(o.facts, id)}
              onPointerDown={down(i)} onPointerMove={move} onPointerUp={up} onPointerCancel={cancel}
              onContextMenu={(e) => e.preventDefault()}>
              <span className="mgco-n">{i + 1}</span>
              <span className="mgco-thumb" style={{ backgroundImage: "url(/thumbs/" + encodeURIComponent(id) + ".jpg)" }} />
              <span className="mgco-name">{pictureLabel(o.facts, id)}</span>
              <button type="button" className="mgco-mv" aria-label={"Move picture " + (i + 1) + " up"} disabled={i === 0}
                onClick={() => o.nudge(i, -1)}>{"▲"}</button>
              <button type="button" className="mgco-mv" aria-label={"Move picture " + (i + 1) + " down"} disabled={i === list.length - 1}
                onClick={() => o.nudge(i, 1)}>{"▼"}</button>
            </div>
          );
        })}
      </div>
      <div className="mgco-foot">
        <div className={"mgco-note" + (o.msg.err ? " err" : "")}>{o.msg.text ? "" : note}</div>
        <button type="button" className={"mgcu-btn" + (o.dirty ? " primary" : "")} disabled={!o.dirty || o.busy}
          onClick={o.save}>Save order</button>
      </div>
      <div className="mgco-sends">
        <button type="button" className="mgco-send primary" disabled={o.busy || !list.length} onClick={o.sendShots}>
          {"▮ Send to The Loom · as shots, in order"}</button>
        <button type="button" className="mgco-send" disabled={o.busy || !list.length} onClick={o.sendCast}>
          {"▮ Send to The Loom · as cast"}</button>
      </div>
    </div>
  );
}
