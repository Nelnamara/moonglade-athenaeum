import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiGet } from "../api.js";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import { askPicker, isPickerOpen } from "./PickerHost.jsx";
import {
  GROUPS, GROUP_LABEL, MAX_COLORS, MINE_KEY, MINE_MAX, dividerShareAt, editorFromPalette,
  extractColors, fillGroup, focusBand, groupLocked, groupTotal, inkOn, moveColor, newEditor,
  newMineId, normalizeMine, normalizePreset, paletteRowState, paletteSummary, previewOf,
  removeColor, removeMine, rename, replaceFromLibrary, setCount, setDivider, setHex, stepShare,
  stripOf, toggleGroup, toPalette, upsertMine, validate,
} from "../gen/colorPaletteCore.js";
import "../styles/color-palette.css";

/* THE COLOUR PALETTE -- the Generate drawer's PALETTE row and its overlay (Library · Custom,
   and the editor). Session H decision 4 (Tsubaki3 Generate Handoff.dc.html frame D, "4a bars
   + 4c live preview", checked against PixAI's own editor, references 24-25) for the Custom
   tab and the editor; the Library tab is built to PixAI's own pattern (reference 23: cover-art
   cards with a colour strip) in the app's tokens -- it was not in the design run.

   Every rule lives in gen/colorPaletteCore.js; this file is the paint and the wiring.

   MOUNTING. The drawer mounts <PaletteRow> where the row goes (the dock's Tuning slab under
   creativity; the phone's Advanced screen, "Palette and negative stay in the shipped Advanced
   group") and hands it the generate state (`s`, `set`) and `ctx` -- whether context images are
   on, in which case the row is HELD (dimmed, "not sent"), never cleared. The row owns its own
   overlay, portaled to <body> at z 346/347 (color-palette.css), so the dock itself carries
   nothing but the mount.

   WHAT IT WRITES. `set({palette})` on the drawer state, and the account's saved palettes
   through useAccountPrefs (key palette.mine). Nothing is written to PixAI: its own saved
   palettes are a POST, and this lane never writes there. The Library is one read,
   GET /api/palettes/presets, shared by every row on the page. */

/* ---- the Library read: one fetch per page, shared ---- */
let _lib = null;            // {status: "ok"|"error", list, error}
let _libRun = null;
const _libSubs = new Set();
function _loadLibrary(force) {
  if (_libRun) return _libRun;
  if (_lib && _lib.status === "ok" && !force) return Promise.resolve(_lib);
  _libRun = apiGet("/api/palettes/presets").then((d) => {
    const list = ((d && d.palettes) || []).map(normalizePreset).filter(Boolean);
    _lib = (d && d.error && !list.length)
      ? { status: "error", list: [], error: String(d.error) }
      : { status: "ok", list, error: "" };
    return _lib;
  }).catch(() => {
    _lib = { status: "error", list: [], error: "network error" };
    return _lib;
  }).finally(() => {
    _libRun = null;
    for (const fn of [..._libSubs]) fn();
  });
  return _libRun;
}
function useLibrary(active) {
  const [, bump] = useState(0);
  useEffect(() => {
    const fn = () => bump((n) => n + 1);
    _libSubs.add(fn);
    return () => { _libSubs.delete(fn); };
  }, []);
  useEffect(() => { if (active) _loadLibrary(false); }, [active]);
  return {
    status: _lib ? _lib.status : "loading",
    list: _lib ? _lib.list : [],
    retry: () => { _lib = null; bump((n) => n + 1); _loadLibrary(true); },
  };
}

/* ---- small pieces ---- */
function Strip({ colors, className }) {
  return (
    <div className={"cpal-strip" + (className ? " " + className : "")}>
      {(colors || []).map((c, i) => (
        <i key={i} style={{ flex: c.ratio, background: c.hex }} />
      ))}
    </div>
  );
}

function Switch({ on, locked, title, onClick, big }) {
  return (
    <button type="button" role="switch" aria-checked={!!on} title={title}
      className={"cpal-sw" + (on ? " on" : "") + (locked ? " locked" : "") + (big ? " big" : "")}
      onClick={onClick}>
      <i />
    </button>
  );
}

/* The generated cover of a saved palette: the preview card's field, figure and strip. */
function MineCover({ palette, name }) {
  const pv = previewOf(palette);
  return (
    <div className="cpal-mcover" style={{ background: pv.field }}>
      <div className="cpal-mfigure" style={{ background: pv.figure }} />
      <div className="cpal-cardname">{name}</div>
    </div>
  );
}

/* Load a picture (a same-origin thumb or a local data: URL) and median-cut its colours. The
   picture never leaves the browser: an upload here is read with FileReader and nothing else. */
function colorsFromUrl(url, count) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      try {
        const W = 72;
        const w = W, h = Math.max(1, Math.round(W * (img.naturalHeight / Math.max(1, img.naturalWidth))));
        const c = document.createElement("canvas");
        c.width = w; c.height = Math.min(h, 144);
        const cx = c.getContext("2d");
        cx.drawImage(img, 0, 0, c.width, c.height);
        resolve(extractColors(cx.getImageData(0, 0, c.width, c.height).data, count));
      } catch {
        resolve([]);
      }
    };
    img.onerror = () => resolve([]);
    img.src = url;
  });
}

/* ---- one group's bar: bands by share, the divider handles, tap to focus ---- */
function GroupBar({ ed, setEd, k, phone, onBandTap }) {
  const barRef = useRef(null);
  const list = ed.groups[k];
  const startDrag = (i) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    const el = barRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const move = (ev) => {
      const frac = (ev.clientX - rect.left) / Math.max(1, rect.width);
      setEd((cur) => setDivider(cur, k, i, dividerShareAt(cur.groups[k], i, frac)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };
  const keyDivider = (i) => (e) => {
    const d = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;
    if (!d) return;
    e.preventDefault();
    setEd((cur) => setDivider(cur, k, i, cur.groups[k][i].ratio + d));
  };
  return (
    <div ref={barRef} className={"cpal-bar" + (phone ? " phone" : "")}>
      {list.map((c, i) => {
        const sel = ed.focus.group === k && ed.focus.index === i;
        const last = i === list.length - 1;
        return (
          <div key={i} className={"cpal-band" + (sel ? " sel" : "")}
            style={{ flex: c.ratio, background: c.hex }}
            title={c.hex + " · " + c.ratio + "%"}
            onClick={() => { setEd((cur) => focusBand(cur, k, i)); if (onBandTap) onBandTap(); }}>
            {!phone ? <span className={"cpal-pct " + inkOn(c.hex)}>{c.ratio}%</span> : null}
            {!last ? (
              <span className="cpal-handle" role="slider" tabIndex={0}
                aria-label={"Divider between colour " + (i + 1) + " and " + (i + 2)}
                aria-valuemin={1} aria-valuemax={c.ratio + list[i + 1].ratio - 1} aria-valuenow={c.ratio}
                title="Drag to trade share"
                onClick={(e) => e.stopPropagation()}
                onPointerDown={startDrag(i)} onKeyDown={keyDivider(i)}>↔</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/* A row of the focused group's list: hex pill · − share % + · ↑ ↓ × */
function ColorRow({ ed, setEd, k, i, c, big }) {
  const n = ed.groups[k].length;
  const sel = ed.focus.group === k && ed.focus.index === i;
  return (
    <div className={"cpal-crow" + (sel ? " sel" : "") + (big ? " big" : "")}
      onClick={() => setEd((cur) => focusBand(cur, k, i))}>
      <label className="cpal-hexpill" title="Change this colour" onClick={(e) => e.stopPropagation()}>
        <i style={{ background: c.hex }} />
        <span>{c.hex}</span>
        <input type="color" value={c.hex.toLowerCase()}
          onChange={(e) => setEd((cur) => setHex(cur, k, i, e.target.value))} />
      </label>
      <span className="cpal-sp" />
      <span className="cpal-stepper" onClick={(e) => e.stopPropagation()}>
        <button type="button" aria-label="Less share" disabled={n < 2}
          onClick={() => setEd((cur) => stepShare(cur, k, i, -1))}>−</button>
        <b>{c.ratio} %</b>
        <button type="button" aria-label="More share" disabled={n < 2}
          onClick={() => setEd((cur) => stepShare(cur, k, i, +1))}>+</button>
      </span>
      <span className="cpal-rowbtns" onClick={(e) => e.stopPropagation()}>
        <button type="button" aria-label="Move up" disabled={i === 0}
          onClick={() => setEd((cur) => moveColor(cur, k, i, -1))}>↑</button>
        <button type="button" aria-label="Move down" disabled={i === n - 1}
          onClick={() => setEd((cur) => moveColor(cur, k, i, +1))}>↓</button>
        <button type="button" aria-label="Remove" disabled={n <= 1}
          title={n <= 1 ? "A group keeps at least one colour — turn it off instead" : "Remove"}
          onClick={() => setEd((cur) => removeColor(cur, k, i))}>×</button>
      </span>
    </div>
  );
}

function CountStepper({ ed, setEd, k }) {
  const n = ed.groups[k].length;
  return (
    <span className="cpal-stepper cpal-count">
      <button type="button" aria-label="Fewer colours" disabled={n <= 1}
        onClick={() => setEd((cur) => setCount(cur, k, n - 1))}>−</button>
      <b>{n} {n === 1 ? "colour" : "colours"}</b>
      <button type="button" aria-label="More colours" disabled={n >= MAX_COLORS}
        onClick={() => setEd((cur) => setCount(cur, k, n + 1))}>+</button>
    </span>
  );
}

/* ---- the editor (frame D) ---- */
function Editor({ ed, setEd, lib, ctx, phone, onBack, onClose, onSave, saveNote }) {
  const [renaming, setRenaming] = useState(false);
  const [libOpen, setLibOpen] = useState(false);
  const [extractOpen, setExtractOpen] = useState(false);
  const [extractThumb, setExtractThumb] = useState("");
  const [extractNote, setExtractNote] = useState("");
  const [bandSheet, setBandSheet] = useState(false);
  const fileRef = useRef(null);
  const libRef = useRef(null);
  // The desktop Library menu closes on a press anywhere outside it (the phone's is inline).
  useEffect(() => {
    if (!libOpen || phone) return undefined;
    const down = (e) => { if (libRef.current && !libRef.current.contains(e.target)) setLibOpen(false); };
    document.addEventListener("pointerdown", down, true);
    return () => document.removeEventListener("pointerdown", down, true);
  }, [libOpen, phone]);
  const problems = validate(ed);
  const pal = toPalette(ed);
  const pv = previewOf(pal);
  const fk = ed.focus.group;

  const extract = async (url, thumb) => {
    const count = ed.on[fk] ? ed.groups[fk].length : 6;
    setExtractThumb(thumb || url);
    setExtractNote("Reading the picture's colours…");
    const colors = await colorsFromUrl(url, count);
    if (!colors.length) { setExtractNote("No colours could be read from that picture."); return; }
    setEd((cur) => fillGroup(cur, cur.focus.group, colors));
    setExtractNote(GROUP_LABEL[fk] + " now holds " + colors.length + " colour"
      + (colors.length === 1 ? "" : "s") + " from the picture.");
  };
  const fromGallery = async () => {
    const m = await askPicker({ type: "image" });
    if (m && m.media_id) extract("/thumbs/" + m.media_id + ".jpg", m.thumb);
  };
  const fromUpload = (file) => {
    if (!file) return;
    const r = new FileReader();
    r.onload = () => extract(String(r.result || ""), String(r.result || ""));
    r.readAsDataURL(file);
  };

  const title = renaming ? (
    <input className="cpal-rename" autoFocus value={ed.name} maxLength={50}
      aria-label="Palette name"
      onChange={(e) => setEd((cur) => rename(cur, e.target.value))}
      onBlur={() => setRenaming(false)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === "Escape") { e.stopPropagation(); setRenaming(false); } }} />
  ) : (
    <div className="cpal-edtitle" onClick={() => setRenaming(true)} title="Rename">{ed.name || "Untitled"}</div>
  );

  const libMenu = libOpen ? (
    <div className="cpal-libmenu" role="menu">
      {lib.status === "loading" ? <div className="cpal-dim">Loading PixAI's palettes…</div> : null}
      {lib.status === "error" ? <div className="cpal-dim">Couldn't load the Library.</div> : null}
      {lib.list.map((p) => (
        <button key={p.id} type="button" role="menuitem" className="cpal-libitem"
          onClick={() => { setEd((cur) => replaceFromLibrary(cur, p)); setLibOpen(false); }}>
          <span>{p.name}</span>
          <Strip colors={stripOf(p.palette)} />
        </button>
      ))}
    </div>
  ) : null;

  const extractRow = extractOpen ? (
    <div className="cpal-extract">
      <div className="cpal-exthumb" style={extractThumb ? { backgroundImage: "url(" + JSON.stringify(extractThumb) + ")" } : null} />
      <div className="cpal-extext">
        <div>Pick from your gallery, or upload</div>
        <div className="cpal-dim">{extractNote || "Fills the group you're on (" + GROUP_LABEL[fk].toLowerCase() + ") with the image's colours and their shares"}</div>
      </div>
      <button type="button" className="cpal-btn" onClick={fromGallery}>From the gallery</button>
      <button type="button" className="cpal-btn" onClick={() => fileRef.current && fileRef.current.click()}>Upload</button>
      <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
        onChange={(e) => { const f = e.target.files && e.target.files[0]; e.target.value = ""; fromUpload(f); }} />
    </div>
  ) : null;

  const groupsView = GROUPS.map((k) => {
    const on = ed.on[k];
    const list = ed.groups[k];
    const locked = groupLocked(ed, k);
    return (
      <div key={k} className="cpal-group">
        <div className="cpal-ghead">
          <button type="button" className={"cpal-glabel" + (fk === k && on ? " focus" : "")}
            onClick={() => on && setEd((cur) => focusBand(cur, k, 0))}>
            {phone ? GROUP_LABEL[k] : GROUP_LABEL[k].toUpperCase()}
          </button>
          <span className="cpal-gtotal">{on ? list.length + " · " + groupTotal(list) + "%" : "off"}</span>
          <span className="cpal-sp" />
          <Switch on={on} locked={locked} big={phone}
            title={locked ? "Overall or background must stay on" : on ? "Turn off" : "Turn on"}
            onClick={() => setEd((cur) => toggleGroup(cur, k))} />
        </div>
        {on ? (
          <GroupBar ed={ed} setEd={setEd} k={k} phone={phone} onBandTap={phone ? () => setBandSheet(true) : null} />
        ) : (
          <button type="button" className={"cpal-gempty" + (phone ? " phone" : "")}
            onClick={() => setEd((cur) => toggleGroup(cur, k))}>
            Off · turn on to add colours to {GROUP_LABEL[k].toLowerCase()}
          </button>
        )}
      </div>
    );
  });

  const notes = (
    <>
      {ctx ? <div className="cpal-held">Held while context images are on · used when you switch back</div> : null}
      {problems.length ? <div className="cpal-held">{problems.join(" · ")}</div> : null}
      {saveNote ? <div className="cpal-held">{saveNote}</div> : null}
    </>
  );

  if (phone) {
    const fl = ed.groups[fk] || [];
    const fi = Math.min(ed.focus.index, Math.max(0, fl.length - 1));
    return (
      <div className="cpal-ed phone">
        <div className="cpal-phead">
          <div className="cpal-pmini" style={{ background: pv.field }}><Strip colors={pv.strip} /></div>
          <div className="cpal-pname">
            {title}
            <div className="cpal-dim">{ed.from ? "from " + ed.from : "your own"}</div>
          </div>
          <button type="button" className="cpal-link" onClick={() => setRenaming(true)}>rename</button>
        </div>
        <div className="cpal-pbtns">
          <button type="button" className={"cpal-btn big" + (libOpen ? " on" : "")}
            onClick={() => { setLibOpen(!libOpen); setExtractOpen(false); }}>From Library</button>
          <button type="button" className={"cpal-btn big" + (extractOpen ? " on" : "")}
            onClick={() => { setExtractOpen(!extractOpen); setLibOpen(false); }}>From image</button>
        </div>
        {libMenu}
        {extractRow}
        {groupsView}
        <div className="cpal-hint">Tap a band to change its colour and share · drag a divider to trade shares · overall or background must be on</div>
        {notes}
        <div className="cpal-foot phone">
          <button type="button" className="cpal-btn big" onClick={onBack}>Cancel</button>
          <button type="button" className="cpal-primary big" disabled={problems.length > 0}
            onClick={onSave}>Save &amp; apply</button>
        </div>
        {bandSheet && ed.on[fk] && fl[fi] ? (
          <>
            <div className="cpal-bandscrim" onClick={() => setBandSheet(false)} />
            <div className="cpal-bandsheet" role="dialog" aria-label={GROUP_LABEL[fk] + " colour"}>
              <div className="cpal-grab" />
              <div className="cpal-ghead">
                <span className="cpal-glabel focus">{GROUP_LABEL[fk]} · colour {fi + 1}</span>
                <span className="cpal-sp" />
                <CountStepper ed={ed} setEd={setEd} k={fk} />
              </div>
              <ColorRow ed={ed} setEd={setEd} k={fk} i={fi} c={fl[fi]} big />
              <button type="button" className="cpal-btn big" onClick={() => setBandSheet(false)}>Done</button>
            </div>
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div className="cpal-ed">
      <div className="cpal-edhead">
        <button type="button" className="cpal-back" onClick={onBack} aria-label="Back">‹</button>
        {title}
        <button type="button" className="cpal-link" onClick={() => setRenaming(true)}>rename</button>
        <button type="button" className="cpal-x" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="cpal-edbtns">
        <div className="cpal-libwrap" ref={libRef}>
          <button type="button" className={"cpal-btn" + (libOpen ? " on" : "")} aria-haspopup="menu"
            onClick={() => { setLibOpen(!libOpen); }}>Replace colours from the Library ▾</button>
          {libMenu}
        </div>
        <button type="button" className={"cpal-btn" + (extractOpen ? " on" : "")}
          onClick={() => setExtractOpen(!extractOpen)}>Extract from image</button>
      </div>
      {extractRow}
      <div className="cpal-edbody">
        <div className="cpal-edmain">
          {groupsView}
          <div className="cpal-hint">Tap a colour to select it · drag a divider to change the shares · 1–12 colours per group · overall or background must be on</div>
          {ed.on[fk] ? (
            <div className="cpal-list">
              <div className="cpal-listhead">
                <span className="cpal-lbl">{fk.toUpperCase()} · COLOURS</span>
                <span className="cpal-sp" />
                <CountStepper ed={ed} setEd={setEd} k={fk} />
              </div>
              <div className="cpal-rows">
                {ed.groups[fk].map((c, i) => <ColorRow key={i} ed={ed} setEd={setEd} k={fk} i={i} c={c} />)}
              </div>
            </div>
          ) : null}
        </div>
        <div className="cpal-preview">
          <div className="cpal-lbl">PREVIEW</div>
          <div className="cpal-pcard">
            <div className="cpal-pfield" style={{ background: pv.field }}>
              <div className="cpal-pfigure" style={{ background: pv.figure }} />
              <div className="cpal-pcardname">{ed.name || "Untitled"}</div>
            </div>
            <Strip colors={pv.strip} className="cpal-pstrip" />
          </div>
          <div className="cpal-dim">The Library card, repainted live: background as the field, character (or overall) as the figure, overall as the strip.</div>
        </div>
      </div>
      <div className="cpal-foot">
        <div className="cpal-footnotes">{notes}</div>
        <button type="button" className="cpal-btn" onClick={onBack}>Cancel</button>
        <button type="button" className="cpal-primary" disabled={problems.length > 0}
          title={problems.length ? problems.join(" · ") : "Save to your palettes and use it"}
          onClick={onSave}>Save &amp; apply</button>
      </div>
    </div>
  );
}

/* ---- the overlay: Library · Custom, and the editor ---- */
function PaletteOverlay({ closing, onClose, applied, onApply, ctx, phone, host }) {
  const prefs = useAccountPrefs();
  const mine = useMemo(() => normalizeMine(prefs.get(MINE_KEY, [])), [prefs.prefs]); // eslint-disable-line react-hooks/exhaustive-deps
  const lib = useLibrary(true);
  const [tab, setTab] = useState(applied && applied.source === "mine" ? "custom" : "library");
  const [sel, setSel] = useState(applied ? { kind: applied.source, id: applied.id } : null);
  const [ed, setEd] = useState(null);
  const [edTab, setEdTab] = useState("library");
  const [saveNote, setSaveNote] = useState("");
  const [delArm, setDelArm] = useState("");
  const [saving, setSaving] = useState(false);
  const panelRef = useRef(null);
  // Focus moves into the window when it opens, so the keyboard starts where the eye is.
  useEffect(() => { if (panelRef.current) panelRef.current.focus({ preventScroll: true }); }, []);

  // Escape: the topmost layer only. The picker handles its own; the editor's rename field
  // stops its own Escape; otherwise the editor steps back, then the overlay closes. Capture
  // phase, stopped here, so the dock underneath does not also close.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape" || isPickerOpen()) return;
      // The rename field ends its own edit on Escape (and stops it there).
      if (e.target && e.target.classList && e.target.classList.contains("cpal-rename")) return;
      e.stopPropagation();
      if (ed) setEd(null); else onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [ed, onClose]);

  const openEditor = (next, from) => { setSaveNote(""); setEdTab(from); setEd(next); };
  const selected = sel && (sel.kind === "library"
    ? lib.list.find((p) => p.id === sel.id)
    : mine.find((p) => p.id === sel.id));
  const inUse = !!(applied && selected && applied.id === selected.id && applied.source === sel.kind);

  const use = (p, kind) => {
    onApply({ name: p.name, palette: p.palette, source: kind, id: p.id, from: p.from || "" });
    onClose();
  };
  const save = async () => {
    if (!ed || saving || validate(ed).length) return;
    const id = ed.id || newMineId(Date.now(), Math.random());
    const r = upsertMine(prefs.get(MINE_KEY, []), ed, id);
    if (r.full) {
      setSaveNote("You have " + MINE_MAX + " saved palettes — delete one on Custom to save another.");
      return;
    }
    setSaving(true);
    const res = await prefs.set(MINE_KEY, r.list);
    setSaving(false);
    if (res && res.error) { setSaveNote("Couldn't save it: " + res.error); return; }
    onApply({ name: r.entry.name, palette: r.entry.palette, source: "mine", id: r.entry.id, from: r.entry.from });
    onClose();
  };
  const del = async (id) => {
    if (delArm !== id) { setDelArm(id); return; }
    setDelArm("");
    const res = await prefs.set(MINE_KEY, removeMine(prefs.get(MINE_KEY, []), id));
    if (res && res.error) setSaveNote("Couldn't delete it: " + res.error);
    else setSel(null);
  };

  const cardsLibrary = (
    <div className={"cpal-grid" + (phone ? " phone" : "")}>
      {lib.status === "loading" && !lib.list.length
        ? Array.from({ length: phone ? 6 : 10 }, (_, i) => <div key={i} className="cpal-card skel" />)
        : null}
      {lib.status === "error" && !lib.list.length ? (
        <div className="cpal-empty">
          Couldn't load PixAI's palettes. <button type="button" className="cpal-link" onClick={lib.retry}>Try again</button>
        </div>
      ) : null}
      {lib.list.map((p) => {
        const on = sel && sel.kind === "library" && sel.id === p.id;
        return (
          <button key={p.id} type="button" className={"cpal-card" + (on ? " sel" : "")}
            aria-pressed={on} title={p.name} onClick={() => setSel({ kind: "library", id: p.id })}
            onDoubleClick={() => use(p, "library")}>
            <div className="cpal-cover">
              {p.cover_url ? <img src={p.cover_url} alt="" draggable="false" /> : null}
              <div className="cpal-cardname">{p.name}</div>
              {applied && applied.source === "library" && applied.id === p.id ? <span className="cpal-tick">✓</span> : null}
            </div>
            <Strip colors={stripOf(p.palette)} />
          </button>
        );
      })}
    </div>
  );

  const cardsMine = (
    <div className={"cpal-grid" + (phone ? " phone" : "")}>
      <button type="button" className="cpal-card cpal-new" onClick={() => openEditor(newEditor(), "custom")}>
        <span className="cpal-plus">+</span>
        <span>New colour palette</span>
      </button>
      {mine.map((p) => {
        const on = sel && sel.kind === "mine" && sel.id === p.id;
        return (
          <button key={p.id} type="button" className={"cpal-card" + (on ? " sel" : "")}
            aria-pressed={on} title={p.name} onClick={() => setSel({ kind: "mine", id: p.id })}
            onDoubleClick={() => use(p, "mine")}>
            <div className="cpal-cover"><MineCover palette={p.palette} name={p.name} />
              {applied && applied.source === "mine" && applied.id === p.id ? <span className="cpal-tick">✓</span> : null}
            </div>
            <Strip colors={stripOf(p.palette)} />
          </button>
        );
      })}
    </div>
  );

  const footer = selected && ((tab === "library" && sel.kind === "library") || (tab === "custom" && sel.kind === "mine")) ? (
    <div className={"cpal-selbar" + (phone ? " phone" : "")}>
      <Strip colors={stripOf(selected.palette)} className="cpal-selstrip" />
      <div className="cpal-selname">
        <b>{selected.name}</b>
        <span className="cpal-dim">{paletteSummary(selected).split(" · ").slice(1).join(" · ")}{inUse ? " · in use" : ""}</span>
      </div>
      <span className="cpal-sp" />
      {sel.kind === "library" ? (
        <button type="button" className="cpal-btn" onClick={() => openEditor(
          editorFromPalette(selected.palette, { name: ("My " + selected.name).slice(0, 50), from: selected.name }), "library")}>
          Customise
        </button>
      ) : (
        <>
          <button type="button" className={"cpal-btn" + (delArm === selected.id ? " ruby" : "")}
            onClick={() => del(selected.id)}>{delArm === selected.id ? "Delete · sure?" : "Delete"}</button>
          <button type="button" className="cpal-btn" onClick={() => openEditor(
            editorFromPalette(selected.palette, { name: selected.name, id: selected.id, from: selected.from }), "custom")}>
            Edit
          </button>
        </>
      )}
      <button type="button" className="cpal-primary" onClick={() => use(selected, sel.kind)}>Use palette</button>
    </div>
  ) : (
    <div className={"cpal-selbar empty" + (phone ? " phone" : "")}>
      <span className="cpal-dim">{tab === "library"
        ? "Pick a palette to use it, or customise it into your own."
        : "Your saved palettes, kept with your account. Make one with + New colour palette."}</span>
    </div>
  );

  const body = ed ? (
    <Editor ed={ed} setEd={(fn) => { setSaveNote(""); setEd(fn); }} lib={lib} ctx={ctx} phone={phone}
      saveNote={saveNote || (saving ? "Saving…" : "")}
      onBack={() => { setEd(null); setTab(edTab); }} onClose={onClose} onSave={save} />
  ) : (
    <div className="cpal-tabsview">
      <div className="cpal-head">
        <div className="cpal-title">Colour palette</div>
        <span className="cpal-sp" />
        {!phone ? <button type="button" className="cpal-x" onClick={onClose} aria-label="Close">×</button> : null}
      </div>
      <div className="cpal-tabs" role="tablist">
        {[["library", "Library"], ["custom", "Custom"]].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k}
            className={"cpal-tab" + (tab === k ? " on" : "")}
            onClick={() => { setTab(k); setDelArm(""); setSaveNote(""); }}>{l}{k === "custom" && mine.length ? " · " + mine.length : ""}</button>
        ))}
      </div>
      <div className="cpal-scroll">{tab === "library" ? cardsLibrary : cardsMine}</div>
      {ctx ? <div className="cpal-held pad">Held while context images are on · used when you switch back</div> : null}
      {saveNote ? <div className="cpal-held pad">{saveNote}</div> : null}
      {footer}
    </div>
  );

  return createPortal(
    <>
      <div className={"cpal-scrim" + (closing ? " closing" : "") + (phone ? " phone" : "")} onClick={onClose} aria-hidden="true" />
      <div className={"cpal-host" + (phone ? " phone" : "")} onClick={phone ? undefined : onClose}>
        <div ref={panelRef} tabIndex={-1}
          className={"cpal-panel" + (closing ? " closing" : "") + (phone ? " phone" : "") + (ed ? " editing" : "")}
          role="dialog" aria-modal="true" aria-label="Colour palette"
          onClick={(e) => e.stopPropagation()}>
          {phone ? <div className="cpal-grab" /> : null}
          {body}
        </div>
      </div>
    </>,
    host || document.body,
  );
}

/* ---- the row in the drawer ---- */
export function PaletteRow({ s, set, ctx, phone }) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const timer = useRef(null);
  const rowRef = useRef(null);
  // Where the overlay mounts: inside the dock's host wrapper when there is one (display:
  // contents, so it is neither a containing block nor a stacking context) -- the app's
  // outside-click closer counts that as inside the dock, as it does the model flyout -- else
  // <body> (the phone).
  const [host, setHost] = useState(null);
  const row = paletteRowState(s, ctx);
  const pal = s.palette;
  const ms = phone ? 280 : 350;
  const show = () => {
    clearTimeout(timer.current);
    setHost((rowRef.current && rowRef.current.closest(".mgx-dock-host")) || document.body);
    setClosing(false);
    setOpen(true);
  };
  const hide = useCallback(() => {
    setClosing(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { setOpen(false); setClosing(false); }, ms);
  }, [ms]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const ov = pal && pal.palette ? pal.palette : null;
  const bgColors = ov && ov.background ? ov.background.colors : [];
  const topColors = ov ? (ov.overall ? ov.overall.colors : bgColors) : [];
  const second = ov && ov.overall && ov.background ? bgColors : [];
  // On the Context side the whole row reads held, the way the negative and the recipes do there
  // (owner walk 2026-09-29): dimmed, with the held note, pick or no pick. A pick stays possible --
  // the overlay says it is held and used when you switch back -- and nothing held is sent
  // (colorPaletteCore.paletteForPayload; loom/test/color-palette-core.test.js pins the payload).
  const ctxHeld = !!ctx;

  return (
    <div ref={rowRef} className={"cpal-row" + (phone ? " phone" : "")}>
      <div className="cpal-rowhead">
        {!phone ? <span className="mgdock-lbl">PALETTE</span> : null}
        <span className="cpal-sp" />
        <button type="button" className={"cpal-link" + (ctxHeld ? " held" : "")} onClick={show}
          title={ctxHeld ? "Held · not sent with context images — a palette picked here is used when you switch back"
            : "Choose a colour palette, or make your own"}>Library · Custom ›</button>
      </div>
      {pal ? (
        <div className={"cpal-rowbody" + (row.state === "held" ? " held" : "")}>
          <Strip colors={topColors} className="cpal-rowstrip" />
          {second.length ? <Strip colors={second} className="cpal-rowstrip thin" /> : null}
          <div className="cpal-rowname">
            <span>{paletteSummary(pal)}</span>
            <button type="button" className="cpal-rowx" title="Stop using this palette"
              aria-label="Stop using this palette" onClick={() => set({ palette: null })}>×</button>
          </div>
        </div>
      ) : (
        <button type="button" className={"cpal-rownone" + (phone ? " phone" : "") + (ctxHeld ? " held" : "")} onClick={show}>
          None · pick one from the Library or make your own
        </button>
      )}
      {row.note ? <div className="cpal-rownote">{row.note}</div> : null}
      {open ? (
        <PaletteOverlay closing={closing} onClose={hide} applied={pal} ctx={ctx} phone={phone}
          host={host} onApply={(p) => set({ palette: p })} />
      ) : null}
    </div>
  );
}

export default PaletteRow;
