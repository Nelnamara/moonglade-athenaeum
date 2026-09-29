import React, { useEffect, useState } from "react";
import Icon from "../icons/Icons.jsx";
import { fetchCollectionDetail } from "../api.js";
import "../styles/librarybar.css";
import "../styles/curation.css";

/* THE COLLECTIONS LIST (Session N, N1/N2): every collection with its count, the smart ones
   marked with the refresh mark, and Manage. It is the page's "Collections" rail drawn as a
   popover from the Filters tray's Collection chip -- the shipped gallery has no left rail to
   hang it on, and giving it one would restyle a whole owner-approved surface, so the rows,
   the counts and the Manage link are the page's and the panel that holds them is the tray's
   own menu language (.mgl-menu, the same anchored list as the Model chip).

   Reads /api/collections/detail when it opens: the counts are a read, and a smart
   collection's count is its query run then. Nothing is written on open. */
export default function CollectionsPanel({ anchor, active, names, onPick, onManage, onClose }) {
  const [rows, setRows] = useState(null);      // null until the read lands
  useEffect(() => {
    let dead = false;
    fetchCollectionDetail().then((r) => { if (!dead) setRows(r || []); });
    return () => { dead = true; };
  }, []);

  useEffect(() => {
    const onDown = (e) => {
      if (anchor && anchor.current && anchor.current.contains(e.target)) return;
      if (!e.target.closest || !e.target.closest(".mgcu-panel")) onClose();
    };
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [anchor, onClose]);

  // until the read lands, the names the shell already holds (no counts yet)
  const list = rows || (names || []).map((n) => ({ name: n.name, kind: n.kind, count: null }));
  const r = anchor && anchor.current ? anchor.current.getBoundingClientRect() : null;
  const style = r ? { left: Math.max(10, Math.min(r.left, window.innerWidth - 280)), top: r.bottom + 8 } : { left: 10, top: 80 };

  const row = (name, label, count, on, title, smart) => (
    <button key={name || "__all"} type="button" className={"mgcu-row" + (on ? " on" : "")} title={title}
      onClick={() => onPick(name)}>
      {name ? <Icon name="collection" /> : null}
      <span className="mgcu-row-name">{label}{smart ? " ⟳" : ""}</span>
      {count != null ? <span className="mgcu-row-n">{count}</span> : null}
    </button>
  );

  return (
    <div className="mgl-menu mgcu-panel" style={style} role="dialog" aria-label="Collections">
      <div className="mgcu-panel-hd">
        <span className="mgcu-panel-cap">COLLECTIONS</span>
        <button type="button" className="mgcu-panel-manage" onClick={onManage}>Manage</button>
      </div>
      <div className="mgcu-panel-scroll">
        {row("", "All pictures", null, !active, "")}
        {list.map((c) => row(c.name, c.name, c.count, active === c.name,
          c.kind === "smart" ? "Smart: " + (c.query || "a saved search") : "Hand-picked", c.kind === "smart"))}
      </div>
    </div>
  );
}
