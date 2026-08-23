import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  buildEditPayload, editCaps, editGate, EDIT_CAPS, EDIT_PRICE_KEY_SKIP,
  refTag, switchEditModel,
} from "../gen/editCore.js";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import usePriceProbe from "../gen/usePriceProbe.js";
import { askPicker } from "./PickerHost.jsx";
import CostBadge from "./CostBadge.jsx";

/* The Edit tab: Edit Pro / Reference Pro against /api/edit, with the toolbox
   preset bank. @image1 is the image being edited; extra references number from
   @image2 -- the instruction refers to them by those tags.

   STATE LIVES IN THE DRAWER (dock fidelity stage 3, 2026-08-16 -- the DC's own
   model, Frontend Gallery.dc.html 1917-1922: one component holds editRefs /
   editModel / resolution / … for all three sub-tabs). `s` / `setS` arrive as
   props (EDIT_DEFAULTS shape, editCore.js) so the SOURCE slab -- the picture
   being edited plus its references -- is ONE list shared by Edit, Fixer and
   Enhance (DC 1445-1468 is not gated by `sub`). Everything else is unchanged:
   this component still OWNS its price debounce, its CostBadge instance, its
   editGate and its run() -> submitTask('/api/edit', buildEditPayload(s)).

   `dock` (Generate dock, 2026-08-16 fidelity pass -- Frontend Gallery.dc.html
   1541-1591 draws ONE composer footer shared by every tab): when given
   ({ topEl, promptEl, goEl, resultsEl, balance, promptApi, promptMax }), the
   instruction textarea, the CostBadge, the '✦ Edit' button and the result lines
   render into the dock's slots via portals -- SAME state, SAME costRef, SAME
   run()/gate; only where they mount changes. promptApi receives the dock's
   ★ Snippets insert/read pair while this tab is visible. Without `dock` the
   tab renders its own instruction field, submit row and results inline.

   WHAT THIS RENDERS: slab 2 (EDIT MODEL) and slab 3 (QUALITY) of the DC's
   three-slab Edit grid (DC 1470-1540). Slab 1 (SOURCE) is <SourceSlab> below,
   mounted by the drawer for every sub-tab. */
export default function EditTab({ visible, s, setS, onDroppedNote, dock }) {
  const [presets, setPresets] = useState({});
  const [importTask, setImportTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, openLine] = useResultLines();
  const costRef = useRef(null);
  const busyRef = useRef(false);
  const caps = editCaps(s.model);
  const gate = editGate(s);
  const used = ((s.source || "").trim() ? 1 : 0) + s.refs.length;

  const set = (patch) => setS((old) => ({ ...old, ...patch }));

  // presets load lazily, once, when the tab is first shown
  useEffect(() => {
    if (!visible || Object.keys(presets).length) return;
    fetch("/api/presets").then((r) => r.json())
      .then((d) => setPresets((d && d.presets) || {})).catch(() => {});
  }, [visible]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Its OWN price-probe instance -- sharing a debounce/seq with the image tab's is
     exactly what caused the classic's historical no-price-on-?edit= bug. The probe
     (gen/usePriceProbe.js) owns the debounce, the seq guard, the abort timeout and
     the payload-identity spend gate; this tab supplies only the payload builder.
     It POSTs buildEditPayload(s), the SAME object /api/edit receives on submit, so a
     quote can never describe a different edit than what goes out. */
  const build = useCallback(() => {
    const p = buildEditPayload(s);
    return { payload: p, idle: (s.source || "").trim() ? null : true };
  }, [s]);
  // `enabled: visible` is the #27 cleanup and the entry re-prime in one seam: hidden,
  // the probe holds no armed timer and no request (the badge is portaled into the
  // footer and unmounts with the tab, and the shared source can change from the
  // Fixer meanwhile); becoming visible again forces a re-price, because the badge
  // comes back idle whatever the settled verdict says.
  const probe = usePriceProbe({ build, costRef, enabled: visible, skipKeys: EDIT_PRICE_KEY_SKIP });

  // Re-prices on any field change. BEHAVIOUR CHANGE 2026-08-22: the instruction is in
  // the probe's identity skip, so a keystroke short-circuits instead of blanking the
  // badge and disabling ✦ Edit for 250ms + one RTT.
  useEffect(() => { probe.refresh(); }, [s, probe.refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  // clampEditNote (DC 1517-1519 / 2255-2258): set by a model switch that had to correct
  // the resolution (or, real caps, the aspect); replaced by the next switch, like the DC's.
  const [clampNote, setClampNote] = useState("");
  const chooseModel = (k) => {
    const { next, notice, clamp } = switchEditModel(s, k);
    setS(next);
    // The dropped-references note is the SOURCE slab's inline amber line (DC 1465-1467),
    // not a toast -- the drawer holds it beside the shared source state.
    if (onDroppedNote) onDroppedNote(notice ? notice.note : "");
    setClampNote(clamp || "");
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
    // PAYLOAD IDENTITY gate -- the button is already disabled on it; this is the click
    // that slips through a stale render (a keyboard Enter needs no repaint to fire).
    if (!probe.canSubmit) { probe.refresh(); return; }
    busyRef.current = true; setBusy(true);
    const emit = openLine("Submitting…");
    await submitTask("/api/edit", buildEditPayload(s), { label: "Edited", emit });
    busyRef.current = false; setBusy(false);
    // The submit DEBITED credits or a card; the payload is byte-identical, so only a
    // FORCED re-price gets past the short-circuit.
    probe.refresh({ force: true });
  };

  // Dock ★ Snippets <-> the instruction: insert (functional update, no stale closure) and
  // read (for "+ save current"). Registered only while this tab is the visible one.
  const promptApi = dock ? dock.promptApi : null;
  const sRef = useRef(s);
  sRef.current = s;
  useEffect(() => {
    if (!promptApi || !visible) return;
    const api = {
      insert: (t) => setS((old) => ({
        ...old,
        instruction: (old.instruction.trim() ? old.instruction.trim().replace(/,\s*$/, "") + ", " : "") + String(t || ""),
      })),
      read: () => sRef.current.instruction || "",
    };
    promptApi.current = api;
    return () => { if (promptApi.current === api) promptApi.current = null; };
  }, [promptApi, visible, setS]);

  if (!visible) return null;

  // The footer pieces (dock mode) -- one definition each, mounted inline or portaled.
  const inDock = !!dock;
  // Dock rows follow the DC's promptRows rule (3561, 08-16d/f: grows with the text,
  // 6 at rest, one more while it has focus, capped by the dock's own room --
  // `promptMax` / `promptFocus` from the dock's measurement and its composer focus ring).
  const dockRows = inDock
    ? Math.max(6, Math.min(dock.promptMax || 8,
        Math.ceil(((s.instruction || "").length || 1) / 76) + (dock.promptFocus ? 1 : 0)))
    : 3;
  // The field itself is the DC's composer prompt (promptStyle 3561 = .mgdock-prompt, no
  // label of its own). PLACEHOLDER IS REAL-DATA (owner ruling 2026-08-16): the DC's
  // promptPlaceholder (3560) is one constant for every tab, 'Describe your image…' --
  // image-gen copy, not tab-aware; an edit instruction refers to its pictures by PixAI's
  // @imageN tags (the SOURCE slab's badges), so the placeholder teaches that syntax.
  const instructionField = (
    <textarea className={inDock ? "mgdock-prompt" : "gd-prompt"} rows={dockRows}
      value={s.instruction}
      placeholder="make it night · put @image2's outfit on @image1 …"
      onChange={(e) => set({ instruction: e.target.value })} />
  );
  const costLine = (
    <CostBadge ref={costRef} hint="Pick an image to edit to see the cost."
      stack={inDock || undefined} balance={inDock ? dock.balance : undefined} />
  );
  // The submit control is gated on the price probe's verdict IN ADDITION to editGate:
  // the quote on the badge must have been priced off the payload this click submits.
  const goOff = !!gate || busy || !probe.canSubmit;
  const goButton = inDock ? (
    <button type="button" className={"mgdock-gen" + (goOff ? " off" : "")}
      disabled={goOff} title={gate || "Submit — this spends credits or a card"}
      onClick={run}><span>&#10022; Edit</span></button>
  ) : (
    <button className="gen" disabled={goOff} title={gate || "Submit the edit"}
      onClick={run}>&#10022; Edit</button>
  );
  // Composer top row (DC 1557-1562: pip · summary): the edit model as the pip -- with the
  // picture being edited as its thumb -- and refs · resolution · aspect as the summary.
  const topRow = inDock ? (
    <>
      <span className="mgdock-modelchip static" title="Edit model — set in the Edit settings">
        {s.source ? <img src={"/thumbs/" + s.source + ".jpg"} alt="" /> : <span className="mgdock-chipph" />}
        <span>{EDIT_CAPS[s.model] ? EDIT_CAPS[s.model].label : s.model}</span>
      </span>
      <span className="mgdock-frames">{used}/{caps.max_refs} refs · {s.resolution} · {s.aspect}</span>
    </>
  ) : null;
  // The result lines (Submitting… / Queued / ✔ done / ✕ error, incl. the "task MAY exist"
  // transport warning) live OUTSIDE the ▲-gated grid in dock mode -- a submit from the
  // collapsed footer must still be able to answer.
  const results = lines.length ? <ResultLines lines={lines} /> : null;

  return (
    <>
      {inDock && dock.topEl ? createPortal(topRow, dock.topEl) : null}
      {inDock && dock.promptEl ? createPortal(instructionField, dock.promptEl) : null}
      {inDock && dock.goEl ? createPortal(<>{costLine}{goButton}</>, dock.goEl) : null}
      {inDock && dock.resultsEl ? createPortal(results, dock.resultsEl) : null}

      {/* SLAB 2 -- EDIT MODEL (Frontend Gallery.dc.html 1470-1520): the heading (1471,
          editSlabLabel 'EDIT MODEL' under the Edit sub-tab), the model <select> (1473-1476;
          option labels are the REAL edit-model list, EDIT_CAPS -- the same two the DC drew),
          the RESOLUTION / ASPECT two-column row (1479-1497; option lists are the real per-
          model caps, a documented divergence: the DC's fixed four aspects vs the probe's
          eleven / ten) and the clampEditNote (1517-1519). Styles are the DC's inline
          strings, one class each (dock.css .mgdock-editmodel / -editcols / -editcol /
          -editcap / -editsel / -editnote). */}
      <div className="mgdock-slab" style={{ animationDelay: "60ms" }}>
        <div className="mgdock-lbl">EDIT MODEL</div>
        <select className="mgdock-editmodel" value={s.model} title="Edit model"
          onChange={(e) => chooseModel(e.target.value)}>
          {Object.keys(EDIT_CAPS).map((k) => (
            <option key={k} value={k}>{EDIT_CAPS[k].label}</option>
          ))}
        </select>
        <div className="mgdock-editcols">
          <div className="mgdock-editcol">
            <div className="mgdock-editcap">RESOLUTION</div>
            <select className="mgdock-editsel" value={s.resolution}
              onChange={(e) => set({ resolution: e.target.value })}>
              {caps.resolutions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="mgdock-editcol">
            <div className="mgdock-editcap">ASPECT</div>
            <select className="mgdock-editsel" value={s.aspect}
              onChange={(e) => set({ aspect: e.target.value })}>
              {caps.aspects.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </div>

        {/* EXTRA -- REAL CAPABILITY, KEPT (owner ruling 2026-08-16; checklist region 2
            'Toolbox preset row'): the DC never drew a preset picker, but the server has one
            (/api/presets, per-account banked Toolbox prompts; a preset satisfies the
            instruction gate and pins its own model -- moonglade_gallery.py
            _edit_params_from_payload). Restyled to the DC's look: the RESOLUTION-style
            caption + the DC's small-select skin, in the slab whose model it overrides. */}
        <div className="mgdock-editcol">
          <div className="mgdock-editcap">TOOLBOX PRESET</div>
          <div className="mgdock-presetrow">
            <select className="mgdock-editsel" value={s.preset}
              title="A banked pixai.art Toolbox prompt — used instead of the instruction, and it pins its own model"
              onChange={(e) => set({ preset: e.target.value })}>
              <option value="">None — custom instruction</option>
              {Object.entries(presets).map(([name, p]) => (
                <option key={name} value={name}>{p.label || name}</option>
              ))}
            </select>
            <input className="mgdock-editsel mgdock-taskid" placeholder="pixai task id" value={importTask}
              inputMode="numeric"
              onChange={(e) => setImportTask(e.target.value.replace(/\D/g, ""))} />
            <button type="button" className="mgdock-bank" onClick={bankPreset}
              title="Bank the prompt from one of your pixai.art tasks as a reusable preset">
              + bank
            </button>
          </div>
        </div>

        {!inDock && (
          <>
            <label className="gd-lbl">Instruction</label>
            {instructionField}
          </>
        )}

        {clampNote ? <div className="mgdock-editnote">{clampNote}</div> : null}
      </div>

      {/* SLAB 3 -- QUALITY (DC 1522-1540): the heading (1523); for a model with a quality
          knob the Low / Medium / High segmented control (1524-1530, segStyle 2834-2835 --
          the same container + segment as the sub-tab strip; labels are the real qualities
          list, capitalised as the DC labels them, 2940); for one without, the DC's help
          line (1531-1533) built from the real caps ('Reference Pro has no quality knob —
          it offers 2K/4K only.', word for word for Reference Pro).

          NOT RENDERED -- the DC's {{switches}} (1534-1539, 'High priority' / 'Prompt
          helper'): that is the IMAGE tab's state (3657-3660, s.priority / s.helper), drawn
          here because the DC's composer/settings getters are not tab-aware. PixAI's
          instruct-edit `chat` params carry no priority and no prompt helper (moonglade_
          backup.py build_chat_edit_parameters; /api/edit reads none), so an edit has no
          such switch to flip -- real capability wins (owner ruling 2026-08-16). */}
      <div className="mgdock-slab" style={{ animationDelay: "120ms" }}>
        <div className="mgdock-lbl">QUALITY</div>
        {caps.qualities.length > 0 ? (
          <div className="mgdock-segs">
            {caps.qualities.map((q) => (
              <button key={q} type="button"
                className={"mgdock-seg" + (s.quality === q ? " on" : "")}
                onClick={() => set({ quality: q })}>
                {q.charAt(0).toUpperCase() + q.slice(1)}
              </button>
            ))}
          </div>
        ) : (
          <div className="mgdock-editcopy">
            {caps.label} has no quality knob — it offers {caps.resolutions.join("/")} only.
          </div>
        )}
        {!inDock && (
          <>
            <div className="gd-go">
              <span className="gd-cost">{costLine}</span>
              <span className="sp" />
              {goButton}
            </div>
            {gate && <div className="gd-note">{gate}</div>}
            <ResultLines lines={lines} />
          </>
        )}
      </div>
    </>
  );
}

/* SLAB 1 -- SOURCE (Frontend Gallery.dc.html 1445-1468, getters 2842-2843 slotBox,
   2866-2871 editRefSlots, 2925-2932 subTabs/refNote). Rendered by the drawer for EVERY
   Edit sub-tab (the DC does not gate it on `sub`): the 'SOURCE' label, the Edit / Fixer /
   Enhance sub-tab strip INSIDE the slab, the refNote line, the slot row, and the
   dropped-references note.

   The DC's editRefs is ONE flat list -- index 0 is the picture being edited, the rest
   are references -- and its slot rules follow from that: one empty slot at a time
   (caption 'pick' until there is a source, '+ ref' after), the first pick becomes the
   source, further picks become references, you cannot hold references without a
   source, and clicking a filled slot removes it (removing the source promotes the next
   reference, exactly as filtering index 0 out of the DC's list does) and clears the
   dropped note. Here that list is the build's {source, refs} pair, read the same way.

   REAL-DATA DIVERGENCE (documented, checklist region 1): the badges read '@image1' /
   '@image2' … (refTag, editCore.js) rather than the DC's 'source' / '@2' -- these are the
   literal tags PixAI's instruction syntax refers to, so the slot must show the tag the
   user will type. Restyled to the DC's badge (8.5px mauve on rgba(5,4,13,.74), radius 3).
   The DC's filled tint is a demo stand-in for the picture: the real thumbnail fills it. */
export function SourceSlab({ s, setS, sub, onSub, droppedNote, onDroppedNote }) {
  const caps = editCaps(s.model);
  const source = (s.source || "").trim();
  const used = (source ? 1 : 0) + s.refs.length;

  const pick = async () => {
    const m = await askPicker({ type: "image" });
    if (!m || !m.media_id) return;
    setS((old) => {
      const has = !!(old.source || "").trim();
      if (!has) return { ...old, source: m.media_id };
      if (1 + old.refs.length >= editCaps(old.model).max_refs) return old;
      return { ...old, refs: old.refs.concat([{ media_id: m.media_id, thumb: m.thumb }]) };
    });
  };
  const removeSource = () => {
    setS((old) => {
      const [first, ...rest] = old.refs;
      return { ...old, source: first ? first.media_id : "", refs: rest };
    });
    if (onDroppedNote) onDroppedNote("");
  };
  const removeRef = (i) => {
    setS((old) => ({ ...old, refs: old.refs.filter((_, k) => k !== i) }));
    if (onDroppedNote) onDroppedNote("");
  };

  return (
    <div className="mgdock-slab" style={{ animationDelay: "0ms" }}>
      <div className="mgdock-lbl">SOURCE</div>
      <div className="mgdock-subtabs" role="tablist">
        {/* Edit / Enhance. The old box-coordinate 'Fixer' sub-tab was removed (owner, 2026-08-18):
            it had been broken a while and the panelplugin Handfix/Face-Enhance presets on Enhance
            (mirror-gated) do that job now. */}
        {[["edit", "Edit"], ["enhance", "Enhance"]].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={sub === k} title={l}
            className={"mgdock-seg" + (sub === k ? " on" : "")}
            onClick={() => onSub(k)}>{l}</button>
        ))}
      </div>
      <div className="mgdock-refnote">{used} / {caps.max_refs} · the picture being edited counts as one</div>
      <div className="mgdock-srcslots">
        {source ? (
          <button type="button" className="mgdock-srcslot filled" title="The picture being edited"
            onClick={removeSource}>
            <img src={"/thumbs/" + source + ".jpg"} alt="" />
            <span className="tag">@image1</span>
          </button>
        ) : null}
        {s.refs.map((r, i) => (
          <button type="button" className="mgdock-srcslot filled" key={r.media_id + i}
            title={"Reference " + (i + 2)} onClick={() => removeRef(i)}>
            <img src={r.thumb} alt="" />
            <span className="tag">{refTag(i)}</span>
          </button>
        ))}
        {used < caps.max_refs && (
          <button type="button" className="mgdock-srcslot" title="Pick from your gallery" onClick={pick}>
            <span className="cap">{used ? "+ ref" : "pick"}</span>
          </button>
        )}
      </div>
      {droppedNote ? <div className="mgdock-editnote">{droppedNote}</div> : null}
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
