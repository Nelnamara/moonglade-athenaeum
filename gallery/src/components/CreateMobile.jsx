import React, { useCallback, useEffect, useRef, useState } from "react";
import { ASPECTS, dims, goGate, loraIncompat } from "../gen/genCore.js";
import { EDIT_CAPS, editCaps, refTag } from "../gen/editCore.js";
import ModelFlyout from "./ModelFlyout.jsx";
import { askPicker } from "./PickerHost.jsx";
import { ResultLines } from "./EditTab.jsx";
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

   EDIT MODE, Edit sub-tab (2026-08-03) is now real, following the identical
   contract Image mode set: real logic via a shared hook (useEditGenerate.js,
   instantiated ONCE in AppMobile.jsx as `edit`, spread in here the same
   reason `gen` is), a mobile presentation on top, editCore.js/submitTask.js
   riding completely unmodified. What's real:
     - Prompt (-> s.instruction), Source (@image1, pick/clear via askPicker),
       and up to caps.max_refs-1 extra references (@image2, @image3... via
       editCore's own refTag) -- exactly the fields the design's main pane
       shows for Edit (design_handoff/.../Moonglade Mobile.dc.html lines
       109-184: Prompt / Model / Source, +the enhance-only filter grid this
       build never reaches);
     - the cost quote -- Edit's OWN separate <mg-cost-badge> mount (editCostRef,
       never shared with Image's costRef -- see useEditGenerate.js's header
       comment for why sharing them would resurrect the classic's
       no-price-on-?edit= bug) fed by useEditGenerate's real /api/price
       debounce;
     - Generate itself -- the real editGate()/run() pair (editCore.js's own
       functions, the SAME ones EditTab.jsx calls), real busy state, and a
       real result feed (reusing EditTab.jsx's own exported <ResultLines>
       rather than a third hand-rolled copy).

   CORRECTED NOTE on Edit's MODEL field (Edit Pro / Reference Pro): the DC's
   main pane already has its own Model row (shared across Image/Edit/Video)
   that opens a palette showing both as pickable tiles, independent of the
   Advanced screen's redundant Resolution/Quality/Aspect copy of the same
   choice -- so this was never a reachability problem to solve. The shipped
   two-chip row instead mirrors desktop EditTab.jsx's own card-row switch,
   the real reference implementation for this exact fixed 2-item field --
   ModelFlyout.jsx's marketplace-browsing picker (built for an open-ended
   model catalog) doesn't fit a closed enum of two, so reusing desktop's own
   simpler control was the better match, not a workaround. Wired to
   editCore's real switchEditModel(). Resolution/Quality/Aspect stay deferred
   with EDIT_CAPS' own honest per-model defaults, exactly like Image's own
   Advanced-gated fields -- nothing sent to /api/price or /api/edit is fake,
   only unreachable-to-CHANGE this increment. The Advanced
   row's disclosed summary text is adjusted to "resolution, quality, aspect,
   negative" (dropping "model", which is no longer Advanced-only here).

   Not built here, and not modeled in the design's main pane at all (only
   Advanced's subEdit block and desktop's own EditTab.jsx have it): the
   toolbox preset dropdown + "bank a preset from a task id" control. Presets
   stay empty this increment, so editGate() naturally requires a typed
   Prompt -- honest, matches the simpler mental model the mobile mockup's own
   Prompt-only field set implies.

   Edit's Fixer sub-tab renders an honest sub-placeholder (reusing
   gallery-mobile.css's own .glm-placeholder classes) using the design's own
   real copy for the drag-a-box gesture (design_handoff/.../Moonglade Mobile
   .dc.html lines 432-436 -- confirmed the ONLY drag/box-related content in
   that 1327-line file) -- NOT a shortcut on anything actually specified:
   there is no reference implementation of touch-canvas box drawing anywhere,
   not in desktop's own mouse-only FixTab.jsx, not in the design mockup
   itself (which only asserts the words and a Face/Hand mode toggle as a
   stand-in, per that file's own state shape -- no canvas, no pointer wiring,
   no box-position fields at all). Edit's sub-tab strip here is a real
   two-way Edit/Fixer control, not the design's literal three-way
   Edit/Fixer/Enhance -- see the ENHANCE paragraph directly below for why.

   ENHANCE stays dead. Re-verified 2026-08-03: tests/test_enhance.py is
   still 6/6 passing; there is still no /api/enhance or /api/workflows route,
   no ENHANCE_PLUGINS/build_panelplugin_parameters/workflow_catalog anywhere
   in the server. The two things still named "Enhance" in current code are
   NOT that dead surface -- desktop's Edit-tab "Enhance" sub-tab
   (GenerateDrawer.jsx) is the free, client-side Art Filters panel
   (window.MgArtFilters/static/mg-art-filters.js: nothing generated, nothing
   spent, works offline), and Image mode's "Enhance Details" booster chip
   (genCore.js's MG_HIRES) is an ordinary field of the Image payload (PixAI's
   own hires-fix pass), not a separate dispatch. Neither is built here: this
   increment's mobile Edit mode ships ONLY the real Edit sub-tab and Fixer's
   honest placeholder -- no Art Filters mount, no hires booster UI, no
   "Enhance" label anywhere in this file. If a later increment ever adds a
   mobile Enhance surface, it must be the free client-side filters panel,
   never a server dispatch -- the same rule the desktop research already
   established.

   VIDEO MODE (this increment) is the shared <mg-generate-drawer> web
   component (static/mg-generate-drawer.js) -- the SAME element desktop's
   GenerateDrawer.jsx mounts for its own Video tab (see that file's VideoTab).
   No reimplementation: form state, live cost, submit/poll, and the result
   strip are all the component's own unchanged machinery.

   VideoMode itself, and the cmode/setCmode state that selects it, were LIFTED
   OUT of this file to AppMobile.jsx on 2026-08-03 (credit-safety fix) -- see
   AppMobile.jsx's own header comment and VideoMode.jsx's header comment for
   the full reasoning. Short version: this file is only rendered while
   AppMobile's OUTER tab === "create" ({tab === "create" && <CreateMobile
   .../>}), so a VideoMode instance mounted IN here, however carefully guarded
   against the Image/Edit/Video segmented-control switch, still got torn down
   by a Gallery/Control tab switch -- unmounting mid-submit and silently
   dropping the poll that was tracking an already-charged, in-flight video
   render. VideoMode now mounts directly in AppMobile.jsx, one level above
   this file's own conditional render, so neither switch removes it from the
   DOM. This file still owns the segmented control itself (cmode/setCmode
   arrive as props instead of local state, otherwise unchanged) and renders
   NOTHING in place of the old inline VideoMode mount when cmode === "video"
   -- AppMobile.jsx's lifted VideoMode paints there instead, positioned by
   create-mobile.css's .cm-videowrap to land in the exact same visual spot. */

export const MODES = [
  ["image", "Image", "Generate images"],
  ["edit", "Edit", "Edit · Fixer"],
  ["video", "Video", "Generate video"],
];

export default function CreateMobile({
  account, costRef, editCostRef, cmode, setCmode, edit,
  s, set, busy, results, applyModelRow, pickVersion, addLora, removeLora, generate, refreshPrice,
}) {
  const [flyOpen, setFlyOpen] = useState(false);
  const [flyKind, setFlyKind] = useState("base");
  const [editSub, setEditSub] = useState("edit"); // Edit's own Edit/Fixer sub-tab -- local, no draft to lose
  const costHost = useRef(null);
  const editCostHost = useRef(null);
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

  /* Edit's OWN <mg-cost-badge> mount -- same contract as Image's above, but
     it CANNOT rely on an empty-deps one-shot effect the way Image's does:
     Image's costHost span already exists on CreateMobile's very first render
     because cmode defaults to "image" in AppMobile.jsx, so that branch is
     already the one painted. Edit is never the default mode, so its span
     does not exist yet on that first render, and a one-shot effect would
     find editCostHost.current still null and never get another chance. This
     effect re-checks whenever cmode/editSub change and relies on the
     host.firstChild guard for idempotency, so it still fires exactly once --
     the moment the user first lands on Edit's Edit sub-tab -- however many
     renders happen before or after that. */
  useEffect(() => {
    if (cmode !== "edit" || editSub !== "edit") return;
    const host = editCostHost.current;
    if (!host || host.firstChild) return;
    if (window.customElements && window.customElements.get("mg-cost-badge")) {
      const el = document.createElement("mg-cost-badge");
      el.setAttribute("hint", "Pick an image to edit to see the cost.");
      host.appendChild(el);
      editCostRef.current = el;
      edit.refreshPrice();
    } else {
      host.textContent = "⚠ Couldn't verify the cost — editing may spend credits.";
      host.className = "gd-cost gd-costfail";
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cmode, editSub]);

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

  const pickEditSource = async () => {
    const picked = await askPicker({ type: "image" });
    if (picked) edit.set({ source: picked.media_id });
  };
  const pickEditRef = async () => {
    const picked = await askPicker({ type: "image" });
    if (picked) edit.addRef(picked);
  };

  const soonToast = (label) => {
    if (window.Toast) window.Toast.show({ title: label, msg: "Its own screen — coming next." });
  };

  const d = dims(s);
  const editCapsNow = editCaps(edit.s.model);
  const editUsed = (edit.s.source ? 1 : 0) + edit.s.refs.length;
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

        {cmode === "edit" && (
          <>
            <div className="cm-seg3">
              {[
                ["edit", "Edit", "Edit Pro / Reference Pro — instruction edits"],
                ["fixer", "Fixer", "Box a hand or face — PixAI repairs it (always spends)"],
              ].map(([k, label, title]) => (
                <button key={k} type="button" title={title}
                  className={"cm-segbtn" + (editSub === k ? " on" : "")}
                  onClick={() => setEditSub(k)}>{label}</button>
              ))}
            </div>

            {editSub === "edit" && (
              <>
                <div className="cm-lbl">Prompt</div>
                <textarea className="cm-ta" rows={4} value={edit.s.instruction}
                  placeholder="Describe the edit…"
                  onChange={(e) => edit.set({ instruction: e.target.value })} />

                <div className="cm-lbl">Model</div>
                <div className="cm-chiprow">
                  {Object.entries(EDIT_CAPS).map(([k, cap]) => (
                    <button key={k} type="button"
                      className={"glm-metal cm-chip" + (edit.s.model === k ? " on" : "")}
                      onClick={() => edit.chooseModel(k)}>{cap.label}</button>
                  ))}
                </div>
                <div className="cm-hint">
                  {editCapsNow.label} takes up to {editCapsNow.max_refs} reference{editCapsNow.max_refs === 1 ? "" : "s"}.
                </div>

                <div className="cm-lbl">Source</div>
                <div className="cm-refrow">
                  <button type="button" className={"cm-refslot" + (edit.s.source ? " filled" : "")}
                    onClick={pickEditSource} title="Pick the image to edit">
                    {edit.s.source
                      ? <img src={"/thumbs/" + edit.s.source + ".jpg"} alt="" />
                      : "▨"}
                  </button>
                  {edit.s.source && (
                    <button type="button" className="cm-chipx cm-refx" title="Clear source"
                      onClick={() => edit.set({ source: "" })}>&times;</button>
                  )}
                  <span className="cm-hint">
                    {editUsed}/{editCapsNow.max_refs} — @image1 is the image being edited
                  </span>
                </div>

                {(edit.s.refs.length > 0 || editUsed < editCapsNow.max_refs) && (
                  <div className="cm-chiprow cm-refgrid">
                    {edit.s.refs.map((r, i) => (
                      <span className="cm-refthumbwrap" key={r.media_id + i}>
                        <img src={r.thumb} alt="" />
                        <span className="cm-reftag">{refTag(i)}</span>
                        <button type="button" className="cm-refthumbx" title="Remove this reference"
                          onClick={() => edit.dropRef(i)}>&times;</button>
                      </span>
                    ))}
                    {editUsed < editCapsNow.max_refs && (
                      <button type="button" className="cm-refslot" onClick={pickEditRef} title="Add a reference">
                        + ref
                      </button>
                    )}
                  </div>
                )}

                <button type="button" className="cm-advrow" onClick={() => soonToast("Advanced settings")}>
                  ⚙ Advanced — resolution, quality, aspect, negative
                </button>

                <span ref={editCostHost} className="gd-cost cm-cost" />

                {edit.gate && <div className="cm-gatenote">{edit.gate}</div>}

                {edit.results.length > 0 && (
                  <div className="cm-results">
                    <ResultLines lines={edit.results} />
                  </div>
                )}

                <button type="button" className={"cm-generate" + (edit.gate || edit.busy ? " off" : "")}
                  disabled={!!edit.gate || edit.busy}
                  title={edit.gate || "Submit the edit — this spends credits or a card"}
                  onClick={edit.run}>
                  {edit.busy ? "◌ Queued…" : "✦ Edit"}
                </button>
              </>
            )}

            {editSub === "fixer" && (
              <div className="glm-placeholder cm-soon">
                <div className="glm-placeholder-icon" aria-hidden="true">⛶</div>
                <div className="glm-placeholder-title">Fixer</div>
                <div className="glm-placeholder-note">
                  Drag a box over the hand or face on the source. A fix can't
                  be card-covered — it always spends, and always asks first.
                </div>
                <div className="glm-placeholder-note">
                  Touch box-drawing is its own mobile pass — coming next.
                </div>
              </div>
            )}
          </>
        )}

        {/* cmode === "video" renders nothing here on purpose -- the real
            VideoMode is mounted by AppMobile.jsx (lifted, see this file's
            header comment) and painted in this exact slot by
            create-mobile.css's .cm-videowrap overlay. No duplicate mount. */}

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
