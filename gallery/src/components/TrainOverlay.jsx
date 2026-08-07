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

// PixAI's real LoRA categories + their display labels, probed live off the train-lora
// page 2026-08-06 (the design's character/style/concept was placeholder). "detail"
// shows as "Detail Enhancement", matching the site.
const CATEGORIES = [
  ["character", "Character"], ["animal", "Animal"], ["style", "Style"],
  ["realistic", "Realistic"], ["pose", "Pose"], ["clothing", "Clothing"],
  ["background", "Background"], ["detail", "Detail Enhancement"], ["other", "Other"],
];
const MIN_IMAGES = 10;
const MAX_IMAGES = 100;

export default function TrainOverlay({ onClose }) {
  useScrollLock();
  const [csrf, setCsrf] = useState("");
  const [quota, setQuota] = useState(null);
  const [pool, setPool] = useState([]);       // recent library images to choose from
  const [picked, setPicked] = useState([]);   // media_ids in the dataset
  // Trainable base models grouped by architecture -- the real Model Type -> Model Theme
  // structure (each group is one architecture: DiT.2, DiT.1, SDXL, SD 1.5).
  const [groups, setGroups] = useState([]);
  const [archIdx, setArchIdx] = useState(0);       // selected Model Type
  const [baseModel, setBaseModel] = useState("");  // selected theme's VERSION id

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
    fetch("/api/train/models")
      .then((r) => r.json())
      .then((d) => {
        const gs = d.groups || [];
        setGroups(gs);
        if (gs.length && gs[0].models.length) setBaseModel(gs[0].models[0].version_id);
      })
      .catch(() => {});
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // Selecting a Model Type shows that architecture's models and defaults to its first.
  const pickArch = (i) => {
    setArchIdx(i);
    const g = groups[i];
    setBaseModel(g && g.models.length ? g.models[0].version_id : "");
  };
  const themes = (groups[archIdx] || {}).models || [];
  const selectedPrice = (groups[archIdx] || {}).price ?? null;   // credits for this arch

  const toggle = (mid) => {
    setPicked((cur) => (cur.includes(mid)
      ? cur.filter((x) => x !== mid)
      : (cur.length >= MAX_IMAGES ? cur : cur.concat([mid]))));
  };

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

          {/* The cost position, stated before anything else. With free quota it's free;
              without, we now quote the REAL price of the selected base (captured matrix). */}
          <div className={"mgtr-cost" + (quota === 0 ? " paid" : "")}>
            {quota === null ? "checking your free trainings…"
              : quota > 0
                ? "✓ " + quota + " free training" + (quota === 1 ? "" : "s") + " left — this one costs nothing."
                : (selectedPrice != null
                    ? "⚠ No free trainings left — this base costs " + selectedPrice.toLocaleString() + " credits to train."
                    : "⚠ No free trainings left. Training charges real credits — check the price on PixAI before going ahead.")}
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

              {groups.length > 1 && (
                <>
                  <label className="mgpub-lab">Model Type</label>
                  <div className="mgtr-types">
                    {groups.map((g, i) => (
                      <button type="button" key={g.arch}
                        className={"mgtr-type" + (archIdx === i ? " on" : "")}
                        onClick={() => pickArch(i)}>{g.label}</button>
                    ))}
                  </div>
                </>
              )}

              <label className="mgpub-lab">Model Theme</label>
              {themes.length === 0 ? (
                <div className="mgpub-hint">loading base models…</div>
              ) : (
                <div className="mgtr-themes">
                  {themes.map((m) => (
                    <button type="button" key={m.version_id} title={m.title}
                      className={"mgtr-theme" + (baseModel === m.version_id ? " on" : "")}
                      onClick={() => setBaseModel(m.version_id)}>
                      {/* Covers are PixAI CDN URLs the browser can't hotlink cross-origin
                          from localhost -- proxied through the (host-guarded) backend. The
                          selected card's img load can get aborted by the selection
                          re-render; onError retries it once (cache-buster) so the browser
                          doesn't leave it blank. */}
                      {/* NOT loading="lazy": the theme grid sits below the panel's fold,
                          so lazy covers never entered the viewport and never loaded. Only
                          ~15 small thumbnails, so eager is fine. */}
                      {m.cover ? <img src={"/api/train/cover?u=" + encodeURIComponent(m.cover)} alt=""
                        onError={(e) => { const el = e.currentTarget; if (!el.dataset.retried) { el.dataset.retried = "1"; el.src = el.src + "&r=1"; } }} /> : null}
                      <span className="n">{m.title}</span>
                      {baseModel === m.version_id && <span className="mgtr-check">✓</span>}
                    </button>
                  ))}
                </div>
              )}

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
