import React, { useEffect, useRef, useState } from "react";
import { scrollParentOf } from "../../picker/mergeRows.js";
import { useHistoryPool } from "./useTraining.js";

/* "From history" (Training Handoff 2a): the shipped picture pool -- it pages on scroll through
   a sentinel observed from its own scroller (commit adaf033c's mechanism) -- with Grouped (a
   generation at a time, paged by task, issue #56) / All, the library's search, and a selected
   tray. Confirm adds the tray to the grid; nothing reaches PixAI from here. `have` is the set of
   media ids already in the grid, `room` what is left of 100. */
export default function TrainPool({ have, room, onAdd, onClose }) {
  const [mode, setMode] = useState("grouped");
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState("");
  const pool = useHistoryPool({ mode, q });
  const [tray, setTray] = useState([]);            // [{media_id, thumb}]
  const end = useRef(null);
  const { loadMore } = pool;

  useEffect(() => { loadMore(); }, [loadMore]);
  useEffect(() => {
    const el = end.current;
    if (!el || typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) loadMore();
    }, { root: scrollParentOf(el), rootMargin: "600px 0px", threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore, pool.items.length]);

  const inTray = new Set(tray.map((t) => t.media_id));
  const toggle = (entries) => {
    setTray((cur) => {
      const ids = new Set(cur.map((t) => t.media_id));
      const fresh = entries.filter((e) => !have.has(e.media_id));
      const allIn = fresh.length > 0 && fresh.every((e) => ids.has(e.media_id));
      if (allIn) return cur.filter((t) => !fresh.some((e) => e.media_id === t.media_id));
      const add = fresh.filter((e) => !ids.has(e.media_id)).slice(0, Math.max(0, room - cur.length));
      return cur.concat(add);
    });
  };

  return (
    <div className="mgtr-pool" role="dialog" aria-label="Pick from your history">
      <div className="mgtr-pool-head">
        <div className="mgtr-pool-title">From history <span>{tray.length} selected · room for {room}</span></div>
        <div className="mgtr-seg" role="group" aria-label="Grouped or all">
          {[["grouped", "Grouped"], ["all", "All"]].map(([k, l]) => (
            <button type="button" key={k} className={"mgtr-segbtn" + (mode === k ? " on" : "")}
              onClick={() => setMode(k)}>{l}</button>
          ))}
        </div>
      </div>
      <form className="mgtr-pool-search" onSubmit={(e) => { e.preventDefault(); setQ(typed.trim()); }}>
        <input className="mgtr-in" value={typed} placeholder="⌕ Search your prompts"
          onChange={(e) => setTyped(e.target.value)} />
      </form>
      <div className="mgtr-pool-grid">
        {pool.items.map((it) => {
          const entries = it.media_ids
            ? it.media_ids.map((m, i) => ({ media_id: String(m), thumb: i === 0 ? it.thumb : "/thumbs/" + m + ".jpg" }))
            : [{ media_id: it.media_id, thumb: it.thumb }];
          const already = entries.every((e) => have.has(e.media_id));
          const on = !already && entries.some((e) => inTray.has(e.media_id));
          return (
            <button type="button" key={it.key} disabled={already}
              className={"mgtr-pool-tile" + (on ? " on" : "") + (already ? " have" : "")}
              onClick={() => toggle(entries)} title={already ? "Already in the set" : on ? "Take out" : "Add"}>
              <img src={it.thumb} alt="" />
              {it.count > 1 && <span className="mgtr-pool-n">×{it.count}</span>}
              {(on || already) && <span className="mgtr-pool-check">✓</span>}
            </button>
          );
        })}
        <div ref={end} className="mgtr-poolend" aria-hidden="true" />
      </div>
      <div className="mgtr-pool-tray">
        <div className="mgtr-pool-traystrip">
          {tray.map((t) => (
            <button type="button" key={t.media_id} className="mgtr-pool-traytile"
              onClick={() => toggle([t])} title="Take out"><img src={t.thumb} alt="" /></button>
          ))}
          {!tray.length && <span className="mgtr-dim">Pick pictures above; they gather here.</span>}
        </div>
        <button type="button" className="mgtr-ghost" onClick={onClose}>Cancel</button>
        <button type="button" className="mgtr-go" disabled={!tray.length}
          onClick={() => { onAdd(tray); setTray([]); onClose(); }}>Add {tray.length || ""}</button>
      </div>
    </div>
  );
}
