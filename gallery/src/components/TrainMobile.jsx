import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import useSheet from "../hooks/useSheet.js";
import MobileSheet from "./MobileSheet.jsx";
import { acceptCostField } from "../gen/trainCore.js";
import "../styles/train.css";
import "../styles/train-mobile.css";

/* Train a LoRA -- mobile, replaces the "no backend route" placeholder (2026-08-07,
   Moonglade Mobile.dc.html screenIsTrain block + the trainconfirm sheet). Real data
   throughout, the exact real createTrainingTask pipeline desktop's TrainOverlay.jsx
   already proved: /api/train/quota, /api/train/models (curated base list + real
   pricing), /api/train/recent-tasks (new, below), /api/train/submit (preview then
   confirm).

   Real-data adaptation, disclosed: the design's dataset picker taps a TASK tile, and
   its own copy says "each task adds 4" -- a fixed demo constant (TRAIN_TILES was 6
   hardcoded fake tasks, always contributing exactly 4 images each). Real generation
   batches are 1-4 images, not always 4, so /api/train/recent-tasks (added this pass)
   returns each task's REAL image list; tapping a tile adds all of THAT task's real
   images, and the running N/100 count and the "min 10" gate sum real counts, not
   tiles*4. The mechanism the design specifies (tap a task, not an image) is real and
   kept exactly; only the fixed "4" is a placeholder replaced with the true number.

   Category/Model Type use the same real values desktop's build already corrected the
   design's own placeholder demo lists to (9 real PixAI categories; the DiT.3/DiT.2/DiT.1/
   SDXL/SD 1.5 architectures with PixAI's own training base list + per-arch pricing) -- not
   re-litigated here, just reused. Cost, free runs and the pre-selected base follow
   TrainOverlay.jsx's header (SCOPE_2026-09-26 E7): quota or a training free card makes a run
   free, otherwise its price is quoted, and the default base is the server's
   default_version_id (the first SDXL row), not the first group's first model. */

const CATEGORIES = [
  ["character", "Character"], ["animal", "Animal"], ["style", "Style"],
  ["realistic", "Realistic"], ["pose", "Pose"], ["clothing", "Clothing"],
  ["background", "Background"], ["detail", "Detail Enhancement"], ["other", "Other"],
];
const MIN_IMAGES = 10;
const MAX_IMAGES = 100;

/* The base the panel pre-selects: the server's `default_version_id` -- PixAI's own default,
   the first SDXL row of its training list (SCOPE_2026-09-26 E7) -- and the Model Type group
   that holds it. Never "the first group's first model": DiT.3 (Tsubaki.3, 100,000 credits)
   sorts first now, so that rule would pre-select the most expensive base on the list. */
function defaultBase(groups, versionId) {
  const gi = groups.findIndex((g) => g.models.some((m) => m.version_id === versionId));
  if (gi >= 0) return { archIdx: gi, baseModel: versionId };
  return { archIdx: 0, baseModel: "" };
}

export default function TrainMobile({ onClose }) {
  const [csrf, setCsrf] = useState("");
  const [quota, setQuota] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [pickedTasks, setPickedTasks] = useState(() => new Set());
  const [groups, setGroups] = useState([]);
  const [archIdx, setArchIdx] = useState(0);
  const [baseModel, setBaseModel] = useState("");

  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [category, setCategory] = useState("");

  // 'confirm' | null -- shared timer-safe machine (hooks/useSheet.js)
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  const [ask, setAsk] = useState(null);
  const [acceptCost, setAcceptCost] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);


  useEffect(() => {
    apiGet("/api/myart/items").then((d) => setCsrf(d.csrf || ""));
    apiGet("/api/train/quota")
      .then((d) => setQuota(typeof d.free_trainings === "number" ? d.free_trainings : 0));
    apiGet("/api/train/recent-tasks?limit=18").then((d) => setTasks(d.tasks || []));
    apiGet("/api/train/models")
      .then((d) => {
        const gs = d.groups || [];
        setGroups(gs);
        const def = defaultBase(gs, d.default_version_id || "");
        setArchIdx(def.archIdx);
        setBaseModel(def.baseModel);
      });
  }, []);

  const pickArch = (i) => {
    setArchIdx(i);
    const g = groups[i];
    setBaseModel(g && g.models.length ? g.models[0].version_id : "");
  };
  const themes = (groups[archIdx] || {}).models || [];
  const selectedPrice = (groups[archIdx] || {}).price ?? null;

  const toggleTask = (tid) => setPickedTasks((cur) => {
    const next = new Set(cur);
    if (next.has(tid)) next.delete(tid); else next.add(tid);
    return next;
  });

  const pickedMediaIds = tasks.filter((t) => pickedTasks.has(t.task_id))
    .flatMap((t) => t.media_ids).slice(0, MAX_IMAGES);
  const enough = pickedMediaIds.length >= MIN_IMAGES;

  const body = () => ({ base_model_id: baseModel, media_ids: pickedMediaIds, title: name,
    trigger_words: trigger, category, csrf });

  const preview = async () => {
    setBusy(true); setErr("");
    try {
      const p = await apiPost("/api/train/submit", body());
      if (p.error) { setErr(p.error); return; }
      setAsk(p); setAcceptCost(false); openSheet("confirm");
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };
  const confirm = async () => {
    setBusy(true); setErr("");
    try {
      const res = await apiPost("/api/train/submit",
        { ...body(), confirm: true, ...acceptCostField(ask, acceptCost) });
      // Same as PublishMobile: the error note lives under the sheet -- close it
      // so the failure is actually visible instead of a silent button revert.
      if (res.error) { setErr(res.error); closeSheet(); return; }
      setDone(res); closeSheet();
      if (typeof res.free_trainings_left === "number") setQuota(res.free_trainings_left);
    } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); }
  };

  return (
    <div className="trm-wrap">
      {done ? (
        <div className="trm-donebox">
          ✓ Training submitted{done.used_card ? " — it used your training free card"
            : done.was_free ? " — it used one of your free trainings" : ""}.
        </div>
      ) : (
        <>
          <div className={"trm-cost" + (quota === 0 ? " paid" : "")}>
            {quota === null ? "checking your free trainings…"
              : quota > 0 ? "✓ " + quota + " free training" + (quota === 1 ? "" : "s") + " left — this one costs nothing."
              : (selectedPrice != null
                  ? "⚠ No free trainings left — this base costs " + selectedPrice.toLocaleString() + " credits, unless a training free card covers it."
                  : "⚠ No free trainings left, and PixAI's price list has no price for this base.")}
          </div>

          <div className="trm-dshead">
            <span>Dataset images <b>{Math.min(pickedMediaIds.length, MAX_IMAGES)}/{MAX_IMAGES}</b></span>
            <span className={enough ? "ok" : "need"}>{enough ? "ready" : "Min " + MIN_IMAGES + " required"}</span>
          </div>
          <div className="trm-bar"><div className="trm-barfill" style={{ width: Math.min(100, pickedMediaIds.length) + "%" }} /></div>
          <div className="trm-tilehead">Recent generations — tap to add <i>· adds all of that task's images</i></div>
          <div className="trm-tiles">
            {tasks.map((t) => {
              const on = pickedTasks.has(t.task_id);
              return (
                <button type="button" key={t.task_id} className={"trm-tile" + (on ? " on" : "")}
                  onClick={() => toggleTask(t.task_id)}>
                  <img src={t.thumb} alt="" loading="lazy" />
                  <span className="trm-tilebadge">×{t.count}</span>
                  {on && <span className="trm-tilecheck">✓</span>}
                </button>
              );
            })}
          </div>

          <div className="pubm-lab" style={{ marginTop: 16 }}>Name of LoRA</div>
          <input className="pubm-in" value={name} placeholder="eg: my LoRA" onChange={(e) => setName(e.target.value)} />

          <div className="pubm-lab">Trigger words</div>
          <textarea className="pubm-in" rows={2} value={trigger} placeholder="eg: hatsune miku, aqua hair"
            onChange={(e) => setTrigger(e.target.value)} />

          <div className="pubm-lab">Category</div>
          <select className="pubm-in" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Select a category</option>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>

          {groups.length > 1 && (
            <>
              <div className="pubm-lab">Model Type</div>
              <div className="trm-typerow">
                {groups.map((g, i) => (
                  <button type="button" key={g.arch} className={"trm-typechip" + (archIdx === i ? " on" : "")}
                    onClick={() => pickArch(i)}>{g.label}</button>
                ))}
              </div>
            </>
          )}

          <div className="pubm-lab">Model theme <i>· {(groups[archIdx] || {}).label || ""}</i></div>
          <div className="trm-themerow">
            {themes.map((m) => (
              <button type="button" key={m.version_id} className={"trm-themechip" + (baseModel === m.version_id ? " on" : "")}
                onClick={() => setBaseModel(m.version_id)}>{m.title}</button>
            ))}
          </div>

          {err && <div className="pubm-note err" style={{ marginTop: 12 }}>⚠ {err}</div>}

          <button type="button" className="pubm-go" disabled={busy || !enough || !baseModel} onClick={preview}>
            {busy ? "checking…" : enough ? "Preview & start training →" : "Add " + (MIN_IMAGES - pickedMediaIds.length) + " more image" + (MIN_IMAGES - pickedMediaIds.length === 1 ? "" : "s")}
          </button>
        </>
      )}

      <MobileSheet open={sheet === "confirm"} closing={closing} onClose={closeSheet} title="QUEUE TRAINING RUN">
        {ask && (
          <>
            <div className="pubm-confirmmeta">
              <b>{name || "Untitled LoRA"}</b> · {(groups[archIdx] || {}).label} · {ask.image_count} images · {category || "no category"}
            </div>
            <div className="pubm-note" style={{ marginBottom: 12 }}>{ask.cost_note}{ask.image_note ? " " + ask.image_note : ""}</div>
            {!ask.is_free && (
              <label className="pubm-toggle" style={{ marginBottom: 12 }}>
                <input type="checkbox" checked={acceptCost} onChange={(e) => setAcceptCost(e.target.checked)} />
                <span>{ask.price != null
                  ? "Spend " + ask.price.toLocaleString() + " credits on this training."
                  : "Spend credits on this training — the amount could not be quoted."}</span>
              </label>
            )}
            <div className="glm-sheet-actions">
              <button type="button" className="glm-metal glm-widebtn" onClick={closeSheet} disabled={busy}>Back</button>
              <button type="button" className="glm-primary glm-widebtn" disabled={busy || (!ask.is_free && !acceptCost)} onClick={confirm}>
                {busy ? "submitting…" : "Start training"}
              </button>
            </div>
          </>
        )}
      </MobileSheet>
    </div>
  );
}
