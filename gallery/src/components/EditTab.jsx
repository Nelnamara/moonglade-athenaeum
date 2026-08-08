import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  buildEditPayload, editCaps, editGate, EDIT_CAPS, EDIT_DEFAULTS,
  refTag, switchEditModel,
} from "../gen/editCore.js";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { askPicker } from "./PickerHost.jsx";

/* The Edit tab: Edit Pro / Reference Pro against /api/edit, with the toolbox
   preset bank. @image1 is the image being edited; extra references number from
   @image2 -- the instruction refers to them by those tags. */
export default function EditTab({ visible, initialSource }) {
  const [s, setS] = useState(EDIT_DEFAULTS);
  const [presets, setPresets] = useState({});
  const [importTask, setImportTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, openLine] = useResultLines();
  const costRef = useRef(null);
  const costHost = useRef(null);
  const busyRef = useRef(false);
  const seq = useRef(0);
  const timer = useRef(0);
  const caps = editCaps(s.model);
  const gate = editGate(s);
  const used = ((s.source || "").trim() ? 1 : 0) + s.refs.length;

  const set = (patch) => setS((old) => ({ ...old, ...patch }));

  // An entry point (lightbox / filters panel) hands us {mid, n} -- a fresh object
  // per hand-off, so re-sending the SAME image still re-applies after the user
  // cleared or swapped the source (see GenerateDrawer's editSource comment).
  useEffect(() => {
    if (initialSource && initialSource.mid) set({ source: initialSource.mid });
  }, [initialSource]);

  // presets load lazily, once, when the tab is first shown
  useEffect(() => {
    if (!visible || Object.keys(presets).length) return;
    fetch("/api/presets").then((r) => r.json())
      .then((d) => setPresets((d && d.presets) || {})).catch(() => {});
  }, [visible]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Its OWN debounce + seq pair -- sharing them with the image tab's is exactly
     what caused the classic's historical no-price-on-?edit= bug. */
  const fireCost = useCallback(() => {
    const mine = ++seq.current;
    const badge = costRef.current;
    if (!(s.source || "").trim()) { if (badge && badge.clear) badge.clear(); return; }
    if (badge && badge.setChecking) badge.setChecking();
    fetch("/api/price", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildEditPayload(s)),
    })
      .then((r) => r.json())
      .then((d) => { if (mine === seq.current && costRef.current) costRef.current.setPrice(d); })
      .catch(() => { if (mine === seq.current && costRef.current) costRef.current.setPrice(null); });
  }, [s]);

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(fireCost, 250);
  }, [fireCost]);

  useEffect(() => {
    if (!visible) return;
    const host = costHost.current;
    if (!host || host.firstChild) return;
    if (window.customElements && window.customElements.get("mg-cost-badge")) {
      const el = document.createElement("mg-cost-badge");
      el.setAttribute("hint", "Pick an image to edit to see the cost.");
      host.appendChild(el);
      costRef.current = el;
      fireCost();
    } else {
      host.textContent = "⚠ Couldn't verify the cost — editing may spend credits.";
      host.className = "gd-cost gd-costfail";
    }
  }, [visible]); // eslint-disable-line react-hooks/exhaustive-deps

  const pickSource = async () => {
    const m = await askPicker({ type: "image" });
    if (m) set({ source: m.media_id });
  };
  const addRef = async () => {
    const m = await askPicker({ type: "image" });
    if (m) setS((old) => ({ ...old, refs: old.refs.concat([{ media_id: m.media_id, thumb: m.thumb }]) }));
  };
  const dropRef = (i) => setS((old) => ({ ...old, refs: old.refs.filter((_, k) => k !== i) }));

  const chooseModel = (k) => {
    const { next, notice } = switchEditModel(s, k);
    setS(next);
    if (notice && window.Toast) window.Toast.show({ kind: "err", ...notice });
  };

  const bankPreset = async () => {
    const id = importTask.trim();
    if (!id) return;
    try {
      const d = await fetch("/api/presets", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: id }),
      }).then((r) => r.json());
      if (d.error) {
        if (window.Toast) window.Toast.show({ kind: "err", title: "Not banked", msg: d.error });
        return;
      }
      setImportTask("");
      const fresh = await fetch("/api/presets").then((r) => r.json());
      setPresets((fresh && fresh.presets) || {});
      if (d.imported) set({ preset: d.imported });
      if (window.Toast) window.Toast.show({ kind: "ok", title: "Banked " + (d.label || d.imported) });
    } catch {
      if (window.Toast) window.Toast.show({ kind: "err", title: "Not banked", msg: "Network error." });
    }
  };

  const run = async () => {
    if (busyRef.current || gate) return;
    busyRef.current = true; setBusy(true);
    const emit = openLine("Submitting…");
    await submitTask("/api/edit", buildEditPayload(s), { label: "Edited", emit });
    busyRef.current = false; setBusy(false);
  };

  if (!visible) return null;
  return (
    <div className="gd-body">
      <div className="gd-row">
        {Object.keys(EDIT_CAPS).map((k) => (
          <button key={k} className={"card" + (s.model === k ? " on" : "")}
            onClick={() => chooseModel(k)}>{EDIT_CAPS[k].label}</button>
        ))}
      </div>

      <label className="gd-lbl">Editing image</label>
      <div className="gd-row">
        <button className="card" onClick={pickSource}>
          {s.source
            ? <img className="gd-refthumb" src={"/thumbs/" + s.source + ".jpg"} alt="" />
            : "▨ Pick"}
        </button>
        {s.source && <button className="gd-mini" onClick={() => set({ source: "" })}>✕</button>}
        <span className="gd-note">· {used}/{caps.max_refs} (@image1 = the image being edited)</span>
      </div>

      <div className="gd-refs">
        {s.source ? (
          <div className="gd-slot">
            <img src={"/thumbs/" + s.source + ".jpg"} alt="" />
            <span className="gd-slottag">@image1</span>
          </div>
        ) : null}
        {s.refs.map((r, i) => (
          <div className="gd-slot" key={r.media_id + i}>
            <img src={r.thumb} alt="" />
            <span className="gd-slottag">{refTag(i)}</span>
            <button className="gd-slotx" onClick={() => dropRef(i)}>×</button>
          </div>
        ))}
        {used < caps.max_refs && (
          <button className="gd-slot dashed" onClick={addRef}>+ ref</button>
        )}
      </div>

      <label className="gd-lbl">Toolbox preset</label>
      <div className="gd-row">
        <select className="gd-sel" value={s.preset} onChange={(e) => set({ preset: e.target.value })}>
          <option value="">None — custom instruction</option>
          {Object.entries(presets).map(([name, p]) => (
            <option key={name} value={name}>{p.label || name}</option>
          ))}
        </select>
        <input className="gd-num wide" placeholder="pixai task id" value={importTask}
          onChange={(e) => setImportTask(e.target.value.replace(/\D/g, ""))} />
        <button className="gd-mini" onClick={bankPreset}
          title="Bank the prompt from one of your pixai.art tasks as a reusable preset">
          + bank
        </button>
      </div>

      <label className="gd-lbl">Instruction</label>
      <textarea className="gd-prompt" rows={3} value={s.instruction}
        placeholder="make it night · put @image2's outfit on @image1 …"
        onChange={(e) => set({ instruction: e.target.value })} />

      <div className="gd-row">
        <span className="gd-lbl">Res</span>
        <select className="gd-sel" value={s.resolution} onChange={(e) => set({ resolution: e.target.value })}>
          {caps.resolutions.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        {caps.qualities.length > 0 && (
          <>
            <span className="gd-lbl">Quality</span>
            <select className="gd-sel" value={s.quality} onChange={(e) => set({ quality: e.target.value })}>
              {caps.qualities.map((q) => <option key={q} value={q}>{q}</option>)}
            </select>
          </>
        )}
        <span className="gd-lbl">Aspect</span>
        <select className="gd-sel" value={s.aspect} onChange={(e) => set({ aspect: e.target.value })}>
          {caps.aspects.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
      </div>

      <div className="gd-go">
        <span ref={costHost} className="gd-cost" />
        <span className="sp" />
        <button className="gen" disabled={!!gate || busy} title={gate || "Submit the edit"}
          onClick={run}>&#10022; Edit</button>
      </div>
      {gate && <div className="gd-note">{gate}</div>}

      <ResultLines lines={lines} />
    </div>
  );
}

export function ResultLines({ lines }) {
  return (
    <div className="gd-results">
      {lines.map((r) => (
        <div key={r.id} className={"gd-res " + r.kind}>
          {r.kind === "run" ? "⏳ " : r.kind === "ok" ? "✔ " : "✕ "}{r.text}
          {r.media && r.media.map((mid) => (
            <a key={mid} href={"/full/" + mid} target="_blank" rel="noreferrer">
              <img src={"/thumbs/" + mid + ".jpg"} alt="" />
            </a>
          ))}
        </div>
      ))}
    </div>
  );
}
