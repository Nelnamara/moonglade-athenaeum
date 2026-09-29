import React, { useEffect, useRef, useState } from "react";
import { recipesApi } from "./recipesApi.js";

/* "Save to a recipe set" (K decision 7, K §F). A tick applies at once -- there is no Save
   button -- and "+ New set" makes a private set and puts the recipe in it. The sets are
   PixAI's collections of recipes; the app calls them Sets because image Collections (❖)
   already own the word. `onChanged(recipeId, inAnySet)` lets the caller turn ⊕ into ✓.

   `sheet` draws it as a phone bottom sheet (the long-press road) instead of a popover. */
export default function RecipeSetsMenu({ recipeId, title, rect, onClose, onChanged, sheet }) {
  const [sets, setSets] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const box = useRef(null);

  useEffect(() => {
    let live = true;
    recipesApi.setsFor(recipeId).then((d) => {
      if (!live) return;
      if (!d || d.error) { setErr((d && d.error) || "PixAI didn't answer"); setSets([]); return; }
      setSets(d.sets || []);
      onChanged && onChanged(recipeId, (d.sets || []).some((s) => s.contains));
    });
    return () => { live = false; };
  }, [recipeId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sheet) return undefined;
    const onDown = (e) => { if (box.current && !box.current.contains(e.target)) onClose(); };
    const t = setTimeout(() => document.addEventListener("mousedown", onDown), 0);
    return () => { clearTimeout(t); document.removeEventListener("mousedown", onDown); };
  }, [onClose, sheet]);

  const apply = (next) => {
    setSets(next);
    onChanged && onChanged(recipeId, next.some((s) => s.contains));
  };
  const toggle = (s, list) => {
    const base = list || sets || [];
    if (busy && !list) return;
    const on = !s.contains;
    setBusy(s.id); setErr("");
    const before = base;
    apply(base.map((x) => (x.id === s.id ? { ...x, contains: on, count: x.count + (on ? 1 : -1) } : x)));
    recipesApi.setToggle(s.id, recipeId, on, s.item_id).then((d) => {
      setBusy("");
      if (!d || d.error) { apply(before); setErr((d && d.error) || "PixAI didn't answer"); return; }
      setSets((cur) => (cur || []).map((x) => (x.id === s.id ? { ...x, item_id: d.item_id || "" } : x)));
    });
  };
  const create = () => {
    const t = name.trim();
    if (!t || busy) return;
    setBusy("new"); setErr("");
    recipesApi.setCreate(t).then((d) => {
      if (!d || d.error || !d.set) { setBusy(""); setErr((d && d.error) || "PixAI didn't make the set"); return; }
      const made = { ...d.set, contains: false, item_id: "", count: 0 };
      setNaming(false); setName("");
      setBusy("");
      const next = [made, ...(sets || [])];
      setSets(next);
      toggle(made, next);
    });
  };

  const style = !sheet && rect ? {
    // right-aligned under the ⊕ that opened it (it sits at a card's top right)
    left: Math.max(8, Math.min((rect.right || rect.left) - 300, (typeof window !== "undefined" ? window.innerWidth : 1200) - 312)),
    top: Math.min(rect.top, (typeof window !== "undefined" ? window.innerHeight : 800) - 260),
  } : undefined;
  const body = (
    <div ref={box} className={sheet ? "rcp-sets rcp-sets-sheet" : "rcp-sets"} style={style} role="dialog"
      aria-label={"Save " + (title || "recipe") + " to a recipe set"} onClick={(e) => e.stopPropagation()}>
      <div className="rcp-sets-head">SAVE TO A RECIPE SET</div>
      {sets === null && <div className="rcp-sets-empty">Reading your sets…</div>}
      {sets && !sets.length && !err && <div className="rcp-sets-empty">No sets yet.</div>}
      {(sets || []).map((s) => (
        <button key={s.id} type="button" className={"rcp-sets-row" + (s.contains ? " on" : "")}
          onClick={() => toggle(s)} disabled={busy === s.id} aria-pressed={!!s.contains}>
          <span className="rcp-sets-name">{s.title}</span>
          <span className="rcp-mono rcp-muted">{s.count}</span>
          <span className="rcp-sets-check">{s.contains ? "✓" : ""}</span>
        </button>
      ))}
      {err && <div className="rcp-sets-err">{err}</div>}
      {naming ? (
        <div className="rcp-sets-new">
          <input autoFocus value={name} maxLength={100} placeholder="Name the set" onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") { e.stopPropagation(); setNaming(false); } }} />
          <button type="button" className="rcp-primary" onClick={create} disabled={!name.trim() || busy === "new"}>Make</button>
        </div>
      ) : (
        <button type="button" className="rcp-sets-add" onClick={() => setNaming(true)}>+ New set</button>
      )}
    </div>
  );
  if (!sheet) return body;
  return (
    <>
      <div className="rcp-m-scrim" onClick={onClose} aria-hidden="true" />
      <div className="rcp-m-sheet rcp-m-sheet-short">{body}</div>
    </>
  );
}
