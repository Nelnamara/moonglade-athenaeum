import React from "react";
import { countClauses, goneLine, SAVED_BASES } from "./savedCore.js";

/* The Saved tab's chrome (Session S, Saved Tab Handoff sections 1, 5): the 112 px set rail,
   the "Saved ▾" chooser it folds into below 640 px of picker width, the header with its
   "N · M old · K not available ▸" count, the LoRA base chips, and the dim list of saved
   models PixAI no longer has. ModelPicker.jsx owns the state and the reads; these draw. */

/* The rail: Saved first, then the named sets A-Z, each with this picker's count. The server
   has already left out every set holding none of this kind (moonglade_recipes.model_sets).
   No rename, no delete: managing sets stays on PixAI. */
export function SavedRail({ sets, current, onPick }) {
  return (
    <nav className="mg-rail" aria-label="Saved and your sets">
      {(sets || []).map((s) => {
        const on = !!current && current.id === s.id;
        return (
          <button key={s.id} type="button" className={"mg-rail-row" + (on ? " on" : "")}
            aria-pressed={on} title={s.title} onClick={() => onPick(s)}>
            <span className="mg-rail-mark" aria-hidden="true">{on ? "▸" : ""}</span>
            <span className="mg-rail-name">{s.title}</span>
            <span className="mg-rail-n">{s.count}</span>
          </button>
        );
      })}
    </nav>
  );
}

/* The same content as the rail, as a popover under the source row (desktop, a narrow picker). */
export function SavedChooser({ sets, current, onPick }) {
  return (
    <div className="mg-chooser" role="menu" aria-label="Saved and your sets">
      {(sets || []).map((s) => (
        <button key={s.id} type="button" role="menuitemradio"
          aria-checked={!!current && current.id === s.id}
          className={current && current.id === s.id ? "on" : ""} onClick={() => onPick(s)}>
          <span className="mg-chooser-name">{s.title}</span> · <span>{s.count}</span>
        </button>
      ))}
    </div>
  );
}

export function SavedHead({ title, count, old, gone, goneOpen, onGone }) {
  const clauses = countClauses({ count, old, gone });
  return (
    <div className="mg-saved-head">
      <span className="mg-saved-title">{title}</span>
      {clauses.length ? (
        <span className="mg-saved-count">
          {clauses.map((c, i) => (
            <React.Fragment key={c.key}>
              {i ? " · " : ""}
              {c.key === "gone" ? (
                <button type="button" className="mg-saved-gone" aria-expanded={!!goneOpen}
                  onClick={onGone}>{c.text + " ▸"}</button>
              ) : c.text}
            </React.Fragment>
          ))}
        </span>
      ) : null}
    </div>
  );
}

export function SavedChips({ value, onPick }) {
  return (
    <div className="mg-savedchips" role="group" aria-label="Base">
      {SAVED_BASES.map(([v, label]) => (
        <button key={v || "all"} type="button" className={value === v ? "on" : ""}
          aria-pressed={value === v} data-base={v} onClick={() => onPick(v)}>{label}</button>
      ))}
    </div>
  );
}

/* "K not available ▸": the saved models PixAI no longer has. They are left out of the list;
   here each shows what is left of it (when it was saved) and `renderKeep` draws its control. */
export function GoneList({ state, renderKeep }) {
  if (!state) return null;
  if (state.error) return <div className="mg-gone"><div className="mg-saved-line mg-saved-err">{state.error}</div></div>;
  if (!state.items) return <div className="mg-gone"><div className="mg-gone-row">Reading them…</div></div>;
  return (
    <div className="mg-gone" role="list">
      {state.items.map((it) => (
        <div key={it.item_id} className="mg-gone-row" role="listitem">
          <span className="mg-gone-name">{goneLine(it)}</span>
          {renderKeep ? renderKeep(it) : null}
        </div>
      ))}
      {!state.items.length ? <div className="mg-gone-row">None left.</div> : null}
    </div>
  );
}

/* "Show old bookmarks" at the end of Saved (S2c): on by default, per account. It is there
   while old rows remain, and while it is off (so it can be turned back on). */
export function OldToggle({ on, onToggle }) {
  return (
    <div className="mg-oldtoggle">
      <button type="button" role="switch" aria-checked={!!on} onClick={onToggle}>
        Show old bookmarks <span className={"mg-oldtoggle-dot" + (on ? " on" : "")} aria-hidden="true">{on ? "●" : "○"}</span>
      </button>
    </div>
  );
}
