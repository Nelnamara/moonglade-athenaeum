import React, { useCallback, useEffect, useRef, useState } from "react";
import useGenerate from "../gen/useGenerate.js";
import {
  ASPECTS, MODES, SIZES, goGate, loraIncompat, loraRange, loraStep,
} from "../gen/genCore.js";
import ModelFlyout from "./ModelFlyout.jsx";
import EditTab from "./EditTab.jsx";
import FixTab from "./FixTab.jsx";
import FiltersPanel from "./FiltersPanel.jsx";
import { askPicker, isPickerOpen } from "./PickerHost.jsx";

/* The pilot's Generate drawer. Image tab = React port riding the classic
   endpoints; Video tab = the SHARED <mg-generate-drawer> web component.

   THE DRAWER IS NEVER UNMOUNTED. It hides with CSS instead, because the shared
   video component's disconnectedCallback sweeps its poll timers -- unmounting on
   close would orphan an in-flight (already charged) video task from every
   surface, and a v4.0 15s render is ~210,000 credits. Same reason the Loom
   renders it once outside its tab-conditional JSX. */

function VideoTab({ visible, prefillRequest }) {
  const host = useRef(null);
  const el = useRef(null);
  useEffect(() => {
    if (!host.current || host.current.firstChild) return;
    if (!window.customElements || !window.customElements.get("mg-generate-drawer")) {
      host.current.textContent = "The shared video drawer script did not load.";
      return;
    }
    const e = document.createElement("mg-generate-drawer");
    host.current.appendChild(e);
    el.current = e;
  }, []);
  // The lightbox's "To Video" hand-off (classic's Gen.addVideoRefs): a single
  // image reference always prefills as i2v (first-frame), matching classic's
  // refs.length>1?'r2v':'i2v' for the one-image case.
  useEffect(() => {
    if (!prefillRequest || !el.current || typeof el.current.prefill !== "function") return;
    el.current.prefill(prefillRequest);
  }, [prefillRequest]);
  return <div ref={host} style={{ display: visible ? "" : "none" }} />;
}

export default function GenerateDrawer({ open, onClose, account, request }) {
  const [tab, setTab] = useState("image");
  const [editSource, setEditSource] = useState("");
  const [videoPrefill, setVideoPrefill] = useState(null);
  const [flyOpen, setFlyOpen] = useState(false);
  const [flyKind, setFlyKind] = useState("base");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const costRef = useRef(null);
  const costHost = useRef(null);
  const deselectRef = useRef(null);
  const drawerRef = useRef(null);
  const g = useGenerate({ costRef });
  const { s, set } = g;
  const loraCap = account && account.lora_cap != null ? account.lora_cap : null;
  const gate = goGate(s, loraCap);

  /* <mg-cost-badge> is a web component; mount it once into the image tab's host.
     If the script never loaded there is NO price surface, so say so in plain
     text rather than leaving a blank space next to a live Generate button. */
  useEffect(() => {
    if (!open || tab !== "image") return;
    const host = costHost.current;
    if (!host || host.firstChild) return;
    if (window.customElements && window.customElements.get("mg-cost-badge")) {
      const el = document.createElement("mg-cost-badge");
      host.appendChild(el);
      costRef.current = el;
      g.refreshPrice();
    } else {
      host.textContent = "⚠ Couldn't verify the cost — generating may spend credits.";
      host.className = "gd-cost gd-costfail";
    }
  }, [open, tab, g]);

  /* External entry points into the drawer (currently: the lightbox's Edit / To
     Video buttons -- classic's Gen.openEdit()/Gen.addVideoRefs()). `request`
     is a one-shot object (a fresh nonce each time, set by the caller), so
     asking for the SAME image twice in a row still re-fires this effect. */
  useEffect(() => {
    if (!request) return;
    if (request.tab === "edit") {
      setTab("edit");
      setEditSource(request.mid);
    } else if (request.tab === "video") {
      setTab("video");
      // A midless request is the #video deep link: land on the tab, prefill nothing.
      if (request.mid) setVideoPrefill({ mode: "i2v", images: [{ media_id: request.mid, thumb: request.thumb }] });
    }
  }, [request]);

  /* Filters and the model/LoRA flyout are both side-by-side overlays anchored
     left of the drawer -- letting both open at once would stack them on top
     of each other. Opening either closes the other; closing the drawer
     itself (scrim, the × button, or the Escape ladder below) closes both. */
  const closeDrawer = useCallback(() => {
    setFlyOpen(false);
    setFiltersOpen(false);
    onClose();
  }, [onClose]);
  const toggleFilters = useCallback(() => {
    setFlyOpen(false);
    setFiltersOpen((v) => !v);
  }, []);

  /* Escape closes the TOPMOST layer only: picker, then filters/flyout, then
     the drawer. (The first cut closed the whole drawer when a picker was
     dismissed.) */
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (isPickerOpen()) return;              // the picker handles its own Escape
      if (filtersOpen) { setFiltersOpen(false); return; }
      if (flyOpen) { setFlyOpen(false); return; }
      closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtersOpen, flyOpen, closeDrawer]);

  const onBasePick = useCallback((row) => {
    setFlyOpen(false);                          // single-select closes, classic
    g.applyModelRow(row);
  }, [g]);

  /* multi picker contract: (model, selected). The picker owns its own highlight
     state, so honor its verdict instead of second-guessing from ours. */
  const onLoraPick = useCallback((model, selected) => {
    if (!model || !model.model_id) return;
    if (selected === false) g.removeLora(model.model_id);
    else g.addLora(model);
  }, [g]);

  const removeLora = (modelId) => {
    g.removeLora(modelId);
    if (deselectRef.current) deselectRef.current(modelId);
  };

  const pickRef = async () => {
    const m = await askPicker({ type: "image" });
    if (m) set({ ref: { media_id: m.media_id, thumb: m.thumb } });
  };

  const m = s.model;
  const restr = (m && m.restrictions) || {};
  const stepsR = restr.samplingSteps || {};
  const cfgR = restr.cfgScale || {};
  const [lo, hi] = loraRange(m ? m.model_type : "");

  return (
    <>
      {/* Both stay MOUNTED and animate via a class -- a display toggle cannot
          transition, and display:none next to the slide CSS left the drawer
          open-but-invisible off-screen (shipped broken 2026-07-29). `inert`
          keeps the hidden drawer out of tab order without display:none. */}
      <div className={"gd-scrim" + (open ? " open" : "")} onClick={closeDrawer} />
      <aside ref={drawerRef} className={"gd" + (open ? " open" : "")} role="dialog" aria-label="Generate"
             aria-hidden={!open} inert={open ? undefined : ""}>
        <div className="gd-head">
          <div className="gd-tabs">
            {[["image", "Image"], ["video", "Video"], ["edit", "Edit"],
              ["fix", "Fix"]].map(([k, l]) => (
              <button key={k} className={"card" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{l}</button>
            ))}
            <button className={"card" + (filtersOpen ? " on" : "")} onClick={toggleFilters}
              title="Opens beside the drawer — compare a filter against the original">
              Filters
            </button>
          </div>
          <span className="sp" />
          <button className="card" onClick={closeDrawer} title="Esc">&times;</button>
        </div>

        {tab === "image" && (
          <div className="gd-body">
            <label className="gd-lbl">Prompt</label>
            <textarea className="gd-prompt" rows={4} value={s.prompt}
              placeholder="Describe your image…"
              onChange={(e) => set({ prompt: e.target.value })} />

            <div className="gd-row">
              <button className="card gd-modelbtn" onClick={() => { setFiltersOpen(false); setFlyKind("base"); setFlyOpen(!flyOpen); }}>
                {m && m.thumb ? <img className="gd-modelthumb" src={m.thumb} alt="" /> : null}
                {m ? (m.resolving ? "Resolving…" : m.title) : "none — browse models"}
              </button>
              {m && m.versions && m.versions.length > 1 && (
                <select className="gd-sel" value={m.version_id}
                  onChange={(e) => g.pickVersion(e.target.value)}>
                  {m.versions.map((v) => (
                    <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>
                  ))}
                </select>
              )}
              <button className="card" onClick={() => { setFiltersOpen(false); setFlyKind("lora"); setFlyOpen(!flyOpen); }}>
                + Add LoRA{loraCap != null ? ` ${s.loras.length} / ${loraCap}` : s.loras.length ? " " + s.loras.length : ""}
              </button>
            </div>
            {m && m.preset && m.preset.sampler ? (
              <div className="gd-note">model preset · sampler {m.preset.sampler}</div>
            ) : null}

            {s.loras.map((l) => {
              const bad = loraIncompat(l, m);
              return (
                <div key={l.model_id} className={"gd-lora" + (bad || l.failed ? " bad" : "")}>
                  {l.preview_url ? <img src={l.preview_url} alt="" /> : null}
                  <span className="gd-lora-t" title={l.title}>{l.title}</span>
                  {l.failed ? <span className="gd-warn">failed</span> :
                    !l.version_id ? <span className="gd-note">resolving…</span> : null}
                  {bad ? <span className="gd-warn">wrong architecture</span> : null}
                  {l.trigger_words ? (
                    <button className="gd-mini" title={"Insert: " + l.trigger_words}
                      onClick={() => set({
                        prompt: (s.prompt.trim() ? s.prompt.trim().replace(/,\s*$/, "") + ", " : "")
                                + String(l.trigger_words).replace(/,\s*$/, ""),
                      })}>
                      +words
                    </button>
                  ) : null}
                  <input type="range" min={lo} max={hi} step={loraStep()} value={l.weight}
                    onChange={(e) => g.setLora(l.model_id, { weight: e.target.value })} />
                  <b className="gd-w">{Number(l.weight).toFixed(2)}</b>
                  <button className="gd-mini" onClick={() => removeLora(l.model_id)}>&times;</button>
                </div>
              );
            })}

            <label className="gd-lbl">Negative</label>
            <textarea className="gd-prompt" rows={2} value={s.negative}
              disabled={m && m.compat_neg === false}
              onChange={(e) => set({ negative: e.target.value })} />

            <div className="gd-row">
              {ASPECTS.map(([label, r]) => (
                <button key={label}
                  className={"gd-mini" + (!s.customW && !s.customH && Math.abs(s.aspect - r) < 0.001 ? " on" : "")}
                  onClick={() => set({ aspect: r, customW: "", customH: "" })}>{label}</button>
              ))}
              <select className="gd-sel" value={s.size}
                onChange={(e) => set({ size: Number(e.target.value), customW: "", customH: "" })}>
                {SIZES.map((n) => <option key={n} value={n}>{n}px</option>)}
              </select>
              <input className="gd-num" placeholder="W" value={s.customW}
                onChange={(e) => set({ customW: e.target.value.replace(/\D/g, "") })} />
              ×
              <input className="gd-num" placeholder="H" value={s.customH}
                onChange={(e) => set({ customH: e.target.value.replace(/\D/g, "") })} />
            </div>

            <div className="gd-row">
              <span className="gd-lbl">Steps</span>
              <input className="gd-num" value={s.steps} disabled={m && m.compat_steps === false}
                placeholder={stepsR.min != null ? `${stepsR.min}–${stepsR.max}` : "25"}
                onChange={(e) => set({ steps: e.target.value.replace(/\D/g, "") })}
                onBlur={(e) => set({ steps: clampField(e.target.value, stepsR, 1, 150) })} />
              <span className="gd-lbl">CFG scale</span>
              <input className="gd-num" value={s.cfg} disabled={m && m.compat_cfg === false}
                placeholder={cfgR.min != null ? `${cfgR.min}–${cfgR.max}` : "auto"}
                onChange={(e) => set({ cfg: e.target.value.replace(/[^\d.]/g, "") })}
                onBlur={(e) => set({ cfg: clampField(e.target.value, cfgR, 1, 30) })} />
              <span className="gd-lbl">Seed</span>
              <input className="gd-num wide" value={s.seed} placeholder="random"
                onChange={(e) => set({ seed: e.target.value.replace(/[^\d-]/g, "").replace(/(?!^)-/g, "") })} />
              <span className="gd-lbl">Count</span>
              <select className="gd-sel" value={s.count} onChange={(e) => set({ count: Number(e.target.value) })}>
                {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>

            <div className="gd-row">
              <span className="gd-lbl">Mode</span>
              <select className="gd-sel" value={s.mode} onChange={(e) => set({ mode: e.target.value })}>
                {MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <label className="gd-cb" title="Faster queue · costs extra">
                <input type="checkbox" checked={s.highPriority}
                  onChange={(e) => set({ highPriority: e.target.checked })} />
                High priority (faster · costs extra)
              </label>
              <label className="gd-cb" title="PixAI's prompt helper (on by default, like the classic drawer)">
                <input type="checkbox" checked={s.promptHelper}
                  onChange={(e) => set({ promptHelper: e.target.checked })} />
                Prompt helper
              </label>
            </div>

            <div className="gd-row">
              <button
                className={"gd-chip" + (s.boosters.hires ? " on" : "")}
                disabled={m && m.compat_upscale === false}
                title={m && m.compat_upscale === false
                  ? "This model's version does not support upscaling"
                  : "Enhance Details — PixAI's own 1.5× / 0.6 denoise pass"}
                onClick={() => set({ boosters: { ...s.boosters, hires: !s.boosters.hires } })}>
                Enhance Details
              </button>
              <button
                className={"gd-chip" + (s.boosters.quality ? " on" : "")}
                title="Prefixes PixAI's Masterpiece quality tag"
                onClick={() => set({ boosters: { ...s.boosters, quality: !s.boosters.quality } })}>
                Quality Tag
              </button>
              <button
                className={"gd-chip" + (s.boosters.face ? " on" : "")}
                onClick={() => set({ boosters: { ...s.boosters, face: !s.boosters.face } })}>
                Face Fix
              </button>
            </div>

            <div className="gd-row">
              <button className="card" onClick={pickRef}>
                {s.ref ? <img className="gd-refthumb" src={s.ref.thumb} alt="" /> : "Reference image"}
              </button>
              {s.ref && (
                <>
                  <input type="range" min="0.1" max="1" step="0.05" value={s.refStrength}
                    onChange={(e) => set({ refStrength: e.target.value })} />
                  <b className="gd-w">{Number(s.refStrength).toFixed(2)}</b>
                  <button className="gd-mini" onClick={() => set({ ref: null })}>&times;</button>
                </>
              )}
            </div>

            <div className="gd-go">
              <span ref={costHost} className="gd-cost" />
              <span className="sp" />
              <button className="gen" disabled={!!gate || g.busy}
                title={gate || "Submit — the price badge left is the quote"}
                onClick={() => g.generate(loraCap)}>
                &#10022; Generate
              </button>
            </div>
            {gate && <div className="gd-note">{gate}</div>}

            <div className="gd-results">
              {g.results.map((r) => (
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
          </div>
        )}

        <VideoTab visible={tab === "video"} prefillRequest={videoPrefill} />
        <EditTab visible={tab === "edit"} initialSource={editSource} />
        <FixTab visible={tab === "fix"} />

        <ModelFlyout
          open={flyOpen} kind={flyKind} setKind={setFlyKind}
          baseType={m ? m.model_type : ""}
          onBasePick={onBasePick} onLoraPick={onLoraPick}
          onClose={() => setFlyOpen(false)}
          deselectRef={deselectRef}
        />
        <FiltersPanel open={filtersOpen} onClose={() => setFiltersOpen(false)} drawerRef={drawerRef}
          onSendToEdit={(mid) => { setEditSource(mid); setTab("edit"); }} />
      </aside>
    </>
  );
}

/* Model-published restrictions REPLACE the field's default bounds (the classic's
   gateField); clamp on blur so a value the server would silently rewrite never
   reaches the payload unremarked. */
function clampField(raw, bounds, defMin, defMax) {
  if (raw === "") return "";
  const n = Number(raw);
  if (!isFinite(n)) return "";
  const min = bounds.min != null ? bounds.min : defMin;
  const max = bounds.max != null ? bounds.max : defMax;
  return String(Math.max(min, Math.min(max, n)));
}
