import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState,
} from "react";
import usePriceProbe from "../gen/usePriceProbe.js";
import CostBadge from "./CostBadge.jsx";
import ModelPicker from "./ModelPicker.jsx";
import "../styles/upscale-panel.css";

/* UpscalePanel -- the React port of static/mg-upscale-panel.js's <mg-upscale-panel>: PixAI's
   Upscale, invoked on a picture that ALREADY EXISTS (not one you are about to make). Two methods,
   PixAI's own two radios whose `value` attributes ARE the parameter names: `enlarge` (their
   "Upscale", an ESRGAN pass over finished pixels, ~1200) and `upscale` (their "Hires", re-diffuses
   at the larger size, ~3700). The ratio cap is DYNAMIC -- derived from the source's real dimensions
   against a per-mode output-pixel ceiling that the server ships in window.MG_UPSCALE (never a second
   hand-ported copy). What it submits is nothing new: an image-view upscale is an ordinary i2i
   generation (mediaId + strength), so it POSTs the SAME /api/price and /api/generate the drawer
   uses -- there is deliberately no /api/upscale (a second submit path is a second place for the
   read-only guard / free-card check / job-tracker registration to be forgotten; those all live
   SERVER-SIDE on /api/generate).

   Ported 2026-08-08 (no-vanilla campaign step 5). Kept a forwardRef + useImperativeHandle component
   so the consumers' imperative contract survives verbatim: upEl.current.open(mediaIdOrRow) /
   .close(), plus isOpen()/isClosing() replacing the desktop Lightbox's .hasAttribute("open")/
   ("closing") reads. Embeds the shared React CostBadge (the cost line) and ModelPicker (the model
   override) -- the latter also REPAIRS a regression: the vanilla did createElement('mg-model-picker')
   gated on customElements.get('mg-model-picker'), which has returned undefined since that element
   was ported to React ModelPicker (campaign step 3, file deleted), so the "Choose a model" override
   showed "picker not loaded" for un-modeled images. (Upscale itself always worked -- it falls back
   to core's UPSCALE_FALLBACK_VERSION_ID.)

   Props: `inline` (render in flow -- the detail pages/mobile sheets -- vs a fixed flyout modal);
   `onDone({media_id, task_id})` optional, fired once a submit is accepted (the old bubbling
   `mg-upscale` event; no consumer wires it today, kept as the React-idiomatic seam). */

const MODES = [
  {
    key: "enlarge", label: "Upscale",
    hint: "Runs an upscaler network over the finished picture. Keeps it exactly as it is, "
      + "just larger. Cheaper, and allows a bigger ratio.",
  },
  {
    key: "upscale", label: "Hires",
    hint: "Re-renders the picture at the larger size, so it gains detail rather than only "
      + "resolution. Allows a smaller ratio and costs roughly 3x.",
  },
];

// The server hands these over so this file carries no second copy of core's numbers. Absent (a page
// that forgot the __UPSCALE_CONST__ marker) is treated as "cannot compute a cap", NOT a guessed
// default (which would offer ratios the server then clamps with nothing on screen to explain it).
function consts() { return window.MG_UPSCALE || null; }
// A model VERSION id (PixAI's own upscale submits one directly), so it goes out as `version_id`.
function fallbackVersion() { const c = consts(); return (c && c.fallbackVersionId) || ""; }

// Mirror core.upscale_output_dims / max_upscale_ratio -- floor-to-a-multiple-of-8 reproduces the
// Python (and PixAI's dialog) exactly (1952, not 1960, at 1400×1.4).
function outDims(w, h, r) {
  return [Math.max(64, Math.floor(w * r / 8) * 8), Math.max(64, Math.floor(h * r / 8) * 8)];
}
function maxRatio(w, h, mode) {
  const c = consts();
  if (!c || !c.ceiling || !c.ceiling[mode] || !w || !h) return 0;   // 0 == unknown, not 1
  for (let i = 30; i > 0; i--) {
    const r = Math.round((1 + i * 0.1) * 10) / 10;
    const o = outDims(w, h, r);
    if (o[0] * o[1] <= c.ceiling[mode]) return r;
  }
  return 1;
}

const UpscalePanel = forwardRef(function UpscalePanel({ inline, onDone }, ref) {
  const [phase, setPhase] = useState("closed");   // closed | open | closing
  const [src, setSrc] = useState(null);
  const [mode, setMode] = useState("enlarge");
  const [ratio, setRatio] = useState(1.2);
  const [scaler, setScaler] = useState(() => {
    const c = consts();
    return (c && c.defaultEnlargeModel) || ((c && c.enlargeModels) || [])[0] || "";
  });
  const [scalerOpen, setScalerOpen] = useState(false);
  const [denoise, setDenoise] = useState(0.6);
  const [denoiseSteps, setDenoiseSteps] = useState(26);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [msg, setMsg] = useState(null);            // {text, bad}
  const [busy, setBusy] = useState(false);

  const costRef = useRef(null);
  const openSeq = useRef(0);
  const closeTimer = useRef(0);
  const busyRef = useRef(false);
  const rootRef = useRef(null);
  const pickHostRef = useRef(null);
  const scalerWrapRef = useRef(null);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const scalerNames = (consts() && consts().enlargeModels) || [];

  // ---- derived (mirrors _syncRatio / _canSubmit / _paintModel, computed each render) ----------
  const w = parseInt(src && src.width, 10) || 0;
  const hh = parseInt(src && src.height, 10) || 0;
  const mx = maxRatio(w, hh, mode);
  const ratioDisabled = !mx || mx <= 1;
  const effRatio = mx ? Math.min(ratio, mx) : ratio;
  const [ow, oh] = outDims(w, hh, effRatio);
  const isVideo = !!(src && src.is_video);
  // ONE predicate for Go AND the cost badge. It used to be two: the badge priced only when the
  // source carried a real model_id, while Go also allowed the fallback version -- so a
  // fallback-only picture (an imported file, or a catalog row with no model recorded) offered a
  // live Upscale button with NO quote beside it. Pricing what Go would refuse, or refusing to
  // price what Go would submit, is the same split that let a disabled control charge; the
  // payload already carries fallbackVersion() as its version_id, so the quote is for exactly
  // what submits.
  const goReady = phase !== "closed" && !!((src && src.model_id) || fallbackVersion())
    && !isVideo && !ratioDisabled;

  // A shrinking cap (mode/image change) clamps the stored ratio so the thumb never exceeds max.
  useEffect(() => {
    if (mx && ratio > mx) setRatio(mx);
  }, [mx, ratio]);

  let ratioMaxNote = "", dimsNote = "";
  if (!mx) {
    dimsNote = (w && hh)
      ? "This page did not receive the upscale limits, so the ratio cannot be checked here."
      : "This image has no recorded size, so the ratio cannot be checked.";
  } else {
    ratioMaxNote = (mx <= 1) ? "" : ("· max " + mx.toFixed(1) + "× for this picture");
    dimsNote = (mx <= 1)
      ? ("This picture is already at PixAI’s ceiling for " + (mode === "enlarge" ? "Upscale" : "Hires") + ".")
      : (w + "×" + hh + " → " + ow + "×" + oh);
  }

  const sourceNote = !src ? "" : isVideo ? "" : (src.width && src.height)
    ? (src.width + "×" + src.height + " source") : "This image has no recorded size.";
  const modeHint = (MODES.find((m) => m.key === mode) || MODES[0]).hint;

  let modelNote = "", showPickBtn = false;
  if (src && src.model_id) {
    modelNote = (src.model_name || src.model_id) + (src.model_picked ? " · chosen" : " · from this image");
  } else if (src && !isVideo) {
    showPickBtn = true;
    modelNote = src.local_import
      ? "You imported this file, so PixAI has no record of which model made it. Upscaling with "
        + "PixAI’s own upscale model — pick a different one if you’d rather."
      : "Your catalog does not know which model made this image, so it will upscale with PixAI’s "
        + "own upscale model. Pick a different one, or fill the catalog in with:  --backfill-full-meta";
  }

  // ---- the SAME body /api/price + /api/generate take from the drawer (verbatim _payload) -------
  const payload = () => {
    const s = src || {};
    const r = ratioDisabled ? null : effRatio;
    const body = {
      // From the image: the catalog's model_id is the task's submitted `modelId` = a VERSION id
      // (goes out as version_id; as model_id it hits the model->versions lookup, matches nothing,
      // "pick a model first"). From the picker: a real MODEL id the server resolves to its current
      // version. Nothing -> the version PixAI's own upscale submits.
      model_id: s.model_picked ? (s.model_id || "") : "",
      version_id: s.model_picked ? "" : (s.model_id || fallbackVersion()),
      prompt: s.prompt || "",
      negative: s.negative || "",
      width: parseInt(s.width, 10) || 0,
      height: parseInt(s.height, 10) || 0,
      steps: parseInt(s.steps, 10) || 25,
      cfg: parseFloat(s.cfg) || 7,
      count: 1,
      ref_media_id: s.media_id || "",
      ref_strength: 0.55,
      prompt_helper: false,
    };
    if (mode === "enlarge") {
      body.enlarge = r;
      body.enlarge_model = scaler || "";
    } else {
      body.upscale = r;
      body.upscale_denoise = denoise;
      body.upscale_denoise_steps = denoiseSteps || 26;
    }
    return body;
  };

  /* The shared price probe (gen/usePriceProbe.js) owns the debounce, the seq guard, the abort
     timeout and the payload-identity spend gate; this panel supplies the payload and the ONE
     predicate above. Idle only when Go itself is impossible -- a plain clear() back to the
     badge's own hint. (A failed fetch still passes null, which is the badge's red
     could-not-verify state, NOT clear(); the probe keeps that distinction.) */
  const build = useCallback(() => ({ payload: payload(), idle: goReady ? null : true }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [src, mode, ratio, effRatio, scaler, denoise, denoiseSteps, ratioDisabled, goReady]);
  // Closed, the panel holds no armed timer and no request out (its consumers keep it mounted
  // between opens); re-opening forces a re-price, because the badge is idle again on screen.
  const probe = usePriceProbe({ build, costRef, enabled: phase !== "closed" });
  // Re-price on any change to a pricing input (the vanilla fired _price from each handler).
  useEffect(() => { probe.refresh(); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [src, mode, ratio, scaler, denoise, denoiseSteps, ratioDisabled, probe.refresh]);
  // The Go gate: the panel's own readiness AND a settled quote for THIS payload.
  const canGo = goReady && probe.canSubmit;

  // Global listeners for the custom scaler dropdown, added ONLY while open -- the cleanup is the
  // React answer to the vanilla's leak risk (globals removed only by _closeScaler).
  useEffect(() => {
    if (!scalerOpen) return undefined;
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); setScalerOpen(false); } };
    const onDoc = (e) => {
      if (scalerWrapRef.current && scalerWrapRef.current.contains(e.target)) return;
      setScalerOpen(false);
    };
    window.addEventListener("keydown", onKey, true);   // capture, before the lightbox's own Esc
    document.addEventListener("click", onDoc);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      document.removeEventListener("click", onDoc);
    };
  }, [scalerOpen]);

  // Reveal the picker at the top of the scroll container (the flyout IS the scroll container) and
  // land focus in the search box -- the vanilla's _openPicker courtesy.
  useEffect(() => {
    if (!pickerOpen) return;
    const host = pickHostRef.current, root = rootRef.current;
    if (!host || !root) return;
    requestAnimationFrame(() => {
      if (root.scrollHeight > root.clientHeight + 1) {
        root.scrollTop = Math.max(0, host.offsetTop - root.offsetTop - 8);
      } else {
        try { host.scrollIntoView({ block: "nearest" }); } catch { /* older engines */ }
      }
      const q = host.querySelector("input");
      if (q && q.focus) q.focus();
    });
  }, [pickerOpen]);

  // ---- imperative handle: the consumers' open/close contract, verbatim ------------------------
  useImperativeHandle(ref, () => ({
    open(what) {
      clearTimeout(closeTimer.current);
      setPhase("open");
      setMsg(null);
      setPickerOpen(false);
      const mine = ++openSeq.current;
      // A slow first /api/image-meta landing after a second open() is discarded, so the panel --
      // and the PAID submit it is one click from making -- never binds to a stale picture.
      const done = (row) => {
        if (mine !== openSeq.current) return;
        setSrc(row || null);
        if (!row) setMsg({ text: "Could not load this image.", bad: true });
        else if (row.is_video) setMsg({ text: "Upscale works on images, not videos.", bad: true });
      };
      if (what && typeof what === "object") { done(what); return; }
      fetch("/api/image-meta/" + encodeURIComponent(String(what)))
        .then((r) => r.json())
        .then((d) => done(d && !d.error ? d : null), () => done(null));
    },
    close() {
      setPhase((p) => {
        if (p !== "open") return p;                 // no-op if not open
        setScalerOpen(false);                       // an open dropdown never outlives its panel
        clearTimeout(closeTimer.current);
        // Defer the display:none flip 340ms so the exit keyframes are ever seen (overlay law).
        closeTimer.current = setTimeout(() => setPhase("closed"), 340);
        return "closing";
      });
    },
    isOpen() { return phaseRef.current === "open" || phaseRef.current === "closing"; },
    isClosing() { return phaseRef.current === "closing"; },
  }), []);

  useEffect(() => () => clearTimeout(closeTimer.current), []);

  const handleClose = () => {
    setPhase((p) => {
      if (p !== "open") return p;
      setScalerOpen(false);
      clearTimeout(closeTimer.current);
      closeTimer.current = setTimeout(() => setPhase("closed"), 340);
      return "closing";
    });
  };

  const onModelPick = (row) => {
    if (!row || !row.model_id) return;
    // Recorded on the source so every later price/submit carries it, flagged CHOSEN (the panel
    // says which it is -- upscaling under a model the picture was not made with changes its look).
    setSrc((s) => Object.assign({}, s, {
      model_id: String(row.model_id),
      model_name: row.title || String(row.model_id),
      model_picked: true,
    }));
    setPickerOpen(false);
  };

  // ---- the spend (verbatim _submit): the ONLY POST /api/generate ------------------------------
  const doSubmit = () => {
    if (!goReady || busyRef.current) return;
    // PAYLOAD IDENTITY gate -- the button is already disabled on it; this is the click that
    // slips through a stale render (a keyboard Enter needs no repaint to fire).
    if (!probe.canSubmit) { probe.refresh(); return; }
    busyRef.current = true;                         // latch, independent of render timing
    setBusy(true);
    const mid = src.media_id;                        // captured before the await
    fetch("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    })
      .then((r) => r.json())
      .then((d) => {
        busyRef.current = false; setBusy(false);
        if (!d || d.error || !d.task_id) {
          setMsg({ text: (d && d.error) || "Could not start the upscale.", bad: true });
          return;
        }
        setMsg(null);
        // The submit DEBITED credits or a card; the payload is byte-identical, so only a
        // FORCED re-price gets past the short-circuit. (This panel closes on success, so the
        // re-open's own forced prime usually gets there first -- kept so the rule reads the
        // same on every cost line: a spend always invalidates the verdict that allowed it.)
        probe.refresh({ force: true });
        handleClose();
        if (typeof onDone === "function") onDone({ media_id: mid, task_id: d.task_id });
        if (window.Toast) {
          window.Toast.show({
            kind: "ok", title: "Upscale started",
            msg: "Watch it in Activity · the result lands in your gallery",
          });
        }
      })
      .catch((e) => {
        busyRef.current = false; setBusy(false);
        setMsg({ text: "Could not start the upscale: " + ((e && e.message) || e), bad: true });
      });
  };

  const cls = "upscale-panel" + (inline ? " inline" : "")
    + (phase === "open" || phase === "closing" ? " open" : "")
    + (phase === "closing" ? " closing" : "");

  return (
    <div
      ref={rootRef}
      className={cls}
      onClick={(e) => { if (!inline && e.target === e.currentTarget) handleClose(); }}
    >
      <div className="mgu-card">
        <div className="mgu-head">
          <span>⇱ Upscale</span>
          {!inline && (
            <button type="button" className="x" aria-label="Close" onClick={handleClose}>×</button>
          )}
        </div>
        <div className="mgu-body">
          <div className="mgu-note">{sourceNote}</div>

          <div className="mgu-lbl">Method</div>
          <div className="mgu-seg">
            {MODES.map((m) => (
              <button
                key={m.key} type="button"
                className={mode === m.key ? "on" : ""}
                onClick={() => setMode(m.key)}
              >
                {m.label}
                <span className="mgu-tip">{m.hint}</span>
              </button>
            ))}
          </div>
          <div className="mgu-note">{modeHint}</div>

          <div className="mgu-lbl">
            Ratio <span className="mgu-val">{effRatio.toFixed(1)}×</span>{" "}
            <span className="mgu-dim">{ratioMaxNote}</span>
          </div>
          <input
            type="range" min="1.1" step="0.1" max={String(mx || 3)}
            value={String(effRatio)} disabled={ratioDisabled}
            onChange={(e) => setRatio(+e.target.value)}
          />
          <div className="mgu-note">{dimsNote}</div>

          {mode === "enlarge" && (
            <div data-mgu="upscaler">
              <div className="mgu-lbl">Upscaler</div>
              <div className="mgu-scalerwrap" ref={scalerWrapRef}>
                <button
                  type="button" className="mgu-scalerbox"
                  aria-haspopup="listbox" aria-expanded={scalerOpen}
                  onClick={(e) => { e.stopPropagation(); setScalerOpen((v) => !v); }}
                >
                  <span>{scaler}</span>
                  <span className="mgu-caret">▾</span>
                </button>
                {scalerOpen && (
                  <div className="mgu-scalerlist" role="listbox">
                    {scalerNames.map((name) => (
                      <div
                        key={name} role="option"
                        className={"mgu-scaleropt" + (name === scaler ? " on" : "")}
                        onClick={(e) => { e.stopPropagation(); setScaler(name); setScalerOpen(false); }}
                      >
                        {name}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {mode === "upscale" && (
            <div data-mgu="denoise">
              <div className="mgu-lbl">
                Denoising strength <span className="mgu-val">{denoise.toFixed(2)}</span>
                <span className="mgu-dim"> · PixAI: works better 0.4–0.6</span>
              </div>
              <input
                type="range" min="0.01" max="0.99" step="0.01"
                value={String(denoise)} onChange={(e) => setDenoise(+e.target.value)}
              />
              <div className="mgu-lbl">Denoising steps</div>
              <input
                className="mgu-sel" type="number" min="1" max="50" step="1"
                value={String(denoiseSteps)}
                onChange={(e) => setDenoiseSteps(parseInt(e.target.value, 10) || 26)}
              />
            </div>
          )}

          <div className="mgu-lbl">Model</div>
          <div className="mgu-note">{modelNote}</div>
          {showPickBtn && !pickerOpen && (
            <button
              type="button" className="mgu-sel"
              style={{ cursor: "pointer", textAlign: "left" }}
              onClick={() => setPickerOpen(true)}
            >
              Choose a model…
            </button>
          )}
          {pickerOpen && (
            <div ref={pickHostRef} data-mgu="picker">
              <ModelPicker kind="base" visible onPick={onModelPick} />
            </div>
          )}

          <CostBadge
            ref={costRef}
            hint="The cost appears once this image has a model."
            cardLabel="a card"
          />

          <button type="button" className="mgu-go" disabled={!canGo || busy} onClick={doSubmit}>
            {busy ? "Submitting…" : "Upscale"}
          </button>
          {msg && <div className={"mgu-note" + (msg.bad ? " bad" : "")}>{msg.text}</div>}
        </div>
      </div>
    </div>
  );
});

export default UpscalePanel;
