import React, { useEffect, useRef, useState } from "react";
import { recipesApi } from "./recipesApi.js";

/* "Save to a recipe set" (K decision 7, K §F). A tick applies at once -- there is no Save
   button -- and "+ New set" makes a private set and puts the recipe in it. The sets are
   PixAI's collections of recipes; the app calls them Sets because image Collections (❖)
   already own the word. `onChanged(recipeId, inAnySet, sets, settled)` lets the caller turn ⊕
   into ✓; `settled` is false for a tick's at-once display and true once PixAI has answered.

   `sheet` draws it as a phone bottom sheet (the long-press road) instead of a popover.

   THE SAME MENU KEEPS A MODEL (Session S, S4c: "Keep this model"). `variant="keep"` draws the
   handoff's rows -- a tick box, the name, a mono tag -- with an optional `local` row first
   (★ Quick-pick, this app's own and instant) and a divider, then PixAI's sets tagged `tag`,
   then "+ New set" and `footLink` (Open on PixAI ↗). `api` swaps the recipe routes for the
   model ones ({setsFor, setToggle, setCreate}; `reread` asks for a read-back when a tick's
   answer never reached the page). `readOnly` (the reason, in words) disables the PixAI rows and
   "+ New set" and says why; the local row stays live. Every tick's ANSWER decides its row -- a
   model tick answers what the server's read-back found -- and one that failed reverts. */

const RECIPE_API = {
  setsFor: (id) => recipesApi.setsFor(id),
  setToggle: (setId, id, on, itemId) => recipesApi.setToggle(setId, id, on, itemId),
  setCreate: (title) => recipesApi.setCreate(title),
};

export default function RecipeSetsMenu({
  recipeId, title, rect, onClose, onChanged, sheet,
  api = RECIPE_API, variant = "sets", heading = "SAVE TO A RECIPE SET", local = null, tag = "",
  readOnly = "", footLink = null, canCreate = true,
}) {
  const keep = variant === "keep";
  const [sets, setSets] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const box = useRef(null);
  const liveRef = useRef(true);

  const load = () => api.setsFor(recipeId).then((d) => {
    if (!liveRef.current) return;
    if (!d || d.error) { setErr((d && d.error) || "PixAI didn't answer"); setSets([]); return; }
    setSets(d.sets || []);
    onChanged && onChanged(recipeId, (d.sets || []).some((s) => s.contains), d.sets || [], true);
  });
  useEffect(() => {
    liveRef.current = true;
    load();
    return () => { liveRef.current = false; };
  }, [recipeId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sheet) return undefined;
    const onDown = (e) => { if (box.current && !box.current.contains(e.target)) onClose(); };
    const t = setTimeout(() => document.addEventListener("mousedown", onDown), 0);
    return () => { clearTimeout(t); document.removeEventListener("mousedown", onDown); };
  }, [onClose, sheet]);

  const apply = (next, settled) => {
    setSets(next);
    onChanged && onChanged(recipeId, next.some((s) => s.contains), next, !!settled);
  };
  const toggle = (s, list) => {
    const base = list || sets || [];
    if ((busy && !list) || readOnly) return;
    const on = !s.contains;
    setBusy(s.id); setErr("");
    const before = base;
    apply(base.map((x) => (x.id === s.id ? { ...x, contains: on, count: x.count + (on ? 1 : -1) } : x)));
    // No live-check here: an answer that lands after the menu closed still reaches onChanged,
    // so the card behind it shows what PixAI said.
    api.setToggle(s.id, recipeId, on, s.item_id).then((d) => {
      setBusy("");
      if (d && typeof d.contains === "boolean") {
        // the answer decides the row: a recipe tick's reply, a model tick's read-back
        const landed = d.contains;
        apply(before.map((x) => (x.id === s.id ? {
          ...x, contains: landed, item_id: landed ? String(d.item_id || "") : "",
          count: x.count + (landed === !!s.contains ? 0 : (landed ? 1 : -1)),
        } : x)), true);
        if (d.error) setErr(d.error);
        return;
      }
      apply(before, true);
      setErr((d && d.error) || "PixAI didn't answer");
      if (api.reread && d && /^network error/i.test(String(d.error || ""))) load();
    });
  };
  const create = () => {
    const t = name.trim();
    if (!t || busy || readOnly) return;
    setBusy("new"); setErr("");
    api.setCreate(t).then((d) => {
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
  const newSet = naming ? (
    <div className="rcp-sets-new">
      <input autoFocus value={name} maxLength={100} placeholder="Name the set" onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") { e.stopPropagation(); setNaming(false); } }} />
      <button type="button" className="rcp-primary" onClick={create} disabled={!name.trim() || busy === "new"}>Make</button>
    </div>
  ) : null;
  const body = keep ? (
    <div ref={box} className={(sheet ? "rcp-sets rcp-sets-sheet" : "rcp-sets") + " rcp-keep"} style={style} role="dialog"
      aria-label={heading + ": " + (title || "")} onClick={(e) => e.stopPropagation()}>
      <div className="rcp-sets-head">{heading}</div>
      {local ? (
        <>
          <button type="button" className={"rcp-sets-row" + (local.on ? " on" : "")} aria-pressed={!!local.on}
            onClick={local.onToggle}>
            <span className="rcp-keep-box" aria-hidden="true">{local.on ? "☑" : "☐"}</span>
            <span className="rcp-sets-name">{local.label}</span>
            <span className="rcp-mono rcp-keep-tag">{local.tag}</span>
          </button>
          <div className="rcp-keep-div" role="separator" />
        </>
      ) : null}
      {readOnly ? <div className="rcp-sets-err">{readOnly}</div> : null}
      {sets === null && <div className="rcp-sets-empty">Reading your sets…</div>}
      {(sets || []).map((s) => (
        <button key={s.id} type="button" className={"rcp-sets-row" + (s.contains ? " on" : "")}
          onClick={() => toggle(s)} disabled={!!readOnly || busy === s.id} title={readOnly || undefined}
          aria-pressed={!!s.contains}>
          <span className="rcp-keep-box" aria-hidden="true">{s.contains ? "☑" : "☐"}</span>
          <span className="rcp-sets-name">{s.title}</span>
          <span className="rcp-mono rcp-keep-tag">{tag}</span>
        </button>
      ))}
      {err && <div className="rcp-sets-err">{err}</div>}
      {newSet}
      <div className="rcp-keep-foot">
        {canCreate && !naming ? (
          <button type="button" className="rcp-keep-link" disabled={!!readOnly} title={readOnly || undefined}
            onClick={() => setNaming(true)}>+ New set</button>
        ) : <span />}
        {footLink ? <a className="rcp-keep-link" href={footLink.href} target="_blank" rel="noopener noreferrer">{footLink.label}</a> : null}
      </div>
    </div>
  ) : (
    <div ref={box} className={sheet ? "rcp-sets rcp-sets-sheet" : "rcp-sets"} style={style} role="dialog"
      aria-label={"Save " + (title || "recipe") + " to a recipe set"} onClick={(e) => e.stopPropagation()}>
      <div className="rcp-sets-head">{heading}</div>
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
      {newSet || <button type="button" className="rcp-sets-add" onClick={() => setNaming(true)}>+ New set</button>}
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
