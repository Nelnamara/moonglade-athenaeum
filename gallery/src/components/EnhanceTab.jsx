import React, { useEffect, useRef, useState } from "react";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { ResultLines } from "./EditTab.jsx";

/* The AI Presets slab under the Enhance sub-tab -- the mirror-gated Bridge tier
   (The Bridge.dc.html §3, "Enhance — home, in the drawer"). Six one-click panelplugin
   presets that submit the SHARED source image (slab 1's SourceSlab, the same picture Edit
   and Fixer read) through /api/enhance, which 409s unless the mirror is armed with a live
   session.

   COST CHIPS ARE LIVE, NOT THE COMP'S PLACEHOLDERS. The comp marked Background Remover /
   Line Art as "free card" and flat "1,000" for the rest -- both false: measured live
   2026-08-18, NO free card covers any panelplugin task on this account and real prices run
   1,000-3,000cr (see DECISIONS "Panelplugin/Enhance is paid-only here"). A "free card" chip
   on a paid task would be a cost lie, the one thing this owner most wants avoided, so the
   chips come from /api/enhance/presets (PixAI's own task-price + kaisuuken/check), honouring
   the comp's stated intent -- "the drawer's existing credit vocabulary, reused" -- with true
   numbers instead of its placeholder data.

   Renders ONLY when the mirror is armed -- OFF = gone, not dimmed (§2). The caller
   (GenerateDrawer) gates the mount; this component assumes armed. */
export default function EnhanceTab({ source }) {
  const [presets, setPresets] = useState(null);   // null = loading; [] = load failed
  const [lines, openLine] = useResultLines();
  const [busyKey, setBusyKey] = useState("");
  const busyRef = useRef(false);

  // Prices are flat per workflow and account-stable, so one fetch on mount is enough; the
  // server caches them too. Fail soft to [] -- the slab only shows armed, but a price probe
  // must never blank the drawer.
  useEffect(() => {
    let live = true;
    fetch("/api/enhance/presets")
      .then((r) => r.json())
      .then((d) => { if (live) setPresets((d && d.presets) || []); })
      .catch(() => { if (live) setPresets([]); });
    return () => { live = false; };
  }, []);

  const costLabel = (p) =>
    p.free_card ? "✦ free card"
      : p.price != null ? "◆ " + Number(p.price).toLocaleString()
        : "spends";

  const run = async (p) => {
    if (busyRef.current) return;
    if (!source) {
      if (window.Toast) {
        window.Toast.show({ kind: "err", title: "Pick a source first",
          msg: "Choose an image in SOURCE above, then run an AI preset on it." });
      }
      return;
    }
    // A panelplugin ALWAYS spends here (no free card covers one) -- quote the real number in
    // the confirm, the same spend-honesty Fix keeps, before anything is submitted.
    const quote = p.free_card ? "a free card covers it — 0 credits"
      : p.price != null ? "this will spend " + Number(p.price).toLocaleString() + " credits"
        : "this spends credits";
    if (!window.confirm(p.label + " on your source?\n\n" + quote +
        " — AI presets run on the PixAI mirror.")) return;
    busyRef.current = true; setBusyKey(p.key);
    const emit = openLine("Submitting " + p.label + "…");
    // workflow_name wins in the builder when both are set; each preset is pinned to exactly
    // one addressing form (numeric id OR author/name), so send only the one it carries.
    const body = p.workflow_name
      ? { source, workflow_name: p.workflow_name }
      : { source, workflow_id: p.workflow_id };
    await submitTask("/api/enhance", body, { label: p.label, emit });
    busyRef.current = false; setBusyKey("");
  };

  return (
    <div className="mgdock-slab" style={{ animationDelay: "40ms" }}>
      <div className="mgdock-lbl mgdock-ailbl">
        <span>AI PRESETS <span className="mgdock-aivia">· via the Bridge</span></span>
        <span className="sp" />
        <span className="mgdock-aimirror">● runs on the mirror</span>
      </div>
      {presets === null ? (
        <div className="mgdock-enhancecopy">Loading presets…</div>
      ) : presets.length === 0 ? (
        <div className="mgdock-enhancecopy">Couldn't load the AI presets — is the mirror still armed?</div>
      ) : (
        <div className="mgdock-aigrid">
          {presets.map((p) => (
            <button key={p.key} type="button"
              className={"mgdock-aitile" + (p.has_control ? " ctl" : "") + (busyKey === p.key ? " busy" : "")}
              disabled={!!busyKey}
              onClick={() => run(p)}
              title={source ? p.label : "Pick a source image first"}>
              <span className="mgdock-ainame">{p.label}</span>
              <span className="mgdock-aicost">
                {costLabel(p)}
                {p.has_control ? <span className="mgdock-aictl">+ control</span> : null}
              </span>
            </button>
          ))}
        </div>
      )}
      {!source ? (
        <div className="mgdock-enhancecopy2">Pick a source image in SOURCE above, then tap a preset to run it.</div>
      ) : null}
      <ResultLines lines={lines} />
    </div>
  );
}
