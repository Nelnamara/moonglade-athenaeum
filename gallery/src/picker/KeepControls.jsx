import React, { useState } from "react";
import { createPortal } from "react-dom";
import RecipeSetsMenu from "../recipes/RecipeSetsMenu.jsx";
import { savedApi } from "./savedApi.js";
import { READ_ONLY_LINE, keepTitle } from "./savedCore.js";
import "../styles/recipes.css";

/* The card's keep controls (Session S, Saved Tab Handoff sections 2-3; drift 135-136).

   [⊕ Save | ▾] on every picker card in the dock and on the phone sheet. The body is ONE save
   to PixAI's Saved (the picker sends it; the server reads it back) and then reads "✓ Saved";
   tapping ✓ Saved opens the menu and never unsaves in one tap. ▾ opens "Keep this model": the
   recipe Sets menu with ★ Quick-pick (this app) on top. The card's own ☆ toggle (Session M) is
   retired: a small lavender ★ before the control is quick-pick's state, nothing more. */

export function SaveSplit({ saved, busy, readOnly, onSave, onMenu, onBlocked }) {
  return (
    <span className={"mg-split" + (saved ? " saved" : "")} onClick={(e) => e.stopPropagation()}>
      <button type="button" className={"mg-split-body" + (readOnly && !saved ? " dim" : "")}
        aria-busy={busy || undefined} disabled={busy}
        title={readOnly && !saved ? READ_ONLY_LINE : saved ? "Saved on PixAI. More in the menu." : "Save to PixAI"}
        onClick={(e) => {
          e.stopPropagation();
          if (saved) { onMenu(e.currentTarget.parentNode); return; }
          if (readOnly) { onBlocked && onBlocked(); return; }
          onSave();
        }}>{saved ? "✓ Saved" : "⊕ Save"}</button>
      <button type="button" className="mg-split-menu" aria-haspopup="dialog" aria-label="More ways to keep it"
        title="Keep it: quick-pick, Saved and your sets"
        onClick={(e) => { e.stopPropagation(); onMenu(e.currentTarget.parentNode); }}>▾</button>
    </span>
  );
}

/* The row under a card's name: the "old" tag (S2c), quick-pick's ★, the split control, and
   the one line that answers the last write (emerald when PixAI confirmed it, peach when not). */
export function KeepRow({ m, quick, saved, busy, readOnly, note, onSave, onMenu, onBlocked }) {
  return (
    <>
      <div className="mg-keep">
        {m.old ? <span className="mg-old">old</span> : null}
        {quick ? <span className="mg-star" title="In your quick picks" aria-label="In your quick picks">★</span> : null}
        <SaveSplit saved={saved} busy={busy} readOnly={readOnly} onSave={onSave} onMenu={onMenu}
          onBlocked={onBlocked} />
      </div>
      {note ? <div className={"mg-keepnote " + note.kind} role="status">{note.text}</div> : null}
    </>
  );
}

/* Where a popover opens: under the control that opened it, right-aligned to it. */
export function keepRect(el) {
  const r = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
  return r ? { left: r.left, right: r.right, top: r.bottom + 4 } : null;
}

/* "Keep this model": one model's place in this app's quick picks and in PixAI's sets. Opening
   it reads (the selector); each PixAI tick is one write the server reads back. Portaled to
   <body>: the dock's palette is transformed and clips (the hover preview's trap), so the menu
   floats in the overlay band (.mg-keep-layer, 420); on the phone it is a bottom sheet over the
   Model/LoRA sheet (.rcp-m, 417 > 345). */
export function KeepMenu({ m, kind, rect, sheet, readOnly, quick, onQuick, onSets, onClose }) {
  const [ro, setRo] = useState(!!readOnly);
  const id = String(m.model_id);
  const api = {
    reread: true,
    setsFor: (mid) => savedApi.state(mid).then((d) => {
      if (d && typeof d.read_only === "boolean") setRo(d.read_only);
      return d;
    }),
    setToggle: (setId, mid, on, itemId) => savedApi.tick(setId, mid, on, itemId),
    setCreate: (title) => savedApi.createSet(title),
  };
  const menu = (
    <RecipeSetsMenu variant="keep" recipeId={id} title={m.title} heading={keepTitle(kind)} api={api}
      rect={rect} sheet={sheet} onClose={onClose} tag="PixAI" readOnly={ro ? READ_ONLY_LINE : ""}
      local={onQuick ? { label: "★ Quick-pick", tag: "this app", on: !!quick, onToggle: onQuick } : null}
      footLink={{ label: "Open on PixAI ↗", href: "https://pixai.art/model/" + encodeURIComponent(id) }}
      onChanged={(_, __, sets, settled) => settled && onSets && onSets(sets)} />
  );
  if (typeof document === "undefined") return null;
  // data-keeps-dock: a click in the menu is not a click outside the dock (App.jsx's closer)
  return createPortal(sheet ? <div className="rcp-m mg-keep-sheet" data-keeps-dock="">{menu}</div>
    : <div className="mg-keep-layer" data-keeps-dock="">{menu}</div>, document.body);
}

/* The same menu for a saved model PixAI no longer has (S5c "K not available ▸"): one row,
   Saved, ticked; unticking it takes the entry out of Saved by its item id. Nothing else can be
   done with it -- there is no model to quick-pick, open or put in a set. */
export function GoneMenu({ item, defaultId, rect, sheet, readOnly, onGone, onClose }) {
  const api = {
    setsFor: () => Promise.resolve({ sets: [{ id: defaultId || "saved", title: "Saved", count: 0, reserved: true,
      contains: true, item_id: item.item_id }] }),
    setToggle: (setId, _id, on) => (on ? Promise.resolve({ error: "A removed model can't be saved again" })
      : savedApi.remove(item.item_id).then((d) => {
        if (d && d.removed === true) { onGone && onGone(item); return { contains: false, item_id: "" }; }
        if (d && d.removed === false) return { contains: true, item_id: item.item_id, error: d.error || "PixAI didn't take it out" };
        return { error: (d && d.error) || "PixAI didn't answer" };
      })),
    setCreate: () => Promise.resolve({ error: "A removed model can't go in a set" }),
  };
  const menu = (
    <RecipeSetsMenu variant="keep" recipeId={item.item_id} title="Removed from PixAI" heading="Keep this model"
      api={api} rect={rect} sheet={sheet} onClose={onClose} tag="PixAI" canCreate={false}
      readOnly={readOnly ? READ_ONLY_LINE : ""} />
  );
  if (typeof document === "undefined") return null;
  // data-keeps-dock: a click in the menu is not a click outside the dock (App.jsx's closer)
  return createPortal(sheet ? <div className="rcp-m mg-keep-sheet" data-keeps-dock="">{menu}</div>
    : <div className="mg-keep-layer" data-keeps-dock="">{menu}</div>, document.body);
}
