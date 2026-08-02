import React, { useCallback, useEffect, useRef, useState } from "react";
import useGenerate from "../gen/useGenerate.js";
import {
  ASPECTS, MODES, SIZES, dims, goGate, loraIncompat, loraRange, loraStep,
} from "../gen/genCore.js";
import ModelFlyout from "./ModelFlyout.jsx";
import EditTab from "./EditTab.jsx";
import FixTab from "./FixTab.jsx";
import FiltersPanel from "./FiltersPanel.jsx";
import RunsReel, { isRunningJob } from "./RunsReel.jsx";
import { askPicker, isPickerOpen } from "./PickerHost.jsx";
import "../styles/dock.css";

/* The Generate DOCK — the designed bottom-center glass reshell of the pilot's
   Generate drawer (design spec: Frontend Gallery.dc.html §§ dock 708–1224,
   README dock bullets, drift items 8 + 22).

   MACHINERY IS UNCHANGED. Image tab = React port riding the classic endpoints
   (useGenerate/genCore/submitTask); Edit/Fixer = EditTab/FixTab; Enhance =
   the art-filters compare panel; Video tab = the SHARED <mg-generate-drawer>
   web component. Every submit path, the <mg-cost-badge> pricing, the request
   contract ({tab, mid, thumb, nonce}) and the videoPrefill hand-off all keep
   firing exactly as before — this file only re-shells the chrome around them.

   THE DRAWER IS NEVER UNMOUNTED. It hides with CSS (the host's open/closing
   classes on .mgx-dock-host drive mgDockIn/mgDockOut), because the shared
   video component's disconnectedCallback sweeps its poll timers -- unmounting
   on close would orphan an in-flight (already charged) video task from every
   surface, and a v4.0 15s render is ~210,000 credits. */

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
  return <div ref={host} className="mgdock-videohost" style={{ display: visible ? "" : "none" }} />;
}

export default function GenerateDrawer({ open, onClose, account, request }) {
  const [tab, setTab] = useState("image");
  const [sub, setSub] = useState("edit");          // edit | fix | enhance
  const [expanded, setExpanded] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [promptFocus, setPromptFocus] = useState(false);
  const [editSource, setEditSource] = useState("");
  const [videoPrefill, setVideoPrefill] = useState(null);
  const [flyOpen, setFlyOpen] = useState(false);
  const [flyKind, setFlyKind] = useState("base");
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Lineage: "reusing settings from run #N" -- a LOCAL annotation only (no
  // backend concept exists for it), set at prefill time and cleared the moment
  // a new submission goes out. See prefillFromRun below + the composer chip.
  const [reuseFrom, setReuseFrom] = useState(null);   // {jobId, tag}
  const costRef = useRef(null);
  const costHost = useRef(null);
  const deselectRef = useRef(null);
  const drawerRef = useRef(null);
  const g = useGenerate({ costRef });
  const { s, set } = g;
  const loraCap = account && account.lora_cap != null ? account.lora_cap : null;
  const gate = goGate(s, loraCap);

  /* ---- REAL runs data: GET /api/jobs, generate-type only. The reel, the
     header label and the peek pill all derive from this one list. Refreshed
     by the same three completion channels App.jsx listens on, plus a slow
     poll while the dock is open or anything is still running. ---- */
  const [jobs, setJobs] = useState([]);
  const fetchJobs = useCallback(() => {
    fetch("/api/jobs")
      .then((r) => r.json())
      .then((d) => setJobs(((d && d.jobs) || []).filter((j) => j.type === "generate")))
      .catch(() => {});
  }, []);
  useEffect(() => {
    fetchJobs();
    const onEvt = () => fetchJobs();
    window.addEventListener("mg-gen-done", onEvt);
    document.addEventListener("mg-submit", onEvt);
    document.addEventListener("mg-result", onEvt);
    return () => {
      window.removeEventListener("mg-gen-done", onEvt);
      document.removeEventListener("mg-submit", onEvt);
      document.removeEventListener("mg-result", onEvt);
    };
  }, [fetchJobs]);
  const runningCount = jobs.filter(isRunningJob).length;
  useEffect(() => {
    if (!open && !runningCount) return;
    const t = setInterval(fetchJobs, open ? 4000 : 8000);
    return () => clearInterval(t);
  }, [open, runningCount, fetchJobs]);

  /* ---- measurement (DC measureDock/fitReel: a layout contract, not
     decoration). The dock never rises above the separator bar EXCEPT when
     expanded or the prompt is long, when it may grow to 100vh-28. ---- */
  const [metrics, setMetrics] = useState({ sepBottom: 260, vh: 800 });
  useEffect(() => {
    const measure = () => {
      const sep = document.querySelector(".mgx-sep");
      const sb = sep ? Math.round(sep.getBoundingClientRect().bottom) : 260;
      const vh = window.innerHeight;
      setMetrics((m) => (m.sepBottom === sb && m.vh === vh ? m : { sepBottom: sb, vh }));
    };
    measure();
    window.addEventListener("resize", measure);
    const hdr = document.querySelector(".mgx-hdr");
    let ro = null;
    if (hdr && typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(measure);
      ro.observe(hdr);
    }
    return () => {
      window.removeEventListener("resize", measure);
      if (ro) ro.disconnect();
    };
  }, [open]);

  const promptLines = Math.ceil((s.prompt || "").length / 76);
  const longPrompt = promptLines > 4;
  const capH = (expanded || longPrompt)
    ? metrics.vh - 28
    : metrics.vh - metrics.sepBottom - 14;
  const reelRoom = (metrics.vh - metrics.sepBottom - 14) - 56 - 118 - 46;
  const reelTier = expanded
    ? (metrics.vh < 760 ? 84 : 104)
    : (metrics.vh < 620 ? 64 : metrics.vh < 820 ? 96 : 132);
  const reelH = Math.max(44, Math.min(reelTier, reelRoom));
  const reelVisible = !expanded && reelRoom >= 60;
  const chrome = 46 + (expanded ? 0 : reelH + 46) + (expanded ? 330 : 0) + 96;
  const promptMax = Math.max(2, Math.min(14, Math.floor((capH - chrome) / 25)));
  const promptRows = Math.max(2, Math.min(promptMax, promptLines + (promptFocus ? 1 : 0)));

  /* <mg-cost-badge> is a web component; mount it once into the image tab's
     host. If the script never loaded there is NO price surface, so say so in
     plain text rather than leaving a blank space next to a live Generate
     button. (Unchanged machinery.) */
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

  /* External entry points into the drawer (the lightbox's Edit / To Video
     buttons and the #edit/#video deep links -- classic's Gen.openEdit()/
     Gen.addVideoRefs()). `request` is a one-shot object (a fresh nonce each
     time, set by the caller), so asking for the SAME image twice in a row
     still re-fires this effect. (Unchanged contract; Edit now also lands on
     the Edit sub-tab of the merged Edit tab.) */
  useEffect(() => {
    if (!request) return;
    if (request.tab === "edit") {
      setTab("edit");
      setSub("edit");
      setEditSource(request.mid);
    } else if (request.tab === "video") {
      setTab("video");
      // A midless request is the #video deep link: land on the tab, prefill nothing.
      if (request.mid) setVideoPrefill({ mode: "i2v", images: [{ media_id: request.mid, thumb: request.thumb }] });
    }
  }, [request]);

  /* Filters and the model/LoRA flyout are floating overlays; letting both open
     at once would stack them. Opening either closes the other; closing the
     dock itself (the × button, outside-click via the host, or the Escape
     ladder below) closes both. */
  const closeDrawer = useCallback(() => {
    setFlyOpen(false);
    setFiltersOpen(false);
    setExpanded(false);
    onClose();
  }, [onClose]);
  const toggleFilters = useCallback(() => {
    setFlyOpen(false);
    setFiltersOpen((v) => !v);
  }, []);

  /* The HOST can close the dock without going through closeDrawer (its
     outside-click closer, the banner toggles). The floating overlays now live
     OUTSIDE the aside (see below), so they must fold when the dock does. */
  useEffect(() => {
    if (open) return;
    setFlyOpen(false);
    setFiltersOpen(false);
    setExpanded(false);
  }, [open]);

  /* Escape closes the TOPMOST layer only: picker → filters → flyout →
     collapse the settings → the dock (the DC's Esc chain, innermost first). */
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (isPickerOpen()) return;              // the picker handles its own Escape
      if (filtersOpen) { setFiltersOpen(false); return; }
      if (flyOpen) { setFlyOpen(false); return; }
      if (expanded) { setExpanded(false); return; }
      closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtersOpen, flyOpen, expanded, closeDrawer]);

  const onBasePick = useCallback((row) => {
    setFlyOpen(false);                          // single-select closes, classic
    g.applyModelRow(row);
  }, [g]);

  /* REUSE: a done reel tile's real prefill (owner correction, 2026-08-02) --
     fetches the SAME /api/next/detail/<media_id> Details/Lightbox already call,
     and maps its row onto the real composer setters. Prefills only -- never
     submits; the user reviews/edits, then clicks Generate themselves.

     Fields mapped: model, prompt, negative, frame (customW/customH set directly
     from the row's real width/height -- an exact reproduction, more faithful
     than reverse-guessing which aspect/size stop it came from), steps, cfg, seed.

     MODEL is a two-hop resolve (2026-08-02, fixes a verify-flagged bug found
     live: reuse silently failed to restore the model on every click, old or
     new gens alike). The catalog's row.model_id is the VERSION PixAI actually
     rendered with, not the base model id applyModelRow expects (it calls
     /api/model-version?model_id=X to enumerate a BASE model's versions -- fed
     a version id, that returns nothing and the reuse silently keeps whatever
     model was already selected). /api/model-version?version_id=X does the
     reverse lookup first (core.resolve_model_base_id), THEN applyModelRow
     resolves that real base id server-side the same way a fresh market pick
     does -- never trusts a stale id either way. A run whose model can't be
     resolved (PixAI-side removal, an unconfigured MODEL_DETAIL_HASH) leaves
     the composer's model untouched rather than showing the old wrong-id
     failure toast for a case that isn't the user's mistake.

     LoRAs are DELIBERATELY NOT reconstructed: the catalog's `loras` column is a
     display-only "Name:0.7, Name2:0.5" string (moonglade_backup.resolve_loras)
     with no model_id/version_id in it -- fuzzy-matching a LoRA back from its
     name would risk wiring a DIFFERENT LoRA into a paid submission on a name
     collision, which the spend-safety contract in gen/genCore.js explicitly
     guards against ("never let a substitution pass unremarked"). Proposed,
     disclosed deviation from the literal "loras+weights" in the click-wiring
     spec -- see the report.

     model_id resolution runs FIRST and is awaited: applyModelRow can apply the
     newly-picked model's own preset (negative/steps/cfg) as a side effect, and
     the run's own real values must win over that preset, not be clobbered by
     it. */
  const prefillFromRun = useCallback(async (jobId, mediaId) => {
    if (!mediaId) return;
    let row;
    try {
      const r = await fetch("/api/next/detail/" + encodeURIComponent(mediaId));
      const d = await r.json();
      if (d.error || !d.row) {
        if (window.Toast) window.Toast.show({ kind: "err", title: "Couldn't load that run's settings", msg: d.error || "" });
        return;
      }
      row = d.row;
    } catch {
      if (window.Toast) window.Toast.show({ kind: "err", title: "Couldn't load that run's settings", msg: "Network error." });
      return;
    }
    if (row.model_id) {
      let baseId = "";
      try {
        const rv = await fetch("/api/model-version?version_id=" + encodeURIComponent(row.model_id));
        const dv = await rv.json();
        baseId = (dv && dv.model_id) || "";
      } catch { /* soft-fail: leave the composer's model untouched below */ }
      if (baseId) {
        await g.applyModelRow({ model_id: baseId, title: row.model_name || row.model_id, preview_url: "" });
      }
    }
    g.set({
      prompt: row.prompt_full || row.prompt_preview || "",
      negative: row.negative_prompt || "",
      customW: row.width ? String(row.width) : "",
      customH: row.height ? String(row.height) : "",
      steps: row.steps || "",
      cfg: row.cfg_scale || "",
      seed: row.seed || "",
    });
    setTab("image");
    setExpanded(true);
    setReuseFrom({ jobId, tag: "#" + String(jobId || "").slice(-4) });
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

  const d = dims(s);
  const custom = !!(parseInt(s.customW, 10) > 0 && parseInt(s.customH, 10) > 0);
  const frameSummary = d.width + " × " + d.height + " px" + (s.count > 1 ? " · " + s.count + " images" : "");
  const modelShort = m ? (m.resolving ? "Resolving…" : m.title) : "Pick a model";

  /* The peek pill can only OPEN the dock through the host's own toggle verbs;
     the drawer has no openDock prop, so it forwards the click to a real
     [data-dock-toggle] launcher (Banner/SeparatorBar) — the same code path a
     user click takes, no second open mechanism invented. */
  const openViaToggle = () => {
    const els = document.querySelectorAll("[data-dock-toggle]");
    for (const el of els) {
      if (!el.classList.contains("mgdock-peek")) { el.click(); return; }
    }
  };

  const reelLabel = runningCount ? "Making" : "Runs";
  const reelNote = runningCount
    ? runningCount + (runningCount === 1 ? " image resolving — it sharpens as it lands" : " images resolving — they sharpen as they land")
    : (historyOpen ? "grouped by day — click any run to reuse its settings" : "today — click any run to reuse its settings");

  const stepsVal = s.steps === "" ? 25 : Number(s.steps);
  const cfgVal = s.cfg === "" ? 7 : Number(s.cfg);

  return (
    <>
      {/* PEEK PILL — shown only when the dock is fully closed AND runs live */}
      {!open && runningCount > 0 && (
        <div className="mgdock-peek" data-dock-toggle="1" onClick={openViaToggle}
          title="Still running — open the dock to watch them resolve">
          <span className="mgdock-eclipse"><span /></span>
          <div className="mgdock-peektxt">{runningCount} making</div>
        </div>
      )}

      {/* expanded scrim: click collapses the settings */}
      {open && expanded && (
        <div className="mgdock-scrim" title="Collapse the settings"
          onClick={() => setExpanded(false)} />
      )}

      {/* Stays MOUNTED always and animates via the HOST's open/closing classes
          (.mgx-dock-host drives mgDockIn/mgDockOut + the 360ms deferred
          unmount window). `inert` keeps the hidden dock out of tab order. */}
      <aside ref={drawerRef}
        className={"mgdock" + (expanded ? " expanded" : "")}
        role="dialog" aria-label="Generate"
        aria-hidden={!open} inert={open ? undefined : ""}
        style={{ maxHeight: Math.max(180, capH) + "px" }}>
        <div className="mgdock-glow" aria-hidden="true" />

        {/* ---- HEADER: runs label · note · tab strip · History · × ---- */}
        <div className="mgdock-head">
          <span className="mgdock-runslabel" style={reelVisible ? null : { display: "none" }}>{reelLabel}</span>
          <span className="mgdock-runsnote" style={reelVisible ? null : { display: "none" }}>{reelNote}</span>
          <span className="sp" />
          <div className="mgdock-tabs">
            {[["image", "Image", "Generate images"],
              ["edit", "Edit", "Edit · Fixer · Enhance"],
              ["video", "Video", "Generate video"]].map(([k, l, t]) => (
              <button key={k} type="button" title={t}
                className={"mgdock-tab" + (tab === k ? " on" : "")}
                onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>
          <button type="button" className={"mgdock-hist" + (historyOpen ? " on" : "")}
            onClick={() => setHistoryOpen((v) => !v)}
            title="Fold yesterday's runs into the reel">
            {historyOpen ? "Hide history" : "History"}
          </button>
          <button type="button" className="mgdock-x" onClick={closeDrawer}
            title="Close the dock — runs keep going">×</button>
        </div>

        {/* ---- DOCK BODY: reel · per-tab surface. Safety-valve scroll for
             short windows only — the composer footer never scrolls. ---- */}
        <div className="mgdock-body">
          {reelVisible && <RunsReel jobs={jobs} historyOpen={historyOpen} reelH={reelH} onPrefill={prefillFromRun} />}

          {tab === "image" && expanded && (
            <div className="mgdock-slabs">
              {/* SLAB 1 — MODEL & LORAS */}
              <div className="mgdock-slab" style={{ animationDelay: "0ms" }}>
                <div className="mgdock-lbl">MODEL &amp; LORAS</div>
                <button type="button" className={"mgdock-modelrow" + (m ? "" : " empty")}
                  onClick={() => { setFiltersOpen(false); setFlyKind("base"); setFlyOpen(!flyOpen); }}
                  title="Browse the model catalog">
                  {m && m.thumb ? <img className="mgdock-modelthumb" src={m.thumb} alt="" /> : <span className="mgdock-modelthumb ph" />}
                  <span className="mgdock-modelname">{modelShort}</span>
                  <span className="sp" />
                  <span className="mgdock-browse">browse</span>
                </button>
                {m && m.versions && m.versions.length > 1 && (
                  <select className="gd-sel" value={m.version_id}
                    onChange={(e) => g.pickVersion(e.target.value)}>
                    {m.versions.map((v) => (
                      <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>
                    ))}
                  </select>
                )}
                {m && m.preset && m.preset.sampler ? (
                  <div className="mgdock-presetnote">
                    {m.title} ships its author's preset — applied on pick · sampler {m.preset.sampler}
                  </div>
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
                <button type="button" className="mgdock-addlora"
                  onClick={() => { setFiltersOpen(false); setFlyKind("lora"); setFlyOpen(!flyOpen); }}>
                  + Add LoRA{loraCap != null ? ` ${s.loras.length} / ${loraCap}` : s.loras.length ? " " + s.loras.length : ""}
                </button>
                <div className="mgdock-refrow">
                  <button type="button" className={"mgdock-refslot" + (s.ref ? " filled" : "")}
                    onClick={pickRef} title="Pick from your gallery">
                    {s.ref ? <img src={s.ref.thumb} alt="" /> : "+ ref"}
                  </button>
                  {s.ref && (
                    <>
                      <span className="mgdock-lbl">STRENGTH</span>
                      <input type="range" min="0.1" max="1" step="0.05" value={s.refStrength}
                        onChange={(e) => set({ refStrength: e.target.value })} />
                      <b className="gd-w">{Number(s.refStrength).toFixed(2)}</b>
                      <button className="gd-mini" onClick={() => set({ ref: null })}>&times;</button>
                    </>
                  )}
                </div>
              </div>

              {/* SLAB 2 — FRAME */}
              <div className="mgdock-slab" style={{ animationDelay: "60ms" }}>
                <div className="mgdock-lbl">FRAME</div>
                <div className="mgdock-ratios">
                  {ASPECTS.map(([label, r]) => {
                    const on = !s.customW && !s.customH && Math.abs(s.aspect - r) < 0.001;
                    const gw = r >= 1 ? 19 : Math.max(6, Math.round(19 * r));
                    const gh = r >= 1 ? Math.max(6, Math.round(19 / r)) : 19;
                    return (
                      <button key={label} type="button"
                        className={"mgdock-ratio" + (on ? " on" : "")}
                        onClick={() => set({ aspect: r, customW: "", customH: "" })}
                        title={label}>
                        <i style={{ width: gw, height: gh }} />
                        <span>{label}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="mgdock-lbl">SIZE · LONG EDGE</div>
                <div className="mgdock-stops">
                  {SIZES.map((n, i) => (
                    <button key={n} type="button"
                      className={"mgdock-stop" + (!custom && s.size === n ? " on" : "")}
                      onClick={() => set({ size: n, customW: "", customH: "" })}
                      title={n + "px"}>
                      {["S", "M", "L", "XL"][i] || n}
                    </button>
                  ))}
                </div>
                <div className="mgdock-customrow">
                  <input className={"mgdock-custom" + (custom ? " on" : "")} placeholder="W" value={s.customW}
                    onChange={(e) => set({ customW: e.target.value.replace(/\D/g, "") })} />
                  ×
                  <input className={"mgdock-custom" + (custom ? " on" : "")} placeholder="H" value={s.customH}
                    onChange={(e) => set({ customH: e.target.value.replace(/\D/g, "") })} />
                  <span className="mgdock-note-sm">overrides</span>
                </div>
                <div className="mgdock-dims">
                  → {d.width} × {d.height} px{custom ? <span className="mauve"> · custom wins</span> : null}
                </div>
                <div className="mgdock-lbl">COUNT</div>
                <div className="mgdock-stops">
                  {[1, 2, 3, 4].map((n) => (
                    <button key={n} type="button"
                      className={"mgdock-stop" + (s.count === n ? " on" : "")}
                      onClick={() => set({ count: n })}>{n}</button>
                  ))}
                </div>
              </div>

              {/* SLAB 3 — TUNING */}
              <div className="mgdock-slab" style={{ animationDelay: "120ms" }}>
                <div className="mgdock-lbl">TUNING · {(MODES.find(([v]) => v === s.mode) || ["", s.mode])[1]}</div>
                <div className="mgdock-modebars">
                  {MODES.map(([v, l], i) => (
                    <button key={v} type="button" title={l}
                      className={"mgdock-modebar" + (i <= MODES.findIndex(([x]) => x === s.mode) ? " on" : "")}
                      onClick={() => set({ mode: v })} />
                  ))}
                </div>
                <div className="mgdock-sliderrow">
                  <span className="mgdock-lbl">STEPS</span>
                  <input type="range"
                    min={stepsR.min != null ? stepsR.min : 1}
                    max={stepsR.max != null ? stepsR.max : 150}
                    step="1" value={stepsVal}
                    disabled={m && m.compat_steps === false}
                    title={m && m.compat_steps === false ? (m.title + " doesn't take STEPS") : "Sampling steps"}
                    onChange={(e) => set({ steps: e.target.value })} />
                  <input className="gd-num" value={s.steps} disabled={m && m.compat_steps === false}
                    placeholder={stepsR.min != null ? `${stepsR.min}–${stepsR.max}` : "25"}
                    onChange={(e) => set({ steps: e.target.value.replace(/\D/g, "") })}
                    onBlur={(e) => set({ steps: clampField(e.target.value, stepsR, 1, 150) })} />
                </div>
                <div className="mgdock-sliderrow">
                  <span className="mgdock-lbl">CFG</span>
                  <input type="range"
                    min={cfgR.min != null ? cfgR.min : 1}
                    max={cfgR.max != null ? cfgR.max : 30}
                    step="0.5" value={cfgVal}
                    disabled={m && m.compat_cfg === false}
                    title={m && m.compat_cfg === false ? (m.title + " doesn't take CFG") : "CFG scale"}
                    onChange={(e) => set({ cfg: e.target.value })} />
                  <input className="gd-num" value={s.cfg} disabled={m && m.compat_cfg === false}
                    placeholder={cfgR.min != null ? `${cfgR.min}–${cfgR.max}` : "auto"}
                    onChange={(e) => set({ cfg: e.target.value.replace(/[^\d.]/g, "") })}
                    onBlur={(e) => set({ cfg: clampField(e.target.value, cfgR, 1, 30) })} />
                </div>
                <div className="mgdock-sliderrow">
                  <span className="mgdock-lbl">SEED</span>
                  <input className="mgdock-seed" value={s.seed} placeholder="blank = random"
                    onChange={(e) => set({ seed: e.target.value.replace(/[^\d-]/g, "").replace(/(?!^)-/g, "") })} />
                </div>
                <div className="mgdock-chips">
                  <button type="button"
                    className={"mgdock-chip" + (s.boosters.face ? " on" : "")}
                    onClick={() => set({ boosters: { ...s.boosters, face: !s.boosters.face } })}>
                    Face Fix
                  </button>
                  <button type="button"
                    className={"mgdock-chip" + (s.boosters.quality ? " on" : "")}
                    title="Prefixes PixAI's Masterpiece quality tag"
                    onClick={() => set({ boosters: { ...s.boosters, quality: !s.boosters.quality } })}>
                    Quality Tag
                  </button>
                  <button type="button"
                    className={"mgdock-chip" + (s.boosters.hires ? " on" : "")}
                    disabled={m && m.compat_upscale === false}
                    title={m && m.compat_upscale === false
                      ? "This model's version does not support upscaling"
                      : "Enhance Details — PixAI's own 1.5× / 0.6 denoise pass"}
                    onClick={() => set({ boosters: { ...s.boosters, hires: !s.boosters.hires } })}>
                    Enhance Details
                  </button>
                </div>
                <label className="mgdock-sw" title="Faster queue · costs extra">
                  <input type="checkbox" checked={s.highPriority}
                    onChange={(e) => set({ highPriority: e.target.checked })} />
                  <span className="mgdock-swtrack"><i /></span>
                  <span className="mgdock-swlab">High priority</span>
                </label>
                <label className="mgdock-sw" title="PixAI's prompt helper (on by default, like the classic drawer)">
                  <input type="checkbox" checked={s.promptHelper}
                    onChange={(e) => set({ promptHelper: e.target.checked })} />
                  <span className="mgdock-swtrack"><i /></span>
                  <span className="mgdock-swlab">Prompt helper</span>
                </label>
              </div>
            </div>
          )}

          {tab === "image" && gate && <div className="mgdock-note">{gate}</div>}

          {tab === "image" && g.results.length > 0 && (
            <div className="gd-results mgdock-results">
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
          )}

          {/* EditTab/FixTab stay MOUNTED across tab switches (their `visible`
              prop toggles a null return) so a half-built edit survives a
              detour to Image/Video — the pre-reshell contract. Only the wrap
              chrome hides. */}
          <div className="mgdock-editwrap" style={{ display: tab === "edit" ? "" : "none" }}>
              <div className="mgdock-subtabs">
                {[["edit", "Edit", "Edit Pro / Reference Pro — instruction edits"],
                  ["fix", "Fixer", "Box a hand or face — PixAI repairs it (always spends)"],
                  ["enhance", "Enhance", "Art filters — free, in your browser"]].map(([k, l, t]) => (
                  <button key={k} type="button" title={t}
                    className={"mgdock-seg" + (sub === k ? " on" : "")}
                    onClick={() => setSub(k)}>{l}</button>
                ))}
              </div>
              <EditTab visible={tab === "edit" && sub === "edit"} initialSource={editSource} />
              <FixTab visible={tab === "edit" && sub === "fix"} />
              {tab === "edit" && sub === "enhance" && (
                <div className="mgdock-slab mgdock-enhance">
                  <div className="mgdock-lbl">ART FILTERS · FREE, NO GENERATION</div>
                  <button type="button" className="mgdock-openfilters" onClick={toggleFilters}>
                    ◉ Open filters
                  </button>
                  <div className="mgdock-enhancecopy">
                    Filters composite in your browser over the original — no
                    credits, no request, works offline. Compare against the
                    original, then save to your library or send to image gen.
                  </div>
                </div>
              )}
          </div>

          <VideoTab visible={tab === "video"} prefillRequest={videoPrefill} />
        </div>

        {/* ---- COMPOSER FOOTER (image tab): expand · composer · cost+Generate.
             Edit/Fixer/Enhance and Video keep their own submit rows — their
             machinery (EditTab/FixTab/the shared video component) owns them. */}
        {tab === "image" && (
          <div className="mgdock-foot">
            <button type="button" className="mgdock-expand"
              onClick={() => setExpanded((v) => !v)}
              title={expanded ? "Collapse the settings" : "Expand the settings"}>
              <span className={"mgdock-caret" + (expanded ? " flip" : "")}>▲</span>
            </button>
            <div className={"mgdock-composer" + (promptFocus ? " focus" : "")}>
              <div className="mgdock-composer-top">
                <button type="button" className={"mgdock-modelchip" + (m ? "" : " empty")}
                  onClick={() => { setFiltersOpen(false); setFlyKind("base"); setFlyOpen(!flyOpen); }}
                  title="Pick the base model">
                  {m && m.thumb ? <img src={m.thumb} alt="" /> : <span className="mgdock-chipph" />}
                  <span>{modelShort}</span>
                </button>
                <span className="mgdock-frames">{frameSummary}</span>
                {reuseFrom && (
                  <button type="button" className="mgdock-reusefrom"
                    onClick={() => setReuseFrom(null)}
                    title={"Prompt & core settings prefilled from run " + reuseFrom.tag + " — click to clear"}>
                    ↺ from {reuseFrom.tag} <span>&times;</span>
                  </button>
                )}
                <span className="sp" />
              </div>
              <textarea className="mgdock-prompt" rows={promptRows} value={s.prompt}
                placeholder="Describe your image…"
                onChange={(e) => set({ prompt: e.target.value })}
                onFocus={() => setPromptFocus(true)}
                onBlur={() => setPromptFocus(false)} />
              {expanded && (
                <div className="mgdock-negrow">
                  <span className="mgdock-lbl">NEGATIVE</span>
                  <textarea className="mgdock-neg" rows={1} value={s.negative}
                    placeholder="lowres, text"
                    disabled={m && m.compat_neg === false}
                    onChange={(e) => set({ negative: e.target.value })} />
                </div>
              )}
            </div>
            <div className="mgdock-gocol">
              <span ref={costHost} className="gd-cost" />
              {account && account.credits != null && (
                <span className="mgdock-subline">{Number(account.credits).toLocaleString()} credits</span>
              )}
              <button type="button" className={"mgdock-gen" + (gate || g.busy ? " off" : "")}
                disabled={!!gate || g.busy}
                title={gate ? "Pick a model and write a prompt first" : "Submit — this spends credits or a card"}
                onClick={() => { setReuseFrom(null); g.generate(loraCap); }}>
                <span>&#10022; Generate</span>
              </button>
            </div>
          </div>
        )}
      </aside>

      {/* Floating overlays live OUTSIDE the aside: the dock's backdrop-filter
          makes it a containing block for fixed descendants, which would trap
          both panels inside its 22px-rounded clip. They stay inside the
          .mgx-dock-host wrapper, so the host's outside-click closer still
          counts them as "inside the dock". */}
      <ModelFlyout
        open={flyOpen} kind={flyKind} setKind={setFlyKind}
        baseType={m ? m.model_type : ""}
        onBasePick={onBasePick} onLoraPick={onLoraPick}
        onClose={() => setFlyOpen(false)}
        deselectRef={deselectRef}
      />
      <FiltersPanel open={filtersOpen} onClose={() => setFiltersOpen(false)} drawerRef={drawerRef}
        onSendToEdit={(mid) => { setEditSource(mid); setTab("edit"); setSub("edit"); }} />
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
