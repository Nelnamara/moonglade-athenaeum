import React, { useEffect, useRef, useState } from "react";
import TrainPool from "./TrainPool.jsx";
import { holdTrainEscape, useAdvancedTraining } from "./useTraining.js";
import {
  ADVANCED_DEFAULTS, CAPTION_FILTERS, CAPTION_MAX, GOALS, LR_RANGE, MAX_IMAGES, MIN_IMAGES, RANKS,
  STEP_RANGE, addTag, advancedTriggerLine, captionCounts, captionFilter, captionState, credits,
  describeLabel, etaForSteps, etaText, sentence, focusWindow, perImage, removeTag, replaceIn, stepFocus,
  trackPercent,
} from "../../gen/trainCore.js";

/* Advanced training, desktop (Training Handoff C / decision 3c), with the owner's 2026-09-28
   corrections (BUILD-w3-train.md section 5), which win over the page for FLOW; the page still
   governs the LOOK:

   1 SET UP -- name, trigger words (at least 30 and up to 256 once tidied; the peach line under
      the box), the goal, and the base: Tsubaki.3 (Recommended) or Tsubaki.2, fixed once the
      draft exists. "Next · creates a draft" is the one press that creates it on PixAI (free),
      and it disables on the press.
   2 DESCRIPTIONS -- the images are added HERE (Upload / From history, N of 100, at least 10).
      PixAI describes them first: "Describe automatically (N images)" with PixAI's own quote for
      this set is the ONLY way in (there is no writing them yourself before it), asked once --
      the button names the amount it sends. Then the grid (auto-fill 120 px, the filters All ·
      Auto · Edited · Not described yet, find / replace / + tag / − tag, restore automatic on
      the selected) and the focus view (the image and its whole description, out of 1,000,
      restore automatic, the strip, ← → J K, Esc back to the grid). Edits save one at a time
      after a pause; Describe, Next and Start wait for them. "Next: parameters" stays off until
      every image is described.
   3 PARAMETERS → START -- drawn as the handoff draws them, every control LOCKED at PixAI's
      defaults (its own page locks them and its quote takes no length: spend review finding 3),
      the live quote, the ETA by PixAI's formula, and Start with the price on the button.

   `draftId` (Runs' Continue) opens that draft at its descriptions; nothing is written on open. */

const STEPS = ["Set up", "Descriptions", "Parameters → start"];
const PHASE_N = { setup: 1, descriptions: 2, parameters: 3 };

export default function TrainAdvanced({ setup, csrf, draftId, onBack, onBasic, onRuns, onStarted }) {
  const a = useAdvancedTraining(setup, csrf, draftId);
  const n = PHASE_N[a.phase] || 1;
  const go = (k) => {
    if (k === 3 && a.phase === "descriptions") { a.toParameters(); return; }
    if (k === 2 && a.draftId && a.phase === "parameters") a.setPhase("descriptions");
  };
  const title = a.detail ? a.detail.task.title : a.name;
  const baseName = a.detail ? a.detail.task.base_name : "";

  useEffect(() => { if (a.started && onStarted) onStarted(a.started); }, [a.started]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="mgtr-wiz">
      <div className="mgtr-wizhead">
        <button type="button" className="mgtr-back" onClick={onBack}>‹ Back</button>
        <span className="mgtr-badge">Advanced training</span>
        <ol className="mgtr-stepper">
          {STEPS.map((s, i) => (
            <li key={s} className={n === i + 1 ? "on" : n > i + 1 ? "done" : ""}>
              <button type="button" onClick={() => go(i + 1)}
                disabled={i === 0 ? n !== 1 : false}>{i + 1} {s}</button>
            </li>
          ))}
        </ol>
      </div>
      {a.phase === "setup" && <SetUp a={a} onBasic={onBasic} />}
      {a.phase === "descriptions" && <Descriptions a={a} title={title} baseName={baseName} onBasic={onBasic} />}
      {a.phase === "parameters" && <Parameters a={a} title={title} baseName={baseName} onRuns={onRuns} />}
    </div>
  );
}

/* --------------------------------------------------------------------------- 1 · Set up */
function SetUp({ a, onBasic }) {
  const line = advancedTriggerLine(a.trigger);
  const ready = !!a.name.trim() && !line.block && !!a.base && !!a.goal;
  return (
    <div className="mgtr-card mgtr-adv-setup">
      <div className="mgtr-kick">1 · SET UP</div>
      <label className="mgtr-lab" htmlFor="mgtr-adv-name">Name · Trigger words</label>
      <input id="mgtr-adv-name" className="mgtr-in" value={a.name} placeholder="Name your LoRA"
        onChange={(e) => a.setName(e.target.value)} disabled={!!a.draftId} />
      <input id="mgtr-adv-trig" className={"mgtr-in mono" + (line.warn ? " warn" : "")} value={a.trigger}
        placeholder="trigger words, at least 30 characters" aria-label="Trigger words"
        onChange={(e) => a.setTrigger(e.target.value)} disabled={!!a.draftId} />
      <div className={"mgtr-hint" + (line.warn ? " warn" : "")}>{line.text}</div>
      <div className="mgtr-lab">Category · Base</div>
      <div className="mgtr-tabs" role="radiogroup" aria-label="Category">
        {GOALS.map((g) => (
          <button type="button" key={g.value} role="radio" aria-checked={a.goal === g.value}
            className={"mgtr-tab" + (a.goal === g.value ? " on" : "")} disabled={!!a.draftId}
            onClick={() => a.setGoal(g.value)}>{g.label}</button>
        ))}
      </div>
      <div className="mgtr-advbases" role="radiogroup" aria-label="Base">
        {a.bases.map((b) => (
          <button type="button" key={b.version_id} role="radio" aria-checked={a.base === b.version_id}
            className={"mgtr-advbase" + (a.base === b.version_id ? " on" : "")} disabled={!!a.draftId}
            onClick={() => a.setBase(b.version_id)}>
            {b.title}{b.recommended ? " · Recommended" : ""}
          </button>
        ))}
        {!a.bases.length && <span className="mgtr-dim">Reading PixAI's bases…</span>}
      </div>
      <div className="mgtr-note">The base can't be changed once you continue. "Next · creates a draft" creates the draft on PixAI (free); the button says so.</div>
      {a.err && <div className="mgtr-err">⚠ {a.err}</div>}
      <div className="mgtr-row-end">
        <button type="button" className="mgtr-across" onClick={onBasic}>Use Basic instead</button>
        <button type="button" className="mgtr-go" disabled={!ready || !!a.busy} onClick={a.createDraft}>
          {a.busy === "draft" ? "creating the draft…" : "Next · creates a draft"}</button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- 2 · Descriptions */
function Descriptions({ a, title, baseName, onBasic }) {
  const [src, setSrc] = useState("");
  const [focus, setFocus] = useState(false);
  const [fi, setFi] = useState(0);
  const [filter, setFilter] = useState("all");
  const [sel, setSel] = useState(() => new Set());
  const [find, setFind] = useState("");
  const [repl, setRepl] = useState("");
  const [done, setDone] = useState("");
  const fileRef = useRef(null);
  const ids = a.mediaIds;
  const counts = captionCounts(ids, a.captions);
  const shown = captionFilter(ids, a.captions, filter);
  const q = a.quote;
  const per = perImage(q);
  const g = a.gates;
  const editable = a.status === "captionReady";
  const canChangeSet = (a.status === "draft" || a.status === "captionReady") && !a.busy;
  const have = new Set(ids);
  const undescribed = g.left;
  const target = (list) => {
    const described = list.filter((m) => typeof a.textOf(m) === "string");
    const picked = described.filter((m) => sel.has(m));
    return picked.length ? picked : described;
  };
  const tool = (fn, verb) => {
    const k = a.applyAll(target(shown), fn);
    setDone(k ? verb + " " + k + " description" + (k === 1 ? "" : "s") + "." : "Nothing to change.");
  };
  const selEdited = [...sel].filter((m) => captionState(m, a.captions) === "edited" || a.edits[m] !== undefined);
  const openFocus = (mid) => { setFi(Math.max(0, ids.indexOf(mid))); setFocus(true); };

  return (
    <div className="mgtr-card mgtr-adv-desc">
      <div className="mgtr-adv-deshead">
        <div className="mgtr-kick">2 · DESCRIPTIONS · {ids.length} IMAGE{ids.length === 1 ? "" : "S"}</div>
        {ids.length > 0 && (
          <button type="button" className="mgtr-linkbtn" onClick={() => setFocus(!focus)}>
            {focus ? "▦ Grid (Esc)" : "⤢ Focus"}</button>
        )}
      </div>
      <div className="mgtr-dim">{title}{baseName ? " · " + baseName : ""}</div>

      <div className="mgtr-sources">
        <button type="button" className="mgtr-src" disabled={!canChangeSet || ids.length >= MAX_IMAGES}
          onClick={() => fileRef.current && fileRef.current.click()}>⬆ Upload</button>
        <button type="button" className={"mgtr-src" + (src === "history" ? " on" : "")} disabled={!canChangeSet}
          onClick={() => setSrc(src === "history" ? "" : "history")}>▦ From history</button>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden
          onChange={(e) => { const fl = e.target.files; e.target.value = ""; a.upload(fl); }} />
      </div>
      {src === "history" && (
        <TrainPool have={have} room={Math.max(0, MAX_IMAGES - ids.length)}
          onAdd={(tray) => a.addImages(tray)} onClose={() => setSrc("")} />
      )}
      <div className="mgtr-count">
        <div className="mgtr-countbar"><div className={a.enough ? "ok" : "low"}
          style={{ width: Math.min(100, ids.length) + "%" }} /></div>
        <div className={"mgtr-mono " + (a.enough ? "ok" : "low")}>{ids.length} / {MAX_IMAGES}</div>
      </div>
      {!a.enough && <div className="mgtr-note">At least {MIN_IMAGES}. PNG, JPG or WebP, at least 512×512, no wider than 3:1. Adding or taking out images changes the draft on PixAI (free).</div>}

      {a.status === "captioning" ? (
        <div className="mgtr-capwait" role="status">PixAI is describing the images now. This checks again every few seconds; you can close it and come back from Runs.</div>
      ) : undescribed > 0 && a.enough ? (
        <div className="mgtr-capask">
          <div className="mgtr-capask-head">
            <div className="t">Describe {q && q.image_count > 0 ? q.image_count : undescribed} image{(q && q.image_count === 1) ? "" : "s"} automatically?</div>
            <div className="p">{q && typeof q.total_price === "number" ? credits(q.total_price) : "—"}</div>
          </div>
          <div className="b">
            {per != null ? credits(per) + " credits per image, PixAI's quote for this set, " : ""}charged when it runs, on PixAI. PixAI describes first; you can rewrite every description afterwards.
          </div>
          <div className="a">
            {!g.describe && <span className="mgtr-dim">{g.whyNoDescribe}</span>}
            <button type="button" className="mgtr-go" disabled={!g.describe} onClick={a.describe}>
              {a.busy === "describe" ? "sending…" : describeLabel(q)}</button>
          </div>
        </div>
      ) : null}

      {ids.length > 0 && !focus && (
        <>
          <div className="mgtr-runs-filters" role="tablist" aria-label="Show">
            {CAPTION_FILTERS.map((f) => (
              <button type="button" key={f.key} role="tab" aria-selected={filter === f.key}
                className={"mgtr-chip" + (filter === f.key ? " on" : "")} onClick={() => setFilter(f.key)}>
                {f.label} {counts[f.key]}
              </button>
            ))}
          </div>
          {editable && (
            <div className="mgtr-adv-tools">
              <input className="mgtr-in sm" value={find} placeholder="⌕ find, or a tag" aria-label="Find, or a tag"
                onChange={(e) => { setFind(e.target.value); setDone(""); }} />
              <input className="mgtr-in sm" value={repl} placeholder="replace with…" aria-label="Replace with"
                onChange={(e) => { setRepl(e.target.value); setDone(""); }} />
              <button type="button" className="mgtr-tool" disabled={!find}
                onClick={() => tool((t) => replaceIn(t, find, repl), "Changed")}>Replace</button>
              <button type="button" className="mgtr-tool" disabled={!find.trim()}
                onClick={() => tool((t) => addTag(t, find), "Tagged")}>+ tag to {sel.size ? "selected" : "all"}</button>
              <button type="button" className="mgtr-tool" disabled={!find.trim()}
                onClick={() => tool((t) => removeTag(t, find), "Untagged")}>− tag from {sel.size ? "selected" : "all"}</button>
            </div>
          )}
          <div className="mgtr-dgrid">
            {shown.map((mid) => {
              const text = a.textOf(mid);
              const st = captionState(mid, a.captions);
              const dirty = a.edits[mid] !== undefined;
              const on = sel.has(mid);
              return (
                <div key={mid} className={"mgtr-dtile" + (on ? " sel" : "") + (a.rejected.includes(mid) ? " reject" : "")}>
                  <button type="button" className="mgtr-dtile-img" onClick={() => openFocus(mid)}
                    aria-label="Open in focus">
                    <img src={"/api/train/thumb/" + mid} alt="" />
                    {(st === "edited" || dirty) && <span className="mgtr-dtile-dot" title="Edited" />}
                    <span className="mgtr-dtile-open">⤢</span>
                  </button>
                  {typeof text === "string" && (
                    <button type="button" className={"mgtr-dtile-sel" + (on ? " on" : "")} role="checkbox"
                      aria-checked={on} aria-label="Select"
                      onClick={() => setSel((cur) => { const s = new Set(cur); if (s.has(mid)) s.delete(mid); else s.add(mid); return s; })}>
                      {on ? "✓" : ""}</button>
                  )}
                  {canChangeSet && (
                    <button type="button" className="mgtr-gx" onClick={() => a.removeImage(mid)}
                      aria-label="Take it out" title="Take it out of the set">×</button>
                  )}
                  <div className={"mgtr-dtile-text" + (typeof text === "string" ? "" : " none")}>
                    {typeof text === "string" ? text : text === null ? "couldn't be read" : "Not described yet"}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mgtr-adv-gridfoot">
            <div className="s">{counts.edited} edited · {counts.auto} automatic{counts.none ? " · " + counts.none + " not described yet" : ""} · click a tile or ⤢ for focus{done ? " · " + done : ""}</div>
            <button type="button" className="mgtr-linkbtn" disabled={!editable || !selEdited.length}
              onClick={() => { const k = a.restoreAutomatic(selEdited); setDone(k ? "Restored " + k + "." : ""); }}>
              Restore automatic (selected)</button>
          </div>
        </>
      )}

      {ids.length > 0 && focus && (
        <FocusView a={a} ids={ids} fi={fi} setFi={setFi} onGrid={() => setFocus(false)} editable={editable} />
      )}

      {a.saving > 0 && <div className="mgtr-dim" role="status">Saving {a.saving} edit{a.saving === 1 ? "" : "s"}…</div>}
      {a.err && <div className="mgtr-err">⚠ {a.err}</div>}
      <div className="mgtr-row-end">
        <button type="button" className="mgtr-across" onClick={onBasic}>Use Basic instead</button>
        <span className="mgtr-row-go">
          {!g.next && ids.length > 0 && <span className="mgtr-dim">{g.whyNoNext}</span>}
          <button type="button" className="mgtr-go" disabled={!g.next} onClick={a.toParameters}>
            {a.busy === "quote" ? "asking PixAI's price…" : "Next: parameters"}</button>
        </span>
      </div>
    </div>
  );
}

/* The focus view (3c): the image and its whole description, out of 1,000; restore automatic;
   the strip; ← → J K move (not while typing), Esc returns to the grid. Leaving an image saves
   its edit. */
function FocusView({ a, ids, fi, setFi, onGrid, editable }) {
  const i = Math.min(fi, ids.length - 1);
  const mid = ids[i];
  const text = a.textOf(mid);
  const c = a.captions[mid];
  const len = typeof text === "string" ? text.length : 0;
  const move = (d) => { a.saveOne(mid); setFi(stepFocus(i, ids.length, d)); };
  const moveRef = useRef(move);
  moveRef.current = move;
  const gridRef = useRef(onGrid);
  gridRef.current = () => { a.saveOne(mid); onGrid(); };
  useEffect(() => {
    const release = holdTrainEscape();
    const onKey = (e) => {
      const typing = e.target && /^(TEXTAREA|INPUT)$/.test(e.target.tagName || "");
      if (e.key === "Escape") { e.preventDefault(); if (typing) e.target.blur(); gridRef.current(); return; }
      if (typing) return;
      if (e.key === "ArrowLeft" || e.key === "k" || e.key === "K") { e.preventDefault(); moveRef.current(-1); }
      else if (e.key === "ArrowRight" || e.key === "j" || e.key === "J") { e.preventDefault(); moveRef.current(1); }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); release(); };
  }, []);
  const canRestore = editable && c && typeof c.machine_text === "string" && c.machine_text && text !== c.machine_text;
  return (
    <div className="mgtr-focus">
      <div className="mgtr-focus-main">
        <img className="mgtr-focus-img" src={"/api/train/thumb/" + mid} alt="" />
        <div className="mgtr-focus-side">
          {typeof text === "string" ? (
            <textarea className="mgtr-focus-text" value={text} maxLength={CAPTION_MAX} disabled={!editable}
              aria-label="Description" onChange={(e) => a.editCaption(mid, e.target.value)}
              onBlur={() => a.saveOne(mid)} />
          ) : (
            <div className="mgtr-focus-text none">
              {text === null ? "This description couldn't be read just now." : "Not described yet. PixAI describes it first; then you can rewrite it."}
            </div>
          )}
          <div className="mgtr-focus-meta">
            <span>{i + 1} / {ids.length} · {credits(len)} / {credits(CAPTION_MAX)}{typeof text === "string" && !text.trim() ? " · a description can't be empty" : ""}</span>
            <button type="button" className="mgtr-linkbtn" disabled={!canRestore}
              onClick={() => a.restoreAutomatic([mid])}>Restore automatic</button>
          </div>
        </div>
      </div>
      <div className="mgtr-focus-strip">
        <button type="button" className="mgtr-focus-arrow" onClick={() => move(-1)} disabled={i === 0} aria-label="Previous">←</button>
        <div className="mgtr-focus-thumbs">
          {focusWindow(i, ids.length, 10).map((k) => (
            <button type="button" key={ids[k]} className={"mgtr-focus-thumb" + (k === i ? " on" : "")}
              onClick={() => { a.saveOne(mid); setFi(k); }} aria-label={"Image " + (k + 1)}>
              <img src={"/api/train/thumb/" + ids[k]} alt="" /></button>
          ))}
        </div>
        <button type="button" className="mgtr-focus-arrow" onClick={() => move(1)} disabled={i >= ids.length - 1} aria-label="Next">→</button>
      </div>
      <div className="mgtr-note">← → or J / K move between images · Esc returns to the grid · edits save as you type (one save per pause)</div>
    </div>
  );
}

/* ----------------------------------------------------------------- 3 · Parameters → start */
function Parameters({ a, title, baseName, onRuns }) {
  const ask = a.startAsk;
  const eta = (ask && ask.eta) || etaForSteps(ADVANCED_DEFAULTS.steps);
  const rows = [
    { name: "Length (steps)", val: String(ADVANCED_DEFAULTS.steps), fill: trackPercent(ADVANCED_DEFAULTS.steps, STEP_RANGE),
      note: STEP_RANGE.min + "–" + STEP_RANGE.max + " · locked by PixAI for now" },
    { name: "Learning rate", val: "6e-4 · default", fill: trackPercent(ADVANCED_DEFAULTS.learningRate, LR_RANGE),
      note: "Locked by PixAI for now; unlocks when the API allows it" },
    { name: "Detail capacity (rank)", val: ADVANCED_DEFAULTS.rank + " · default", fill: null, note: "Locked by PixAI for now" },
  ];
  return (
    <div className="mgtr-card mgtr-adv-params">
      <div className="mgtr-kick">3 · PARAMETERS → START</div>
      <div className="mgtr-dim">{title}{baseName ? " · " + baseName : ""}{ask ? " · " + ask.image_count + " images, all described" : ""}</div>
      {rows.map((r) => (
        <div key={r.name} className="mgtr-param locked" aria-disabled="true">
          <div className="mgtr-param-head"><span className="n">{r.name}</span><span className="v">{r.val}</span></div>
          {r.fill !== null && <div className="mgtr-param-track"><div style={{ width: r.fill + "%" }} /></div>}
          <div className="mgtr-param-note">{r.note}</div>
        </div>
      ))}
      <div className="mgtr-ranks" aria-disabled="true">
        {RANKS.map((r) => <span key={r} className={"mgtr-rank" + (r === ADVANCED_DEFAULTS.rank ? " on" : "")}>{r}</span>)}
      </div>
      <div className="mgtr-note">PixAI's own page sends these defaults today (325 steps, learning rate 6e-4, rank 64, gradient accumulation 2), and so does this app.</div>
      <div className="mgtr-quote">
        <div className="mgtr-quote-head"><span className="n">Quote</span>
          <span className="p">{ask ? (ask.is_free ? "free" : credits(ask.price)) : "—"}</span></div>
        <div className="mgtr-note">PixAI's price for this run today, by its base. Free to ask; nothing is spent until Start. Describing was charged when it ran. {sentence(etaText(eta))}</div>
      </div>
      {a.started ? (
        <div className="mgtr-ok">
          ✓ Training started{a.started.used_free_training ? " — it used one of your free trainings" : ""}. It shows in Runs.
          {onRuns && <button type="button" className="mgtr-linkbtn" onClick={onRuns}>See it in Runs ›</button>}
        </div>
      ) : (
        <div className="mgtr-row-end">
          <button type="button" className="mgtr-across" disabled={!!a.busy} onClick={() => a.setPhase("descriptions")}>‹ Back to descriptions</button>
          <button type="button" className="mgtr-go big" disabled={!ask || !!a.busy || a.saving > 0} onClick={a.start}>
            {a.busy === "start" ? "starting…" : !ask ? "Start training" : ask.is_free ? "Start training · free" : "Start training · " + credits(ask.price)}</button>
        </div>
      )}
      {!ask && !a.busy && !a.started && (
        <button type="button" className="mgtr-linkbtn left" onClick={a.refreshQuote}>Ask PixAI's price again</button>
      )}
      {a.err && <div className="mgtr-err">⚠ {a.err}</div>}
      {a.maybe && (
        <div className="mgtr-warnnote">
          PixAI didn't answer clearly, so this run may have started; check Runs before starting again.
          {onRuns && <button type="button" className="mgtr-linkbtn" onClick={onRuns}>Check Runs ›</button>}
        </div>
      )}
    </div>
  );
}
