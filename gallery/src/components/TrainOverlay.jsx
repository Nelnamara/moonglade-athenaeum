import React, { useEffect, useState } from "react";
import "../styles/overlays.css";
import "../styles/publish.css";
import "../styles/train.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* Train a LoRA — Frontend Gallery.dc.html's ovTrain (markup L392-500+), on the real
   createTrainingTask pipeline.

   Left column is the dataset (the design's "Dataset images N/100", min-10 gate, and its
   tile grid of recent generations to toggle on/off). Right column is the design's form:
   Name of LoRA, Trigger words with a live counter, Category, Model Type, Model Theme
   cards — ending in the submit.

   Where the DC carries demo data the same control is wired to the real equivalent:
   - the dataset tiles are your real recent library images (the DC's own tile grid,
     with actual art in it), toggled by clicking, exactly as drawn;
   - Model Theme cards are real base models from /api/model-search?kind=base — the same
     route the Generate drawer's own model picker already uses;
   - Model Type is the architecture FILTER over those cards. It is a real filter, not a
     separate submitted field: PixAI's own form uses modelType for validation/pricing and
     derives the actual model from the chosen base, which is what baseModelId carries.

   COST. This is the app's newest spend path, so it leads with the truth rather than a
   button: PixAI grants a free-training QUOTA (currency `free::user_lora_training` — not
   a kaisuuken card, which is generation-only), and the panel shows how many are left.
   With quota it is genuinely free. With none, PixAI prices training client-side so this
   app CANNOT quote the amount; the server refuses that submit unless the extra
   accept-cost acknowledgment is sent, and this panel makes you tick it deliberately. */

const CATEGORIES = [["character", "Character"], ["style", "Style"], ["concept", "Concept"]];
const MIN_IMAGES = 10;
const MAX_IMAGES = 100;

export default function TrainOverlay({ onClose }) {
  useScrollLock();
  const [csrf, setCsrf] = useState("");
  const [quota, setQuota] = useState(null);
  const [pool, setPool] = useState([]);       // recent library images to choose from
  const [picked, setPicked] = useState([]);   // media_ids in the dataset
  const [models, setModels] = useState([]);
  const [modelType, setModelType] = useState("");
  const [baseModel, setBaseModel] = useState("");

  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [category, setCategory] = useState("");

  const [ask, setAsk] = useState(null);
  const [acceptCost, setAcceptCost] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);

  useEffect(() => {
    fetch("/api/myart/items").then((r) => r.json()).then((d) => setCsrf(d.csrf || "")).catch(() => {});
    fetch("/api/train/quota").then((r) => r.json())
      .then((d) => setQuota(typeof d.free_trainings === "number" ? d.free_trainings : 0))
      .catch(() => setQuota(0));
    fetch("/api/next/library?page=1&page_size=60&media=image&sort=newest")
      .then((r) => r.json()).then((d) => setPool(d.items || [])).catch(() => {});
    fetch("/api/model-search?kind=base&size=24&sort=popular")
      .then((r) => r.json())
      .then((d) => {
        const rows = d.models || d.items || d.results || [];
        setModels(rows);
        if (rows.length && !baseModel) setBaseModel(String(rows[0].id || rows[0].model_id || ""));
      })
      .catch(() => {});
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (mid) => {
    setPicked((cur) => (cur.includes(mid)
      ? cur.filter((x) => x !== mid)
      : (cur.length >= MAX_IMAGES ? cur : cur.concat([mid]))));
  };

  // Architecture filter over the theme cards (the DC's Model Type control), built from
  // whatever the real model rows actually report rather than a guessed enum list.
  const types = Array.from(new Set(models.map((m) => m.model_type || m.modelType || "").filter(Boolean)));
  const shownModels = modelType
    ? models.filter((m) => (m.model_type || m.modelType) === modelType)
    : models;

  const body = () => ({
    base_model_id: baseModel, media_ids: picked, title: name,
    trigger_words: trigger, category, csrf,
  });

  const preview = async () => {
    setBusy(true); setErr("");
    try {
      const r = await fetch("/api/train/submit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body()),
      });
      const p = await r.json();
      if (p.error) { setErr(p.error); return; }
      setAsk(p); setAcceptCost(false);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true); setErr("");
    try {
      const r = await fetch("/api/train/submit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body(), confirm: true,
                               ...(ask && !ask.is_free ? { accept_credit_cost: acceptCost } : {}) }),
      });
      const res = await r.json();
      if (res.error) { setErr(res.error); return; }
      setDone(res); setAsk(null);
      if (typeof res.free_trainings_left === "number") setQuota(res.free_trainings_left);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  const enough = picked.length >= MIN_IMAGES;

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgtr-slab" role="dialog" aria-label="Train a LoRA">
          <div className="mgpub-head">
            <div>
              <div className="mgpub-title">⚗ Train a LoRA</div>
              <div className="mgtr-sub">runs on PixAI — the library keeps the receipts</div>
            </div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {/* The cost position, stated before anything else. */}
          <div className={"mgtr-cost" + (quota === 0 ? " paid" : "")}>
            {quota === null ? "checking your free trainings…"
              : quota > 0
                ? "✓ " + quota + " free training" + (quota === 1 ? "" : "s") + " left — this one costs nothing."
                : "⚠ No free trainings left. Training charges real credits, and PixAI prices it in its own client — this app can't quote the amount."}
          </div>

          <div className="mgtr-body">
            {/* LEFT: the dataset */}
            <div className="mgtr-left">
              <div className="mgtr-dshead">
                <span>Dataset images <b>{picked.length}/{MAX_IMAGES}</b></span>
                <span className={enough ? "ok" : "need"}>
                  {enough ? "ready" : "Min " + MIN_IMAGES + " required"}
                </span>
              </div>
              <div className="mgtr-bar">
                <div className="mgtr-barfill"
                  style={{ width: Math.min(100, (picked.length / MAX_IMAGES) * 100) + "%" }} />
              </div>
              <div className="mgtr-tilehead">Recent generations — click to add or remove</div>
              <div className="mgtr-tiles">
                {pool.map((p) => {
                  const on = picked.includes(p.media_id);
                  return (
                    <button type="button" key={p.media_id}
                      className={"mgtr-tile" + (on ? " on" : "")}
                      onClick={() => toggle(p.media_id)} title={on ? "Remove" : "Add"}>
                      <img src={p.thumb} alt="" loading="lazy" />
                      {on && <span className="mgtr-check">✓</span>}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* RIGHT: the form */}
            <div className="mgtr-right">
              <label className="mgpub-lab">Name of LoRA</label>
              <input className="mgpub-in" value={name} placeholder="eg: my LoRA"
                onChange={(e) => setName(e.target.value)} />

              <label className="mgpub-lab">Trigger words</label>
              <div className="mgtr-trigwrap">
                <textarea className="mgpub-in" rows={2} value={trigger}
                  placeholder="eg: hatsune miku, aqua hair, twin tails"
                  onChange={(e) => setTrigger(e.target.value)} />
                <span className="mgtr-trigcount">{trigger.trim().length}</span>
              </div>
              <div className="mgpub-hint">
                Stick to letters, numbers and common symbols. No double spaces, and none
                at the start or end — those get cleaned up before submitting.
              </div>

              <label className="mgpub-lab">Category</label>
              <select className="mgpub-in" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">Select a category</option>
                {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>

              {types.length > 1 && (
                <>
                  <label className="mgpub-lab">Model Type</label>
                  <div className="mgtr-types">
                    <button type="button" className={"mgtr-type" + (modelType === "" ? " on" : "")}
                      onClick={() => setModelType("")}>All</button>
                    {types.map((t) => (
                      <button type="button" key={t}
                        className={"mgtr-type" + (modelType === t ? " on" : "")}
                        onClick={() => setModelType(t)}>{t}</button>
                    ))}
                  </div>
                </>
              )}

              <label className="mgpub-lab">Model Theme</label>
              <div className="mgtr-themes">
                {shownModels.map((m) => {
                  const id = String(m.id || m.model_id || "");
                  return (
                    <button type="button" key={id} title={m.name || id}
                      className={"mgtr-theme" + (baseModel === id ? " on" : "")}
                      onClick={() => setBaseModel(id)}>
                      {m.cover_url || m.thumb ? <img src={m.cover_url || m.thumb} alt="" loading="lazy" /> : null}
                      <span className="n">{m.name || id}</span>
                      {baseModel === id && <span className="mgtr-check">✓</span>}
                    </button>
                  );
                })}
              </div>

              {err && <div className="mgpub-note err">⚠ {err}</div>}

              {done ? (
                <div className="mgpub-note ok">
                  ✓ Training submitted{done.was_free ? " — it used one of your free trainings" : ""}.
                  {done.task && done.task.refId ? " PixAI is building it now; it'll appear on your models page." : ""}
                </div>
              ) : ask ? (
                <div className="mgpub-confirm">
                  <div className="t">Start this training on PixAI?</div>
                  <div className="b">
                    <b>{ask.title}</b> · {ask.image_count} images · {ask.category}
                    <div className="n">{ask.cost_note}</div>
                    {!ask.is_free && (
                      <label className="mgtr-accept">
                        <input type="checkbox" checked={acceptCost}
                          onChange={(e) => setAcceptCost(e.target.checked)} />
                        <span>I've checked the price on PixAI and want to spend credits.</span>
                      </label>
                    )}
                  </div>
                  <div className="a">
                    <button type="button" className="mgpub-ghost" onClick={() => setAsk(null)} disabled={busy}>Back</button>
                    <button type="button" className="mgpub-go" disabled={busy || (!ask.is_free && !acceptCost)}
                      onClick={confirm}>{busy ? "submitting…" : "Start training"}</button>
                  </div>
                </div>
              ) : (
                <button type="button" className="mgpub-go big" disabled={busy || !enough || !baseModel}
                  onClick={preview}>
                  {busy ? "checking…" : enough ? "⚗ Train it" : "Add " + (MIN_IMAGES - picked.length) + " more image" + (MIN_IMAGES - picked.length === 1 ? "" : "s")}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
