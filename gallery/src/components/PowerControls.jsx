import React, { useEffect, useRef, useState } from "react";
import { defaultState, presetMeta, PRESET_MAX } from "../gen/powerCore.js";
import "../styles/power.css";

/* Session M's account-side power tools, drawn (Generate Power Tools Handoff, frame A and the
   rules M2 default negative, M3 ↺ Last and Presets, M4 quick-pick chips). Drawing only: every
   decision -- what a default fills, what a preset holds, what a chip does -- is in
   gen/powerCore.js and gen/useGenerate.js (`g.power`). The phone's copies of these pieces are
   PowerMobile.jsx; the presets list is the one component both mount. */

/* ---- ↺ Last and Presets ▾ (page: the composer header's two buttons) ---- */

/* The popover opens DOWN like the page's, unless the dock has no room below it (the dock sits at
   the foot of the screen): then it opens UP. Measured once, when it opens. */
function useDir(anchorRef, open) {
  const [dir, setDir] = useState("down");
  useEffect(() => {
    if (!open || !anchorRef.current) return;
    const btn = anchorRef.current.getBoundingClientRect();
    const dock = anchorRef.current.closest(".mgdock");
    const bottom = dock ? dock.getBoundingClientRect().bottom : window.innerHeight;
    const below = bottom - btn.bottom;
    const above = btn.top - (dock ? dock.getBoundingClientRect().top : 0);
    setDir(below < 300 && above > below ? "up" : "down");
  }, [open, anchorRef]);
  return dir;
}

/* A click outside the popover closes it (the dock's own outside-click closer counts anything
   inside .mgx-dock-host as inside, so this is the popover's own). */
function useOutside(ref, open, onClose) {
  useEffect(() => {
    if (!open) return undefined;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    // Escape closes THIS popover first (the dock's own Escape ladder would otherwise close the
    // whole dock underneath it): captured at the window, and stopped there.
    const k = (e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    document.addEventListener("mousedown", h);
    window.addEventListener("keydown", k, true);
    return () => { document.removeEventListener("mousedown", h); window.removeEventListener("keydown", k, true); };
  }, [open, ref, onClose]);
}

export function PowerHeader({ power, listsPop }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const dir = useDir(ref, open);
  useOutside(ref, open, () => setOpen(false));
  const hasLast = !!power.last;
  return (
    <>
      <button type="button" className="mgpow-btn last" disabled={!hasLast || power.restoring}
        title={hasLast ? "Refill from your last send" : "Available after your first send"}
        onClick={() => { setOpen(false); power.restoreLast(); }}>↺ Last</button>
      <span className="mgpow-anchor" ref={ref}>
        <button type="button" className={"mgpow-btn" + (open ? " on" : "")}
          aria-haspopup="dialog" aria-expanded={open}
          onClick={() => setOpen((v) => !v)}>Presets ▾</button>
        {open && (
          <div className={"mgpow-pop " + dir} role="dialog" aria-label="Presets">
            <PresetsPanel power={power} onDone={() => setOpen(false)} />
          </div>
        )}
      </span>
      {listsPop}
    </>
  );
}

/* The presets list (page: presets popover) -- name and its meta line, ✕ deletes, and a
   "Save current as…" row. The same panel is the phone's sheet body. Saving is a deliberate
   click; opening it writes nothing. */
export function PresetsPanel({ power, onDone, phone }) {
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const list = power.presets;
  const save = async () => {
    const r = await power.savePresetAs(name);
    if (r && r.error) { setMsg(r.error); return; }
    setName(""); setMsg("");
    if (phone && onDone) onDone();
  };
  return (
    <div className={"mgpow-panel" + (phone ? " phone" : "")}>
      {list.length === 0 ? <div className="mgpow-empty">No presets yet — set the composer up, then save it below.</div> : null}
      <div className="mgpow-list">
        {list.map((p) => (
          <div key={p.name} className="mgpow-item">
            <button type="button" className="mgpow-pick" disabled={power.restoring}
              onClick={() => { power.restorePreset(p); if (onDone) onDone(); }}>
              <span className="mgpow-name">{p.name}</span>
              <span className="mgpow-meta">{presetMeta(p)}</span>
            </button>
            <button type="button" className="mgpow-del" title="Delete preset" aria-label={"Delete preset " + p.name}
              onClick={() => power.removePreset(p.name)}>✕</button>
          </div>
        ))}
      </div>
      <div className="mgpow-save">
        <input value={name} placeholder="Save current as…" aria-label="Preset name" maxLength={60}
          onChange={(e) => { setName(e.target.value); setMsg(""); }}
          onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
        <button type="button" className="mgpow-savebtn" onClick={save} disabled={!name.trim()}>Save</button>
      </div>
      <div className={"mgpow-foot" + (msg ? " bad" : "")}>
        {msg || list.length + " of " + PRESET_MAX + " · saved to your account · the seed is never stored"}
      </div>
    </div>
  );
}

/* The Lists ▾ button and its popover (page M1: a name and one item per line, saved to the
   account). `children` is the sheet body (RunControls' ListsSheet). */
export function ListsPop({ open, onToggle, onClose, children }) {
  const ref = useRef(null);
  const dir = useDir(ref, open);
  useOutside(ref, open, onClose);
  return (
    <span className="mgpow-anchor" ref={ref}>
      <button type="button" className={"mgpow-btn" + (open ? " on" : "")} aria-haspopup="dialog"
        aria-expanded={open} title="Your saved lists — __name__ in a prompt" onClick={onToggle}>Lists ▾</button>
      {open && <div className={"mgpow-pop wide " + dir} role="dialog" aria-label="Saved lists">{children}</div>}
    </span>
  );
}

/* ---- MODELS / LORAS quick-pick rows (page M4) ---- */

function Chip({ c, onPick }) {
  return (
    <button type="button" className={"mgpow-chip" + (c.on ? " on" : "") + (c.dim ? " dim" : "")}
      title={c.title} aria-pressed={c.on} aria-disabled={c.dim || undefined}
      onClick={() => { if (!c.dim) onPick(c); }}>{c.label}</button>
  );
}

/* Desktop: two rows above the prompt, a row only while it has a chip to show. "+ more" opens
   the picker on that row's kind. A chip is a way in, never a second set of rules: a model chip
   is applyModelRow (the author preset and the family default follow), a LoRA chip adds at its
   last weight or removes. */
export function QuickRows({ power, ctxOn, onMoreModels, onMoreLoras }) {
  const models = power.modelChips, loras = ctxOn ? [] : power.loraChips;
  if (!models.length && !loras.length) return null;
  return (
    <div className="mgpow-rows">
      {models.length > 0 && (
        <div className="mgpow-row">
          <span className="mgdock-lbl mgpow-rowlbl">MODELS</span>
          {models.map((c) => <Chip key={c.id} c={c} onPick={() => power.pickModelChip(c.entry)} />)}
          <button type="button" className="mgpow-chip" title="Opens the model picker" onClick={onMoreModels}>+ more</button>
        </div>
      )}
      {loras.length > 0 && (
        <div className="mgpow-row">
          <span className="mgdock-lbl mgpow-rowlbl">LORAS</span>
          {loras.map((c) => <Chip key={c.id} c={c} onPick={() => power.toggleLoraChip(c.entry)} />)}
          <button type="button" className="mgpow-chip" title="Opens the LoRA picker" onClick={onMoreLoras}>+ more</button>
        </div>
      )}
    </div>
  );
}

/* ---- the negative's ★ Default button (page M2) and the one plain line after it ---- */

export function NegDefaultButton({ power, negative }) {
  const st = defaultState({ family: power.family, negative, defaults: power.defaults });
  return (
    <button type="button" className={"mgpow-default" + (st.isDefault ? " on" : "")} title={st.title}
      disabled={st.disabled} onClick={power.toggleNegDefault}>{st.label}</button>
  );
}

export function PowerNote({ note, phone }) {
  if (!note) return null;
  return <div className={"mgpow-note" + (phone ? " phone" : "")} role="status">{note}</div>;
}
