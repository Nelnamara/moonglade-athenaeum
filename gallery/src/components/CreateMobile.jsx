import React, { useCallback, useEffect, useRef, useState } from "react";
import { ASPECTS, dims, goGate, loraIncompat } from "../gen/genCore.js";
import ModelFlyout from "./ModelFlyout.jsx";
import { askPicker } from "./PickerHost.jsx";
import "../styles/create-mobile.css";

/* The Create tab, Image mode (design spec: Moonglade Mobile.dc.html isCreate
   block, lines 109-184 & 936-1007) -- the SECOND real tab this mobile shell
   ships, following Gallery's exact precedent: real logic via a shared hook
   (useGenerate.js, instantiated ONCE in AppMobile.jsx and spread in here as
   props, same reason useLibrary() was lifted there -- state survives a
   Gallery/Create/Control tab switch instead of resetting on remount), a new
   mobile presentation component on top. genCore.js/submitTask.js are riding
   completely unmodified -- this file never reimplements dims/goGate/
   buildPayload/the spend contract, it only calls the same functions
   GenerateDrawer.jsx calls.

   THIS INCREMENT IS IMAGE-MODE ONLY. What's real:
     - every field the design shows for Image mode (prompt, model & LoRA
       summary, aspect chips, the resolved-dims hint, the optional reference
       image + strength) -- each one a real setter on useGenerate's `s`;
     - the model/LoRA browse sheet -- ModelFlyout.jsx mounted AS-IS (the same
       two <mg-model-picker> web components the desktop dock uses), just
       re-anchored to the bottom of the screen the same way dock.css already
       re-anchors it for the desktop dock (create-mobile.css's
       `.cm-modelwrap .mfly` mirrors `.mgx-dock-host .mfly` verbatim);
     - the reference-image picker -- askPicker() from PickerHost.jsx, which
       AppMobile.jsx now also mounts (previously desktop-only; without it
       "+ ref" would silently resolve to null and the field would be a dead
       tap -- see this file's build report for the full disclosure);
     - the cost quote -- the real <mg-cost-badge> custom element, fed by
       useGenerate's real /api/price debounce (refreshPrice()), mounted the
       exact same way GenerateDrawer.jsx mounts it (an imperative DOM handle
       via costRef, never JSX);
     - Generate itself -- the real goGate()/generate() pair, real busy
       state, and a real results feed (the same gd-results/gd-res classes
       GenerateDrawer already uses) so a failed submit shows a real error,
       not a silent no-op. The design's own generate() is a hardcoded
       1400ms setTimeout stub with no error modeling at all -- this wires
       the real spend-safety path instead of porting that stub.

   DELIBERATE DEVIATION from the design's literal click-wiring (disclosed,
   not silent): the DC's `openModelPalette` always opens the palette on the
   MODEL pane (`paletteKind: 'model'`); its only wired route to the LoRA pane
   is a "+ add" button that lives in the (deferred, not-built-this-increment)
   Advanced screen. Shipping the literal wiring would make LoRA add/remove
   completely unreachable this increment. Instead the "Model & LoRAs" row
   opens on the model pane and a small "+ Add LoRA" row opens straight to the
   LoRA pane -- both routes land on the SAME ModelFlyout sheet, which already
   has its own Models/LoRAs toggle (kind), so nothing new was invented, only
   an extra entry point into a mechanism that already exists.

   DEFERRED to the Advanced screen (its own separate increment, not built
   here, matching the design's own `advSummary` grouping): LoRA weight
   sliders, the SIZE long-edge stops + custom W/H override, steps/cfg/seed/
   mode, the three boosters, and the negative prompt. Until that screen
   ships, every request goes out with GEN_DEFAULTS' real values for those
   fields (size 1024, mode "auto", steps/cfg auto, boosters off, negative
   blank) -- honest defaults, not placeholders; nothing sent to /api/price or
   /api/generate is fake. Tapping "Advanced" surfaces a disclosing toast
   (the same soonToast convention AppMobile.jsx's own Menu items use) rather
   than a dead tap or a half-built screen.

   Edit and Video modes render an honest sub-placeholder (reusing
   gallery-mobile.css's own .glm-placeholder classes) rather than porting
   partial pixels for either -- see the build report for why the segmented
   control itself ships now instead of being deferred alongside them. */

const MODES = [
  ["image", "Image", "Generate images"],
  ["edit", "Edit", "Edit · Fixer · Enhance"],
  ["video", "Video", "Generate video"],
];

export default function CreateMobile({
  account, costRef,
  s, set, busy, results, applyModelRow, pickVersion, addLora, removeLora, generate, refreshPrice,
}) {
  const [cmode, setCmode] = useState("image");
  const [flyOpen, setFlyOpen] = useState(false);
  const [flyKind, setFlyKind] = useState("base");
  const costHost = useRef(null);
  const deselectRef = useRef(null);

  const loraCap = account && account.lora_cap != null ? account.lora_cap : null;
  const gate = goGate(s, loraCap);
  const m = s.model;

  /* <mg-cost-badge> mount -- identical contract to GenerateDrawer.jsx's own
     effect: an imperative DOM handle via costRef, no fetch of its own, real
     text when the script never loaded rather than a blank space next to a
     live spend button. Runs on every real mount (including a remount after
     a tab switch away and back -- the previous element, if any, is simply
     garbage; a fresh one primes with a fresh refreshPrice() call). */
  useEffect(() => {
    const host = costHost.current;
    if (!host || host.firstChild) return;
    if (window.customElements && window.customElements.get("mg-cost-badge")) {
      const el = document.createElement("mg-cost-badge");
      host.appendChild(el);
      costRef.current = el;
      refreshPrice();
    } else {
      host.textContent = "⚠ Couldn't verify the cost — generating may spend credits.";
      host.className = "gd-cost gd-costfail";
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onBasePick = useCallback((row) => {
    setFlyOpen(false);
    applyModelRow(row);
  }, [applyModelRow]);

  const onLoraPick = useCallback((model, selected) => {
    if (!model || !model.model_id) return;
    if (selected === false) removeLora(model.model_id);
    else addLora(model);
  }, [addLora, removeLora]);

  const removeLoraChip = (modelId) => {
    removeLora(modelId);
    if (deselectRef.current) deselectRef.current(modelId);
  };

  const openModelSheet = (kind) => { setFlyKind(kind); setFlyOpen(true); };

  const pickRef = async () => {
    const picked = await askPicker({ type: "image" });
    if (picked) set({ ref: { media_id: picked.media_id, thumb: picked.thumb } });
  };

  const soonToast = (label) => {
    if (window.Toast) window.Toast.show({ title: label, msg: "Its own screen — coming next." });
  };

  const d = dims(s);
  const modelName = m ? (m.resolving ? "Resolving…" : m.failed ? "Lookup failed" : m.title) : "Pick a model";
  const modelMeta = (m && !m.resolving && !m.failed)
    ? [m.model_type, (m.versions && m.versions.length > 1) ? m.versions.length + " versions" : ""]
        .filter(Boolean).join(" · ")
    : "";

  return (
    <div className="glm-tab cm-tab">
      <div className="cm-pad">
        <div className="cm-seg3">
          {MODES.map(([k, label, title]) => (
            <button key={k} type="button" title={title}
              className={"cm-segbtn" + (cmode === k ? " on" : "")}
              onClick={() => setCmode(k)}>{label}</button>
          ))}
        </div>

        {cmode !== "image" && (
          <div className="glm-placeholder cm-soon">
            <div className="glm-placeholder-icon" aria-hidden="true">{cmode === "edit" ? "⟲" : "▶"}</div>
            <div className="glm-placeholder-title">{cmode === "edit" ? "Edit" : "Video"}</div>
            <div className="glm-placeholder-note">
              {cmode === "edit" ? "Edit Pro, Fixer, and Enhance" : "Video generation"} — its own mobile pass, coming next.
            </div>
          </div>
        )}

        {cmode === "image" && (
          <>
            <div className="cm-lbl">Prompt</div>
            <textarea className="cm-ta" rows={4} value={s.prompt}
              placeholder="Describe the image…"
              onChange={(e) => set({ prompt: e.target.value })} />

            <div className="cm-lbl">Model &amp; LoRAs</div>
            <button type="button" className={"cm-modelrow" + (m ? "" : " empty")}
              onClick={() => openModelSheet("base")} title="Browse the model catalog">
              {m && m.thumb ? <img className="cm-modelthumb" src={m.thumb} alt="" /> : <span className="cm-modelthumb ph" />}
              <span className="cm-modeltext">
                <span className="cm-modelname">{modelName}</span>
                {modelMeta ? <span className="cm-modelmeta">{modelMeta}</span> : null}
              </span>
              <span className="cm-browse">browse</span>
            </button>
            {m && m.versions && m.versions.length > 1 && (
              <select className="cm-select" value={m.version_id}
                onChange={(e) => pickVersion(e.target.value)}>
                {m.versions.map((v) => (
                  <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>
                ))}
              </select>
            )}

            {s.loras.length > 0 && (
              <div className="cm-chiprow">
                {s.loras.map((l) => {
                  const bad = loraIncompat(l, m);
                  const status = l.failed ? "failed"
                    : !l.version_id ? "resolving…"
                    : bad ? "wrong architecture"
                    : Number(l.weight).toFixed(2);
                  return (
                    <span key={l.model_id}
                      className={"glm-metal on cm-chip cm-lorachip" + ((bad || l.failed) ? " bad" : "")}>
                      {l.title} · {status}
                      <button type="button" className="cm-chipx" title="Remove this LoRA"
                        onClick={() => removeLoraChip(l.model_id)}>&times;</button>
                    </span>
                  );
                })}
              </div>
            )}
            <button type="button" className="cm-addlora" onClick={() => openModelSheet("lora")}>
              + Add LoRA{loraCap != null ? ` ${s.loras.length} / ${loraCap}` : s.loras.length ? " " + s.loras.length : ""}
            </button>

            <div className="cm-lbl">Aspect</div>
            <div className="cm-chiprow">
              {ASPECTS.map(([label, r]) => {
                const on = !s.customW && !s.customH && Math.abs(s.aspect - r) < 0.001;
                return (
                  <button key={label} type="button"
                    className={"glm-metal cm-chip" + (on ? " on" : "")}
                    onClick={() => set({ aspect: r, customW: "", customH: "" })}>{label}</button>
                );
              })}
            </div>
            <div className="cm-hint">{d.width} × {d.height} px</div>

            <div className="cm-lbl">Reference (optional) — guides the result</div>
            <div className="cm-refrow">
              <button type="button" className={"cm-refslot" + (s.ref ? " filled" : "")}
                onClick={pickRef} title="Pick from your gallery">
                {s.ref ? <img src={s.ref.thumb} alt="" /> : "+ ref"}
              </button>
              {s.ref && (
                <>
                  <input type="range" min="0.1" max="0.9" step="0.05" value={s.refStrength}
                    className="cm-range"
                    onChange={(e) => set({ refStrength: e.target.value })} />
                  <b className="cm-refval">{Number(s.refStrength).toFixed(2)}</b>
                  <button type="button" className="cm-chipx cm-refx" title="Clear reference"
                    onClick={() => set({ ref: null })}>&times;</button>
                </>
              )}
            </div>

            <button type="button" className="cm-advrow" onClick={() => soonToast("Advanced settings")}>
              ⚙ Advanced — LoRA, size, tuning, negative
            </button>

            <span ref={costHost} className="gd-cost cm-cost" />

            {gate && <div className="cm-gatenote">{gate}</div>}

            {results.length > 0 && (
              <div className="gd-results cm-results">
                {results.map((r) => (
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

            <button type="button" className={"cm-generate" + (gate || busy ? " off" : "")}
              disabled={!!gate || busy}
              title={gate || "Submit — this spends credits or a card"}
              onClick={() => generate(loraCap)}>
              {busy ? "◌ Queued…" : "✦ Generate"}
            </button>
          </>
        )}
      </div>

      {flyOpen && <div className="glm-scrim" onClick={() => setFlyOpen(false)} />}
      <div className="cm-modelwrap">
        <ModelFlyout
          open={flyOpen} kind={flyKind} setKind={setFlyKind}
          baseType={m ? m.model_type : ""}
          onBasePick={onBasePick} onLoraPick={onLoraPick}
          onClose={() => setFlyOpen(false)}
          deselectRef={deselectRef}
        />
      </div>
    </div>
  );
}
