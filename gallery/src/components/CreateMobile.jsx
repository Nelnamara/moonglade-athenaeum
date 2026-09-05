import React, { useCallback, useEffect, useState } from "react";
import {
  ASPECTS, SIZES, STEPS_FALLBACK, MODES as GEN_MODES,
  dims, goGate, loraIncompat, loraRange, loraStep,
} from "../gen/genCore.js";
import { EDIT_CAPS, editCaps, refTag } from "../gen/editCore.js";
import { insertTriggerWords } from "../gen/loraTriggers.js";
import ModelFlyout from "./ModelFlyout.jsx";
import MobileScreen from "./MobileScreen.jsx";
import { askPicker } from "./PickerHost.jsx";
import { ResultLines } from "./EditTab.jsx";
import CostBadge from "./CostBadge.jsx";
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
     - the cost quote -- the shared <CostBadge>, fed by useGenerate's real
       /api/price debounce (refreshPrice()), mounted the exact same way
       GenerateDrawer.jsx mounts it (JSX in the footer, driven imperatively
       through costRef);
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

   DEFERRED to the Advanced screen at the time this comment was first written
   -- LoRA weight sliders, the SIZE long-edge stops + custom W/H override,
   steps/cfg/seed/mode, the three boosters, and the negative prompt -- is now
   BUILT (2026-08-03); see the ADVANCED SCREEN paragraph below for what
   shipped and what stayed a disclosed, deliberate omission.

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
     - the cost quote -- Edit's OWN separate <CostBadge> mount (editCostRef,
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
   editCore's real switchEditModel(). Resolution/Quality/Aspect were deferred
   with EDIT_CAPS' own honest per-model defaults, exactly like Image's own
   Advanced-gated fields, until the ADVANCED SCREEN paragraph below's build.
   The Advanced row's disclosed summary text drops "model" (no longer
   Advanced-only) AND "negative" -- the design mock's own copy for this row
   read "resolution, quality, aspect, negative", but editCore.js's EDIT_DEFAULTS
   and buildEditPayload() have no `negative` key anywhere in Edit's state or
   wire payload (verified against both -- see the ADVANCED SCREEN paragraph);
   that word was leftover copy carried over from Image mode's own toast, not a
   real field, so it was dropped rather than shipped as a dead promise.

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
   (the art-filter engine, gallery/src/art/artFilters.js: nothing generated, nothing
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
   create-mobile.css's .cm-videowrap to land in the exact same visual spot.

   ADVANCED SCREEN (2026-08-03) -- the "⚙ Advanced" row now pushes a real
   full-screen screen (MobileScreen.jsx, the first full-screen-push chrome
   this codebase's mobile surfaces have needed -- no existing pattern fit, so
   it was built as a new shared primitive alongside MobileSheet.jsx rather
   than baked inline here or copy-pasted from the bottom-sheet chrome, which
   has different geometry and a different dismissal contract) instead of the
   soonToast() stub. advOpen/advClosing are local state (nothing here needs
   to survive a Gallery/Control tab switch -- the screen is only ever open
   while the user is actively looking at it, unlike the drafts useGenerate()/
   useEditGenerate() protect). It is wired to the SAME lifted `s`/`set`/
   `setLora` (Image) and `edit.s`/`edit.set` (Edit) state the composer screens
   already use -- no parallel state, no new setters.

   Image's ImageAdvanced renders: per-LoRA weight sliders (loraRange()/
   loraStep() -- the SAME bounds-by-base-model-architecture GenerateDrawer.jsx
   uses; s.loras being empty renders an honest "use + Add LoRA" hint instead of
   a blank section); Frame (SIZES stops S/M/L/XL, custom W/H, the resolved
   dims() hint, and Count); Tuning (mode chips, Steps/CFG range sliders bound
   to the selected model's own restrictions with the same disabled-when-
   incompatible logic as desktop, Seed, the three boosters, and Prompt
   helper/Priority as real toggles reading/writing s.promptHelper/
   s.highPriority); and Negative prompt. DISCLOSED DEVIATIONS from the design
   mock's literal numbers, chosen in favor of the real server contract over
   the mock's copy: Count's chips are [1,2,3,4] (genCore.js's buildPayload
   hard-clamps count to 1..4, and GenerateDrawer.jsx's own real COUNT stops
   are the same four -- the design mock's "1/2/4/6" would silently clamp a
   tapped "6" down to 4 with no indication, so the real desktop reference
   won on a numbers mismatch); Priority/Helper are boolean toggle chips
   ("Priority · standard" / "Priority · high", "Prompt helper · on/off"),
   not the mock's "standard · 500 / high · 1000" -- no such per-priority
   pricing exists anywhere in genCore.js or account data, so shipping the
   mock's literal digits would be inventing a number, not disclosing a real
   one (the research pass flagged this exact row as likely-placeholder copy).

   Edit's EditAdvanced renders Resolution/Quality/Aspect from EDIT_CAPS,
   keyed off the model already chosen on the main composer (edit.chooseModel):
   Resolution and Quality as chip rows (Quality's row is replaced by the
   design's own real hint text -- "{label} has no quality knob — it offers
   {resolutions} only" -- for Reference Pro, which ships an empty qualities
   array); Aspect as a <select> (10-11 options -- desktop EditTab.jsx's own
   real reference control for this exact field, chips would not fit 11 options
   on a phone width). No Model row and no Negative prompt in Edit's screen --
   both disclosed above and in the CORRECTED NOTE paragraph.

   Video mode needs no Advanced screen: re-confirmed directly in the React
   <VideoDrawer> (gallery/src/components/VideoDrawer.jsx -- quality/channel/camera
   controls are part of the component's own render) that the shared drawer is fully self-contained,
   and CreateMobile.jsx/VideoMode.jsx render no "Advanced" row at all for
   cmode === "video" (VideoMode paints in AppMobile.jsx's own .cm-videowrap
   slot, entirely outside this file's Advanced-row markup) -- so there was
   never a reachable dead tap to fix; nothing added for Video on purpose. */

export const MODES = [
  ["image", "Image", "Generate images"],
  ["edit", "Edit", "Edit · Fixer"],
  ["video", "Video", "Generate video"],
];

export default function CreateMobile({
  account, costRef, editCostRef, cmode, setCmode, edit,
  s, set, busy, results, applyModelRow, pickVersion, addLora, removeLora, setLora, generate, refreshPrice,
  canSubmit: priceOk,
}) {
  const [flyOpen, setFlyOpen] = useState(false);
  const [flyKind, setFlyKind] = useState("base");
  const [editSub, setEditSub] = useState("edit"); // Edit's own Edit/Fixer sub-tab -- local, no draft to lose
  // Advanced screen -- local (nothing here needs to survive a Gallery/Control
  // tab switch the way the composer drafts do; see header comment). Mirrors
  // AppMobile.jsx's own sheet/closing pair exactly (MobileScreen.jsx's
  // ownership contract is deliberately identical to MobileSheet.jsx's).
  const [advOpen, setAdvOpen] = useState(false);
  const [advClosing, setAdvClosing] = useState(false);

  const loraCap = account && account.lora_cap != null ? account.lora_cap : null;
  const gate = goGate(s, loraCap);
  const m = s.model;

  /* Prime the Image cost chip when Image mode is (re)entered. <CostBadge>'s ref
     is live at commit, so refreshPrice() here always hits a mounted badge --
     useGenerate lives up in AppMobile and already fired against a null costRef
     before this screen mounted, so this explicit prime is what shows the draft's
     price on entry (via costRef, never JSX). */
  useEffect(() => {
    if (cmode === "image") refreshPrice({ force: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cmode]);

  /* Prime Edit's OWN cost chip on entering the Edit/Edit sub-tab. Its <CostBadge>
     only exists while that sub-tab is shown (Image is the default mode, so the
     Edit badge is absent on first render); this fires the moment cmode/editSub
     reach edit/edit, by which commit the badge's ref is live -- never shared with
     Image's costRef (see useEditGenerate.js's header). */
  useEffect(() => {
    if (cmode === "edit" && editSub === "edit") edit.refreshPrice({ force: true });
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
    // Controlled selection: removing from state un-lights the picker card automatically.
    removeLora(modelId);
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

  // Advanced screen open/close -- mirrors AppMobile.jsx's own closeSheet()
  // timing exactly (setTimeout matches the CSS animation's own duration; see
  // MobileScreen.jsx's header comment for why the contract is identical).
  const openAdv = () => setAdvOpen(true);
  const closeAdv = () => {
    setAdvClosing(true);
    setTimeout(() => { setAdvOpen(false); setAdvClosing(false); }, 220);
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

                <button type="button" className="cm-advrow" onClick={openAdv}>
                  ⚙ Advanced — resolution, quality, aspect
                </button>

                <span className="gd-cost cm-cost">
                  <CostBadge ref={editCostRef} hint="Pick an image to edit to see the cost." />
                </span>

                {edit.gate && <div className="cm-gatenote">{edit.gate}</div>}

                {edit.results.length > 0 && (
                  <div className="cm-results">
                    <ResultLines lines={edit.results} />
                  </div>
                )}

                {/* Price-probe verdict ANDed into the existing gate -- same rule as Image mode. */}
                <button type="button" className={"cm-generate" + (edit.gate || edit.busy || !edit.canSubmit ? " off" : "")}
                  disabled={!!edit.gate || edit.busy || !edit.canSubmit}
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
                      {/* Mobile's half of issue #45. The words are inserted automatically on
                          pick (the shared useGenerate.addLora), exactly as on desktop; this
                          is the same re-insert affordance the drawer's "+words" button is,
                          in the chip row's own idiom, because until now this surface had no
                          trigger-word control of any kind. Dedupe makes a stray tap a
                          no-op rather than a duplicator. */}
                      {l.trigger_words ? (
                        <button type="button" className="cm-chipwords"
                          title={"Re-insert this LoRA's trigger words if you deleted them: "
                                 + l.trigger_words}
                          onClick={() => set({ prompt: insertTriggerWords(s.prompt, l.trigger_words) })}>
                          +words
                        </button>
                      ) : null}
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

            <button type="button" className="cm-advrow" onClick={openAdv}>
              ⚙ Advanced — LoRA, size, tuning, negative
            </button>

            <span className="gd-cost cm-cost">
              <CostBadge ref={costRef} />
            </span>

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

            {/* Gated on the price probe's verdict IN ADDITION to goGate/busy: the quote on the
                badge must have been priced off the payload this click submits. generate()
                refuses the same way (gen/priceProbeCore.js). */}
            <button type="button" className={"cm-generate" + (gate || busy || !priceOk ? " off" : "")}
              disabled={!!gate || busy || !priceOk}
              title={gate || "Submit — this spends credits or a card"}
              onClick={() => generate(loraCap)}>
              {busy ? "◌ Queued…" : "✦ Generate"}
            </button>
          </>
        )}
      </div>

      {/* Advanced screen -- a sibling of .cm-pad within this unpositioned
          .glm-tab, so .glm-screen's position:absolute;inset:0 resolves
          against .glm-body (position:relative) the same way .cm-videowrap
          already does -- see gallery-mobile.css's .glm-screen comment. */}
      <MobileScreen open={advOpen} closing={advClosing} onClose={closeAdv}
        title={(cmode === "edit" ? "Edit" : "Image") + " — Advanced"}>
        {cmode === "edit"
          ? <EditAdvanced edit={edit} />
          : <ImageAdvanced s={s} set={set} setLora={setLora} m={m} />}
      </MobileScreen>

      {flyOpen && <div className="glm-scrim" onClick={() => setFlyOpen(false)} />}
      <div className="cm-modelwrap">
        <ModelFlyout
          open={flyOpen} kind={flyKind} setKind={setFlyKind}
          baseType={m ? m.model_type : ""}
          value={m} selected={s.loras}
          onBasePick={onBasePick} onLoraPick={onLoraPick}
          onClose={() => setFlyOpen(false)}
        />
      </div>
    </div>
  );
}

/* ---- Image mode's Advanced fields -- see this file's header comment
   (ADVANCED SCREEN paragraph) for the full field list and the disclosed
   deviations from the design mock's literal Count/Priority numbers. Reads
   and writes the SAME `s`/`set`/`setLora` the Image composer above uses --
   no parallel state. ---- */
function ImageAdvanced({ s, set, setLora, m }) {
  const d = dims(s);
  const custom = !!(parseInt(s.customW, 10) > 0 && parseInt(s.customH, 10) > 0);
  const [loraLo, loraHi] = loraRange(m ? m.model_type : "");
  const restr = (m && m.restrictions) || {};
  const stepsR = restr.samplingSteps || {};
  const cfgR = restr.cfgScale || {};
  const stepsVal = s.steps === "" ? STEPS_FALLBACK : Number(s.steps);
  const cfgVal = s.cfg === "" ? 7 : Number(s.cfg);

  return (
    <>
      <div className="cm-subhead">LoRAs</div>
      {s.loras.length === 0 ? (
        <div className="cm-hint">No LoRAs added yet — use "+ Add LoRA" on the main screen.</div>
      ) : (
        s.loras.map((l) => (
          <div className="cm-adv-lorarow" key={l.model_id}>
            <div className="cm-adv-lorahead">
              <span>{l.title}</span>
              <b>{Number(l.weight).toFixed(2)}</b>
            </div>
            <input type="range" className="cm-range" min={loraLo} max={loraHi} step={loraStep()}
              value={l.weight} disabled={!l.version_id || l.failed}
              onChange={(e) => setLora(l.model_id, { weight: e.target.value })} />
          </div>
        ))
      )}

      <div className="cm-subhead">Frame</div>
      <div className="cm-lbl">Size</div>
      <div className="cm-chiprow">
        {SIZES.map((n, i) => (
          <button key={n} type="button"
            className={"glm-metal cm-chip" + (!custom && s.size === n ? " on" : "")}
            onClick={() => set({ size: n, customW: "", customH: "" })}
            title={n + "px"}>
            {["S", "M", "L", "XL"][i] || n}
          </button>
        ))}
      </div>
      <div className="cm-customrow">
        <input className={"cm-custominput" + (custom ? " on" : "")} placeholder="W" value={s.customW}
          onChange={(e) => set({ customW: e.target.value.replace(/\D/g, "") })} />
        <span>×</span>
        <input className={"cm-custominput" + (custom ? " on" : "")} placeholder="H" value={s.customH}
          onChange={(e) => set({ customH: e.target.value.replace(/\D/g, "") })} />
      </div>
      <div className="cm-hint">
        {d.width} × {d.height} px — custom overrides above{custom ? " (in effect)" : ""}
      </div>

      <div className="cm-lbl">Count</div>
      <div className="cm-chiprow">
        {[1, 2, 3, 4].map((n) => (
          <button key={n} type="button" className={"glm-metal cm-chip" + (s.count === n ? " on" : "")}
            onClick={() => set({ count: n })}>{n}</button>
        ))}
      </div>

      <div className="cm-subhead">Tuning</div>
      <div className="cm-lbl">Mode</div>
      <div className="cm-chiprow">
        {GEN_MODES.map(([v, l]) => (
          <button key={v} type="button" title={l}
            className={"glm-metal cm-chip" + (s.mode === v ? " on" : "")}
            onClick={() => set({ mode: v })}>{l}</button>
        ))}
      </div>

      <div className="cm-adv-sliderrow">
        <span className="cm-lbl">Steps</span>
        <input type="range" className="cm-range"
          min={stepsR.min != null ? stepsR.min : 1} max={stepsR.max != null ? stepsR.max : 150}
          step="1" value={stepsVal}
          disabled={m && m.compat_steps === false}
          title={m && m.compat_steps === false ? (m.title + " doesn't take steps") : "Sampling steps"}
          onChange={(e) => set({ steps: e.target.value })} />
        <b className="cm-adv-sliderval">{stepsVal}</b>
      </div>
      <div className="cm-adv-sliderrow">
        <span className="cm-lbl">CFG</span>
        <input type="range" className="cm-range"
          min={cfgR.min != null ? cfgR.min : 1} max={cfgR.max != null ? cfgR.max : 30}
          step="0.5" value={cfgVal}
          disabled={m && m.compat_cfg === false}
          title={m && m.compat_cfg === false ? (m.title + " doesn't take CFG") : "CFG scale"}
          onChange={(e) => set({ cfg: e.target.value })} />
        <b className="cm-adv-sliderval">{cfgVal}</b>
      </div>

      <div className="cm-lbl">Seed</div>
      <input className="cm-input" value={s.seed} placeholder="blank = random"
        onChange={(e) => set({ seed: e.target.value.replace(/[^\d-]/g, "").replace(/(?!^)-/g, "") })} />

      <div className="cm-lbl">Boosters</div>
      <div className="cm-chiprow">
        <button type="button" className={"glm-metal cm-chip" + (s.boosters.face ? " on" : "")}
          onClick={() => set({ boosters: { ...s.boosters, face: !s.boosters.face } })}>
          Face Fix
        </button>
        <button type="button" className={"glm-metal cm-chip" + (s.boosters.quality ? " on" : "")}
          title="Prefixes PixAI's Masterpiece quality tag"
          onClick={() => set({ boosters: { ...s.boosters, quality: !s.boosters.quality } })}>
          Quality Tag
        </button>
        <button type="button" className={"glm-metal cm-chip" + (s.boosters.hires ? " on" : "")}
          disabled={m && m.compat_upscale === false}
          title={m && m.compat_upscale === false
            ? "This model's version does not support upscaling"
            : "Enhance Details — PixAI's own 1.5× / 0.6 denoise pass"}
          onClick={() => set({ boosters: { ...s.boosters, hires: !s.boosters.hires } })}>
          Enhance Details
        </button>
      </div>

      <div className="cm-chiprow">
        <button type="button" className={"glm-metal cm-chip" + (s.promptHelper ? " on" : "")}
          title="PixAI's prompt helper (on by default, like the classic drawer)"
          onClick={() => set({ promptHelper: !s.promptHelper })}>
          Prompt helper · {s.promptHelper ? "on" : "off"}
        </button>
        <button type="button" className={"glm-metal cm-chip" + (s.highPriority ? " on" : "")}
          title="Faster queue · costs extra"
          onClick={() => set({ highPriority: !s.highPriority })}>
          Priority · {s.highPriority ? "high" : "standard"}
        </button>
      </div>

      <div className="cm-subhead">Negative prompt</div>
      <textarea className="cm-ta" rows={2} value={s.negative}
        placeholder="lowres, bad hands, watermark"
        disabled={m && m.compat_neg === false}
        onChange={(e) => set({ negative: e.target.value })} />
    </>
  );
}

/* ---- Edit mode's Advanced fields -- resolution/quality/aspect only (no
   Model row, no Negative prompt; both disclosed in this file's header
   comment). Reads and writes the SAME `edit.s`/`edit.set` the Edit composer
   above uses -- no parallel state. ---- */
function EditAdvanced({ edit }) {
  const caps = editCaps(edit.s.model);
  return (
    <>
      <div className="cm-subhead">Resolution</div>
      <div className="cm-chiprow">
        {caps.resolutions.map((r) => (
          <button key={r} type="button"
            className={"glm-metal cm-chip" + (edit.s.resolution === r ? " on" : "")}
            onClick={() => edit.set({ resolution: r })}>{r}</button>
        ))}
      </div>

      <div className="cm-subhead">Quality</div>
      {caps.qualities.length > 0 ? (
        <div className="cm-chiprow">
          {caps.qualities.map((q) => (
            <button key={q} type="button"
              className={"glm-metal cm-chip" + (edit.s.quality === q ? " on" : "")}
              onClick={() => edit.set({ quality: q })}>{q}</button>
          ))}
        </div>
      ) : (
        <div className="cm-hint">
          {caps.label} has no quality knob — it offers {caps.resolutions.join("/")} only.
        </div>
      )}

      <div className="cm-subhead">Aspect</div>
      <select className="cm-select" value={edit.s.aspect}
        onChange={(e) => edit.set({ aspect: e.target.value })}>
        {caps.aspects.map((a) => <option key={a} value={a}>{a}</option>)}
      </select>
    </>
  );
}
