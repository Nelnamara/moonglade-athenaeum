import { useCallback, useEffect, useRef, useState } from "react";
import { buildPayload, clampLoras, GEN_DEFAULTS, goGate } from "./genCore.js";
import { submitTask, useResultLines } from "./submitTask.js";

/* The image-generation hook. Mirrors the classic Gen IIFE's timing contracts:
   - price: 250ms debounce + a seq counter so a stale response never paints over
     a newer one (the classic's costSeq), and the badge goes to "checking" the
     moment a refresh is scheduled so a stale number is never on screen while a
     newer request is pending;
   - version/LoRA resolve: seq-guarded the same way;
   - submit: a busyRef latch makes double-submit impossible independent of React
     scheduling, the button re-enables when the server ANSWERS, concurrent
     submissions each own a result line, and there is NO retry anywhere. */

export default function useGenerate({ costRef }) {
  const [s, setS] = useState(GEN_DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [results, openLine] = useResultLines();
  const priceSeq = useRef(0);
  const priceTimer = useRef(0);
  const verSeq = useRef(0);
  const busyRef = useRef(false);

  const set = useCallback((patch) => setS((old) => ({ ...old, ...patch })), []);

  /* ---- price preview: same payload builder as submit, debounced ---- */
  const firePrice = useCallback(() => {
    const seq = ++priceSeq.current;
    const badge = costRef.current;
    const p = buildPayload(s);
    if (!p.version_id) { if (badge && badge.clear) badge.clear(); return; }
    fetch("/api/price", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    })
      .then((r) => r.json())
      .then((d) => { if (seq === priceSeq.current && costRef.current) costRef.current.setPrice(d); })
      .catch(() => {
        // fail-CLOSED: a failed check paints the badge's red "couldn't verify"
        // state, never silence and never "free".
        if (seq === priceSeq.current && costRef.current) costRef.current.setPrice(null);
      });
  }, [s, costRef]);

  const refreshPrice = useCallback(() => {
    // Blank the number FIRST: an old quote next to new settings is the one thing
    // worse than no quote (review: a click inside the debounce window spent
    // against a figure that had already stopped being true).
    const badge = costRef.current;
    if (badge && badge.setChecking) badge.setChecking();
    clearTimeout(priceTimer.current);
    priceTimer.current = setTimeout(firePrice, 250);
  }, [firePrice, costRef]);

  // Structural cost inputs only -- prompt/negative/seed text never refires,
  // matching the classic. steps IS structural (it changes the upscale pass too).
  useEffect(() => { refreshPrice(); }, [
    s.model, s.loras, s.ref, s.refStrength, s.boosters,
    s.aspect, s.size, s.customW, s.customH, s.count, s.highPriority,
    s.mode, s.steps,
  ]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- model pick -> version resolve (seq-guarded) ---- */
  const applyFromVersion = (v) => {
    const patch = {
      caps: v.capabilities || [],
      compat_neg: cget(v, "negativePrompt"),
      compat_steps: cget(v, "samplingSteps"),
      compat_cfg: cget(v, "cfgScale"),
      compat_upscale: cget(v, "upscale"),
      restrictions: v.restrictions || {},
      preset: {
        negative: v.negative_prompt || "", steps: v.sampling_steps,
        cfg: v.cfg_scale, sampler: v.sampling_method || "",
      },
    };
    return patch;
  };

  /* Only patch a field the version actually carries -- the classic's
     applyModelDefaults ("only for fields the model has data for"). The first cut
     wiped a typed negative/steps/cfg to empty on any preset-less model. */
  const presetPatch = (v) => {
    const out = {};
    if (v.negative_prompt) out.negative = v.negative_prompt;
    if (v.sampling_steps != null && v.sampling_steps !== "") out.steps = String(v.sampling_steps);
    if (v.cfg_scale != null && v.cfg_scale !== "") out.cfg = String(v.cfg_scale);
    return out;
  };

  /* Returns the applied model shape ({model_id, version_id, versions, ...}) on
     success and null on failure or a verSeq drop. Callers historically ignore
     this; Remix (issue #4) keys on it -- state can't answer "did MY apply
     land, and which versions exist" in an async flow (React batches the setS,
     so an eager-updater read right after the await sees the PRE-apply state;
     that false-negatived the exact-version check on a live run, 2026-08-13). */
  const applyModelRow = useCallback(async (row) => {
    const seq = ++verSeq.current;
    setS((old) => ({
      ...old,
      model: { model_id: row.model_id, title: row.title, thumb: row.preview_url || row.cover_url || "", version_id: "", resolving: true },
    }));
    try {
      const r = await fetch("/api/model-version?model_id=" +
        encodeURIComponent(row.model_id) + "&all=1");
      const d = await r.json();
      if (seq !== verSeq.current) return null;
      const versions = d.versions || [];
      const latest = versions.find((v) => v.is_latest) || versions[0];
      if (!latest || !latest.version_id) throw new Error(d.error || "no versions");
      const model = {
        model_id: row.model_id, title: row.title,
        thumb: row.preview_url || row.cover_url || "",
        version_id: latest.version_id, model_type: latest.model_type || "",
        versions, ...applyFromVersion(latest),
      };
      setS((old) => ({
        ...old, model,
        // weights re-clamped to the NEW architecture, and an armed hires chip
        // disarmed when this version can't upscale (classic gateBooster).
        loras: clampLoras(old.loras, model.model_type),
        boosters: model.compat_upscale === false
          ? { ...old.boosters, hires: false } : old.boosters,
        ...presetPatch(latest),
      }));
      return model;
    } catch {
      if (seq !== verSeq.current) return null;
      setS((old) => ({
        ...old,
        model: { model_id: row.model_id, title: row.title, thumb: row.preview_url || row.cover_url || "", version_id: "", failed: true },
      }));
      if (window.Toast) window.Toast.show({ kind: "err", title: "Model lookup failed", msg: row.title });
      return null;
    }
  }, []);

  const pickVersion = useCallback((versionId) => {
    setS((old) => {
      const v = (old.model.versions || []).find((x) => x.version_id === versionId);
      if (!v) return old;
      const model = {
        ...old.model, version_id: v.version_id, model_type: v.model_type || "",
        ...applyFromVersion(v),
      };
      return {
        ...old, model,
        loras: clampLoras(old.loras, model.model_type),
        boosters: model.compat_upscale === false
          ? { ...old.boosters, hires: false } : old.boosters,
        ...presetPatch(v),
      };
    });
  }, []);

  /* ---- LoRA lifecycle ----
     The multi picker hands us the row itself plus its selected flag; it has
     ALREADY resolved version/architecture/trigger words, so this upserts from
     the row and only falls back to a fetch when a field is missing.
     trigger_words is a comma-separated STRING server-side, not an array. */
  const addLora = useCallback(async (row) => {
    let present = false;
    setS((old) => {
      present = old.loras.some((l) => l.model_id === row.model_id);
      if (present) return old;
      return {
        ...old,
        loras: old.loras.concat([{
          model_id: row.model_id, title: row.title, preview_url: row.preview_url,
          // Remix (issue #4) hands rows carrying the task's EXACT weight; the
          // picker's market rows have none and keep the 0.7 default. Honoring
          // it here (not via a follow-up setLora) is what keeps a two-versions-
          // of-one-LoRA task from cross-patching the wrong entry's weight
          // (adversarial review 2026-08-13, finding 1.1).
          version_id: row.version_id || "",
          weight: Number.isFinite(+row.weight) ? +row.weight : 0.7,
          lora_base_type: row.lora_base_model_type || row.model_type || "",
          trigger_words: typeof row.trigger_words === "string" ? row.trigger_words : "",
          versions: [],
        }]),
      };
    });
    if (present || row.version_id) return;   // the picker already resolved it
    try {
      const r = await fetch("/api/model-version?model_id=" +
        encodeURIComponent(row.model_id) + "&all=1");
      const d = await r.json();
      const versions = d.versions || [];
      const latest = versions.find((v) => v.is_latest) || versions[0];
      if (!latest || !latest.version_id) throw new Error("unresolved");
      setS((old) => ({
        ...old,
        loras: old.loras.map((l) => l.model_id === row.model_id ? {
          ...l, version_id: latest.version_id,
          lora_base_type: latest.lora_base_model_type || "",
          trigger_words: typeof latest.trigger_words === "string" ? latest.trigger_words : "",
          versions,
        } : l),
      }));
    } catch {
      setS((old) => ({
        ...old,
        loras: old.loras.map((l) => l.model_id === row.model_id ? { ...l, failed: true } : l),
      }));
    }
  }, []);

  const removeLora = useCallback((modelId) => {
    setS((old) => ({ ...old, loras: old.loras.filter((l) => l.model_id !== modelId) }));
  }, []);

  const setLora = useCallback((modelId, patch) => {
    setS((old) => ({
      ...old,
      loras: old.loras.map((l) => (l.model_id === modelId ? { ...l, ...patch } : l)),
    }));
  }, []);

  /* ---- submit: NO retries, body-keyed errors, adjusted always recorded ---- */
  const generate = useCallback(async (loraCap) => {
    if (busyRef.current) return;              // latch, independent of render timing
    if (goGate(s, loraCap)) return;
    busyRef.current = true;
    setBusy(true);
    const emit = openLine("Submitting…");
    // ONE shared submit path for every spend route -- see gen/submitTask.js for
    // the contract it enforces (no retry, body-keyed errors, adjusted on the
    // line, cb(phase, data) tracking).
    await submitTask("/api/generate", buildPayload(s), { label: "Generated", emit });
    busyRef.current = false;                   // the classic unlocks on ANSWER
    setBusy(false);
  }, [s, openLine]);

  return { s, set, busy, results, applyModelRow, pickVersion,
           addLora, removeLora, setLora, generate, refreshPrice };
}


function cget(v, key) {
  const c = v.compatibility || {};
  return key in c ? c[key] : undefined; // undefined = unknown = fail-open
}
