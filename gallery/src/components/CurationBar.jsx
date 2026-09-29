import React, { useEffect, useRef, useState } from "react";
import Icon from "../icons/Icons.jsx";
import "../styles/curation.css";

/* THE BULK BAR (Session N, N4). One bar over the selection: ★1-5 . + Tag . Keeper . Reject .
   + collection, each applied to every picked picture at once (Curation Handoff, section A).
   The verbs are App's: they go through useCurate, whose server answer says how many pictures
   REALLY changed and which values to put back on Undo.

   IT SHOWS WHENEVER ANYTHING IS TICKED, not only with Select ON: in this app a checkbox
   ticks a picture without the mode (drift 9), and the rating keys already act on that same
   selection, so the bar follows the selection rather than the toggle.

   THE COLLECTION MENU LISTS HAND-PICKED COLLECTIONS ONLY. A smart collection is a saved
   search; pictures cannot be put into one (N1). The mark beside "+" is the app's books icon,
   not the page's ❖ -- the Glyph Ledger (2026-09-05) gave that character to the Folio's skin flag
   alone and drew collections as the books. */
export default function CurationBar({ count, handCollections, onStar, onTag, onKeeper, onReject, onAddTo, onClear }) {
  const [tag, setTag] = useState("");
  const [menu, setMenu] = useState(false);
  const wrap = useRef(null);

  useEffect(() => {
    if (!menu) return undefined;
    const onDown = (e) => { if (wrap.current && !wrap.current.contains(e.target)) setMenu(false); };
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); setMenu(false); } };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [menu]);

  const addTag = () => {
    if (!tag.trim()) return;
    onTag(tag);
    setTag("");
  };

  return (
    <div className="mgcu-bulk" role="toolbar" aria-label="Curate the selection">
      <div className="mgcu-bulk-n">{count} selected</div>
      <div className="mgcu-bulk-stars">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" className="mgcu-bulk-star" title={"Rate ★" + n}
            aria-label={"Rate " + n + " stars"} onClick={() => onStar(n)}>{"☆"}</button>
        ))}
      </div>
      <input className="mgcu-bulk-tag" value={tag} placeholder="tag…" aria-label="Tag to add"
        onChange={(e) => setTag(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }} />
      <button type="button" className="mgcu-btn" onClick={addTag}>+ Tag</button>
      <button type="button" className="mgcu-btn keeper" onClick={onKeeper}>{"✓"} Keeper</button>
      <button type="button" className="mgcu-btn" onClick={onReject}>{"✕"} Reject</button>
      <div className="mgcu-addwrap" ref={wrap}>
        <button type="button" className="mgcu-btn primary" aria-expanded={menu}
          title="Add the selection to a hand-picked collection" onClick={() => setMenu((v) => !v)}>
          + <Icon name="collection" /> {"▾"}
        </button>
        {menu && (
          <div className="mgcu-addmenu" role="menu">
            {handCollections.length === 0 ? (
              <div className="mgcu-addnone">No hand-picked collections yet. Actions {"▾"} Add to collection makes the first.</div>
            ) : handCollections.map((name) => (
              <button key={name} type="button" className="mgcu-addrow" role="menuitem"
                onClick={() => { setMenu(false); onAddTo(name); }}>
                <Icon name="collection" /> {name}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="mgcu-sp" />
      <button type="button" className="mgcu-x" onClick={onClear}>clear</button>
    </div>
  );
}
