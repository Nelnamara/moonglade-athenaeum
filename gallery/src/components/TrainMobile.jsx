import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import useSheet from "../hooks/useSheet.js";
import MobileSheet from "./MobileSheet.jsx";
import { scrollParentOf } from "../picker/mergeRows.js";
import { GAUGE_SIZES } from "../lib/moonGaugeCore.js";
import TrainStrip from "./train/TrainStrip.jsx";
import RunsList, { RetryConfirm } from "./train/RunsList.jsx";
import PublishSheet from "./train/PublishSheet.jsx";
import DatasetImport from "./train/DatasetImport.jsx";
import {
  useAdvancedTraining, useBasicTraining, useCsrf, useHistoryPool, usePublish, useRetry,
  useTrainRuns, useTrainSetup,
} from "./train/useTraining.js";
import {
  ADVANCED_DEFAULTS, CAPTION_FILTERS, CAPTION_MAX, GOALS, LR_RANGE, MAX_IMAGES, MIN_IMAGES, RANKS,
  STEP_RANGE, addTag, advancedTriggerLine, captionCounts, captionFilter, captionState, credits,
  describeLabel, etaForSteps, etaText, sentence, loraForDock, perImage, removeTag, replaceIn, roomLeft,
  runsSummary, startLabel, stepFocus, trackPercent,
} from "../gen/trainCore.js";
import "../styles/train.css";
import "../styles/train-mobile.css";

/* Train a LoRA -- the phone (Training Handoff F, Session J, committed 2026-09-28; the flows of
   decisions 1a · 2a · 3c · 4a · 5c · 6a with the owner's 2026-09-28 corrections in
   BUILD-w3-train.md section 5). It replaces the one-page screen of 2026-08-07.

   The same flows as the desktop overlay, ONE STEP PER SCREEN, on the shipped pushed screen
   (`screen: 'train'`, "Train a LoRA": MobileScreen's ‹ + Georgia 15 px head over its rule, body
   padding 13 px), reached as before from the header menu sheet and My Art → LoRAs. The step
   ("2 / 3", "14 / 38") and the screen's own tools sit at the right of that head, as the page
   draws them; the head's ‹ steps back one screen (AppMobile asks `backRef` first) and closes
   the screen from the chooser.

     chooser (the strip on top) → Basic: goal → add images → review (Start keeps the shipped
       "QUEUE TRAINING RUN" confirm sheet)
                                → Advanced: set up → add images → descriptions (image over
       text, swipe; ▦ the 2-column grid; find / replace in ⋯) → parameters (Start through the
       same confirm sheet)
                                → Runs (the strip, filters, rows, one action each; Publish and
       Retry open as bottom sheets)

   Every image source opens in ONE bottom sheet (Upload · From history · Import a dataset); the
   set is a 3-column grid, and a long press takes a picture out. The pinned action row at the
   foot of each screen is the page's 44 px CTA over a 1 px rule.

   THE STATE AND THE CALLS are the desktop's own (components/train/useTraining.js): the same
   quotes, the same one confirm per paid press naming the quoted number, the same server
   re-checks. NOTHING WRITES ON OPEN: opening the screen reads the config, the free trainings
   and the runs; every write is a press. The sheets are portalled to .glm-stage (the wave-1
   rule: never a fixed layer inside the scrolling body) on their own rung above the screen. */

const GOAL_TINT = ["lavender", "mauve", "emerald", "peach"];

function useHost(selector) {
  const [host, setHost] = useState(null);
  useEffect(() => { setHost(document.querySelector(selector) || document.body); }, [selector]);
  return host;
}

export default function TrainMobile({ onClose, onUseLora, backRef }) {
  const csrf = useCsrf();
  const setup = useTrainSetup();
  const [route, setRoute] = useState("chooser");     // chooser | basic | advanced | runs
  const [pick, setPick] = useState("basic");
  const [draftId, setDraftId] = useState("");
  const [advRun, setAdvRun] = useState(0);
  const [filter, setFilter] = useState("all");
  const runs = useTrainRuns({ enabled: route === "chooser" || route === "runs" });
  const retry = useRetry(csrf, () => runs.refresh());
  const pub = usePublish(csrf, () => runs.refresh());
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  const stepBack = useRef(null);                      // a flow's own one-step back, or null
  const root = useRef(null);
  const [head, setHead] = useState(null);
  const host = useHost(".glm-stage");
  useEffect(() => {
    const scr = root.current && root.current.closest(".glm-screen");
    setHead(scr ? scr.querySelector(".glm-screen-head") : null);
  }, []);

  // The head's ‹: one step back inside a flow, then the chooser, then out of the screen.
  useEffect(() => {
    if (!backRef) return undefined;
    backRef.current = () => {
      if (stepBack.current && stepBack.current()) return true;
      if (route !== "chooser") { setRoute("chooser"); return true; }
      return false;
    };
    return () => { backRef.current = null; };
  });

  // A publish or retry that lands (or is cancelled) takes its sheet down with it.
  useEffect(() => { if (pub.target) openSheet("publish"); else if (sheet === "publish") closeSheet(); }, [pub.target]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (retry.ask) openSheet("retry"); else if (sheet === "retry") closeSheet(); }, [retry.ask]);   // eslint-disable-line react-hooks/exhaustive-deps

  const newAdvanced = () => { setDraftId(""); setAdvRun((n) => n + 1); setRoute("advanced"); };
  const onAction = (kind, row) => {
    if (kind === "continue") { setDraftId(row.id); setRoute("advanced"); }
    else if (kind === "publish") pub.open("publish", row);
    else if (kind === "make-public") pub.open("make-public", row);
    else if (kind === "retry") retry.preview(row);
    else if (kind === "use") {
      const lora = loraForDock(row, setup.archOf);
      if (lora && onUseLora) onUseLora(lora);
    }
  };

  let aside = null;
  let body = null;
  if (route === "chooser") {
    const summary = runsSummary(runs.runs);
    body = (
      <Screen cta={<button type="button" className="trm-cta-btn"
        onClick={() => (pick === "advanced" ? newAdvanced() : setRoute("basic"))}>Continue</button>}>
        <TrainStrip running={runs.running} size={GAUGE_SIZES.phone} className="trm-strip"
          onView={() => setRoute("runs")} />
        {setup.paused && <div className="trm-warn">PixAI has paused new training runs{setup.resumesAt ? " until about " + setup.resumesAt : ""}. Runs already training carry on.</div>}
        <button type="button" className={"trm-row" + (pick === "basic" ? " sel" : "")} aria-pressed={pick === "basic"}
          onClick={() => setPick("basic")}>
          <span className="trm-row-main"><b>Basic training</b> · about 30 min</span>
        </button>
        <button type="button" className={"trm-row" + (pick === "advanced" ? " sel" : "")} aria-pressed={pick === "advanced"}
          onClick={() => setPick("advanced")}>
          <span className="trm-row-main"><b>Advanced training</b> · 1–2 h</span>
        </button>
        <button type="button" className="trm-row" onClick={() => setRoute("runs")}>
          <span className="trm-row-main"><b>Runs</b>{summary ? " · " + summary : ""}</span>
          <span className="trm-row-go" aria-hidden="true">›</span>
        </button>
      </Screen>
    );
  } else if (route === "runs") {
    aside = <button type="button" className="trm-headbtn" onClick={() => setRoute("chooser")}>+ New</button>;
    body = (
      <Screen>
        <TrainStrip running={runs.running} size={GAUGE_SIZES.phone} className="trm-strip" />
        {retry.err && !retry.ask && <div className="trm-err">⚠ {retry.err}</div>}
        {runs.errors && runs.errors.length > 0 && (
          <div className="trm-warn">Some runs couldn't be read just now: {runs.errors.join(" · ")}</div>
        )}
        {!runs.loaded ? <div className="trm-txt">Reading your runs…</div>
          : <RunsList runs={runs.runs} filter={filter} setFilter={setFilter} onAction={onAction} phone />}
      </Screen>
    );
  }

  const sheets = (
    <>
      <MobileSheet open={sheet === "publish"} closing={closing} className="trm-sheet"
        onClose={() => { if (!pub.busy) pub.close(); }}>
        <PublishSheet pub={pub} body />
      </MobileSheet>
      <MobileSheet open={sheet === "retry"} closing={closing} className="trm-sheet"
        onClose={() => { if (!retry.busy) retry.setAsk(null); }} title="RETRY A RUN">
        <RetryConfirm retry={retry} />
      </MobileSheet>
    </>
  );

  return (
    <div className="trm-wrap" ref={root}>
      {route === "basic" && (
        <BasicPhone setup={setup} csrf={csrf} stepBack={stepBack} onChooser={() => setRoute("chooser")}
          onAdvanced={newAdvanced} onRuns={() => setRoute("runs")} head={head} host={host} />
      )}
      {route === "advanced" && (
        <AdvancedPhone key={draftId || "new-" + advRun} setup={setup} csrf={csrf} draftId={draftId}
          stepBack={stepBack} onBasic={() => setRoute("basic")} onRuns={() => { setRoute("runs"); runs.refresh(); }}
          head={head} host={host} />
      )}
      {body}
      {head && aside && createPortal(<div className="trm-headaside">{aside}</div>, head)}
      {host && createPortal(sheets, host)}
    </div>
  );
}

/* One step's screen: the body, then the pinned 44 px action row (the page's CTA over a rule). */
function Screen({ children, cta }) {
  return (
    <div className="trm-screen">
      <div className="trm-fill">{children}</div>
      {cta && <div className="trm-cta">{cta}</div>}
    </div>
  );
}

/* The step and a screen's own tools at the right of the pushed screen's head. */
function HeadAside({ head, children }) {
  if (!head) return null;
  return createPortal(<div className="trm-headaside">{children}</div>, head);
}

/* ---------------------------------------------------------------------------------- Basic */
function BasicPhone({ setup, csrf, stepBack, onChooser, onAdvanced, onRuns, head, host }) {
  const b = useBasicTraining(setup, csrf);
  const [step, setStep] = useState(1);
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  const fileRef = useRef(null);
  stepBack.current = () => {
    if (step > 1) { setStep(step - 1); return true; }
    onChooser();
    return true;
  };
  useEffect(() => () => { stepBack.current = null; }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  // the confirm opens on the quote and closes when the run starts (or the quote is dropped)
  useEffect(() => { if (b.ask) openSheet("confirm"); else if (sheet === "confirm") closeSheet(); }, [b.ask]);   // eslint-disable-line react-hooks/exhaustive-deps

  const goalLabel = (GOALS.find((g) => g.value === b.goal) || {}).label || "";
  const tab = b.tab !== null ? b.tabs[b.tab] : null;
  const f = b.footer;
  const have = new Set(b.items.map((x) => x.media_id));
  let cta = null;
  let content = null;
  if (step === 1) {
    content = (
      <>
        <div className="trm-h">What do you want to train?</div>
        {GOALS.map((g, i) => (
          <button type="button" key={g.value} className={"trm-row goal" + (b.goal === g.value ? " sel" : "")}
            aria-pressed={b.goal === g.value} onClick={() => b.setGoal(g.value)}>
            <span className={"mgtr-goal-tint " + GOAL_TINT[i]} />
            <span className="trm-row-text"><span className="trm-row-main"><b>{g.label}</b></span>
              <span className="trm-row-sub">{g.desc}</span></span>
          </button>
        ))}
        <button type="button" className="trm-across" onClick={onAdvanced}>Need to edit descriptions or parameters? Use Advanced</button>
      </>
    );
    cta = <button type="button" className="trm-cta-btn" disabled={!b.goal} onClick={() => setStep(2)}>Continue</button>;
  } else if (step === 2) {
    content = (
      <>
        <div className="trm-lab">DATASET IMAGES <span className={b.enough ? "ok" : "low"}>{b.counted.length} / {MAX_IMAGES}</span></div>
        <button type="button" className="trm-row" onClick={() => openSheet("sources")}>
          <span className="trm-row-main">⬆ Upload · ▦ From history · ⎘ Import a dataset</span>
        </button>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden
          onChange={(e) => { const fl = e.target.files; e.target.value = ""; b.upload(fl); }} />
        <PhoneGrid items={b.items.map((it) => ({ id: it.media_id, thumb: it.thumb || "/api/train/thumb/" + it.media_id, reject: it.reject }))}
          onRemove={b.removeImage} />
        {b.rejects.length > 0 && (
          <div className="trm-txt low">{b.rejects.length} left out: {b.rejects.map((r) => r.name + " (" + r.reason + ")").join(" · ")}</div>
        )}
        {b.items.some((x) => x.reject) && <div className="trm-txt low">{b.items.filter((x) => x.reject).length} rejected: shown in peach and not counted.</div>}
        <div className="trm-txt">PNG, JPG or WebP, at least 512×512, no wider than 3:1. At least {MIN_IMAGES}. Long-press a picture to take it out.</div>
      </>
    );
    cta = <button type="button" className="trm-cta-btn" disabled={!b.enough} onClick={() => setStep(3)}>
      {b.enough ? "Continue to review" : "Add " + (MIN_IMAGES - b.counted.length) + " more"}</button>;
  } else {
    content = b.done ? (
      <div className="trm-done">
        ✓ Training started{b.done.used_card ? " — it used your training free card"
          : b.done.was_free ? " — it used one of your free trainings" : ""}. It shows in Runs.
        <button type="button" className="trm-across" onClick={onRuns}>See it in Runs ›</button>
      </div>
    ) : (
      <>
        <div className="pubm-lab">LoRA name</div>
        <input className="pubm-in" value={b.name} placeholder="Name your LoRA" onChange={(e) => b.setName(e.target.value)} />
        <div className="pubm-lab">Trigger words</div>
        <textarea className={"pubm-in" + (b.trigger && !b.trig.ok ? " warn" : "")} rows={2} value={b.trigger}
          placeholder="e.g. kaia" onChange={(e) => b.setTrigger(e.target.value)} />
        <div className={"trm-txt" + (b.trigger && !b.trig.ok ? " low" : "")}>
          {b.trigger && !b.trig.ok ? b.trig.length + " / 256: " + b.trig.problem + "."
            : "Short, unusual words work best. Add it to a prompt to use the LoRA."}
        </div>
        <div className="pubm-lab">Base model</div>
        <div className="trm-typerow">
          {b.tabs.map((t, i) => (
            <button type="button" key={t.arch} className={"trm-typechip" + (b.tab === i ? " on" : "")}
              onClick={() => b.pickTab(i)}>{t.label}{t.recommended ? " · Recommended" : ""}</button>
          ))}
        </div>
        <div className="trm-themerow">
          {(tab ? tab.models : []).map((m) => (
            <button type="button" key={m.version_id} className={"trm-themechip" + (b.base === m.version_id ? " on" : "")}
              onClick={() => b.setBase(m.version_id)}>{m.title}</button>
          ))}
        </div>
        <div className="trm-txt">Your LoRA only works with this model. It's selected automatically when you use the LoRA.</div>
        <div className="trm-sum">
          <div className="trm-txt">✓ {goalLabel || "—"} · ✓ {b.counted.length} images · ✓ {b.baseName || "—"} · Standard settings{f.reason ? " · " + f.reason : ""}</div>
          <div className="trm-price">
            {f.free && f.struck != null && <span className="struck">{credits(f.struck)}</span>}
            <span className="gold">🪙 {f.price != null ? credits(f.price) : "?"}</span>
            {f.badge && <span className="freebadge">{f.badge}</span>}
            <span className="eta">{etaText(setup.cfg && setup.cfg.eta)}</span>
          </div>
        </div>
        {!b.ask && b.err && !b.maybe && <div className="trm-err">⚠ {b.err}</div>}
        {b.maybe && <div className="trm-warn">PixAI didn't answer clearly, so this run may have started; check Runs before starting again.</div>}
        {setup.paused && <div className="trm-warn">PixAI has paused new training runs; Start waits until it opens again.</div>}
      </>
    );
    cta = b.done ? null : (
      <button type="button" className="trm-cta-btn" disabled={!b.ready || b.busy} onClick={b.preview}>
        {b.busy && !b.ask ? "checking…" : "Start training"}</button>
    );
  }

  const sheets = (
    <>
      <SourcesSheet open={sheet === "sources"} closing={closing} onClose={closeSheet} withImport
        onUpload={() => { closeSheet(); if (fileRef.current) fileRef.current.click(); }}
        onHistory={() => openSheet("history")} onImport={() => { b.loadDatasets(); openSheet("import"); }} />
      <MobileSheet open={sheet === "history"} closing={closing} onClose={closeSheet} className="trm-sheet" title="FROM HISTORY">
        <PhonePool have={have} room={roomLeft(b.items)} onCancel={closeSheet}
          onAdd={(entries) => { b.addImages(entries, "history"); closeSheet(); }} />
      </MobileSheet>
      <MobileSheet open={sheet === "import"} closing={closing} onClose={closeSheet} className="trm-sheet" title="IMPORT A DATASET">
        <DatasetImport datasets={b.datasets} items={b.items} imported={b.imported} phone
          onImport={(sets) => { b.importSets(sets); if (sets.length === 1) b.takeDetails(sets[0]); }}
          onClose={closeSheet} />
      </MobileSheet>
      <MobileSheet open={sheet === "confirm"} closing={closing} className="trm-sheet"
        onClose={() => { if (!b.busy) b.setAsk(null); }} title="QUEUE TRAINING RUN">
        {b.ask && (
          <>
            <div className="pubm-confirmmeta">
              <b>{b.ask.title || b.name || "Untitled LoRA"}</b> · {b.baseName} · {b.ask.image_count} images · {goalLabel}
              {b.ask.reuse ? " · reusing a dataset" : ""}
            </div>
            <div className="pubm-note" style={{ marginBottom: 12 }}>{b.ask.cost_note}{b.ask.image_note ? " " + b.ask.image_note : ""}</div>
            {!b.ask.is_free && (
              <label className="pubm-toggle" style={{ marginBottom: 12 }}>
                <input type="checkbox" checked={b.accepted} onChange={(e) => b.setAccepted(e.target.checked)} />
                <span>{b.ask.price != null ? "Spend " + credits(b.ask.price) + " credits on this training."
                  : "Spend credits on this training — the amount could not be quoted."}</span>
              </label>
            )}
            {b.err && <div className="trm-err">⚠ {b.err}</div>}
            <div className="glm-sheet-actions">
              <button type="button" className="glm-metal glm-widebtn" onClick={() => b.setAsk(null)} disabled={b.busy}>Back</button>
              <button type="button" className="glm-primary glm-widebtn" disabled={b.busy || (!b.ask.is_free && !b.accepted)}
                onClick={b.confirm}>{b.busy ? "starting…" : startLabel(b.ask)}</button>
            </div>
          </>
        )}
      </MobileSheet>
    </>
  );

  return (
    <>
      <HeadAside head={head}><span className="trm-step">{step} / 3</span></HeadAside>
      <Screen cta={cta}>{content}</Screen>
      {host && createPortal(sheets, host)}
    </>
  );
}

/* ------------------------------------------------------------------------------- Advanced */
function AdvancedPhone({ setup, csrf, draftId, stepBack, onBasic, onRuns, head, host }) {
  const a = useAdvancedTraining(setup, csrf, draftId);
  const [screen, setScreen] = useState(draftId ? "descriptions" : "setup");   // setup | images | descriptions | parameters
  const [mode, setMode] = useState("focus");          // focus | grid
  const [fi, setFi] = useState(0);
  const [filter, setFilter] = useState("all");
  const [find, setFind] = useState("");
  const [repl, setRepl] = useState("");
  const [done, setDone] = useState("");
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet(280);
  const fileRef = useRef(null);
  const touch = useRef(null);
  // a draft opens on its grid while nothing is described yet, one at a time once something is
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !a.detail) return;
    seeded.current = true;
    setMode(a.gates.left === a.mediaIds.length ? "grid" : "focus");
  }, [a.detail]);   // eslint-disable-line react-hooks/exhaustive-deps
  // the hook's own phase follows the draft (created -> descriptions; Next -> parameters)
  useEffect(() => {
    if (a.phase === "descriptions" && screen === "setup") setScreen(draftId ? "descriptions" : "images");
    if (a.phase === "parameters") setScreen("parameters");
  }, [a.phase]);   // eslint-disable-line react-hooks/exhaustive-deps
  stepBack.current = () => {
    if (screen === "parameters") { a.setPhase("descriptions"); setScreen("descriptions"); return true; }
    if (screen === "descriptions") { const mid = a.mediaIds[fi]; if (mid) a.saveOne(mid); setScreen("images"); return true; }
    return false;
  };
  useEffect(() => () => { stepBack.current = null; }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const ids = a.mediaIds;
  const q = a.quote;
  const g = a.gates;
  const editable = a.status === "captionReady";
  const canChangeSet = (a.status === "draft" || a.status === "captionReady") && !a.busy;
  const have = new Set(ids);
  const shown = captionFilter(ids, a.captions, filter);
  const counts = captionCounts(ids, a.captions);
  const cur = Math.min(fi, Math.max(0, ids.length - 1));
  const move = (d) => { const mid = ids[cur]; if (mid) a.saveOne(mid); setFi(stepFocus(cur, ids.length, d)); };
  const title = a.detail ? a.detail.task.title : a.name;

  let step = "";
  let tools = null;
  let cta = null;
  let content = null;
  if (screen === "setup") {
    const line = advancedTriggerLine(a.trigger);
    const ready = !!a.name.trim() && !line.block && !!a.base && !!a.goal;
    step = "1 / 4";
    content = (
      <>
        <div className="trm-h">Set up</div>
        <div className="pubm-lab">Name</div>
        <input className="pubm-in" value={a.name} placeholder="Name your LoRA" onChange={(e) => a.setName(e.target.value)} />
        <div className="pubm-lab">Trigger words</div>
        <textarea className={"pubm-in mono" + (line.warn ? " warn" : "")} rows={2} value={a.trigger}
          placeholder="at least 30 characters" onChange={(e) => a.setTrigger(e.target.value)} />
        <div className={"trm-txt" + (line.warn ? " low" : "")}>{line.text}</div>
        <div className="pubm-lab">Category</div>
        <div className="trm-typerow">
          {GOALS.map((gl) => (
            <button type="button" key={gl.value} className={"trm-typechip" + (a.goal === gl.value ? " on" : "")}
              onClick={() => a.setGoal(gl.value)}>{gl.label}</button>
          ))}
        </div>
        <div className="pubm-lab">Base</div>
        {a.bases.map((bs) => (
          <button type="button" key={bs.version_id} className={"trm-row" + (a.base === bs.version_id ? " sel" : "")}
            aria-pressed={a.base === bs.version_id} onClick={() => a.setBase(bs.version_id)}>
            <span className="trm-row-main">{bs.title}{bs.recommended ? " · Recommended" : ""}</span>
          </button>
        ))}
        <div className="trm-txt">The base can't be changed once you continue. The button below creates the draft on PixAI (free).</div>
        {a.err && <div className="trm-err">⚠ {a.err}</div>}
        <button type="button" className="trm-across" onClick={onBasic}>Use Basic instead</button>
      </>
    );
    cta = <button type="button" className="trm-cta-btn" disabled={!ready || !!a.busy} onClick={a.createDraft}>
      {a.busy === "draft" ? "creating the draft…" : "Next · creates a draft"}</button>;
  } else if (screen === "images") {
    step = "2 / 4";
    content = (
      <>
        <div className="trm-lab">DATASET IMAGES <span className={a.enough ? "ok" : "low"}>{ids.length} / {MAX_IMAGES}</span></div>
        <button type="button" className="trm-row" disabled={!canChangeSet} onClick={() => openSheet("sources")}>
          <span className="trm-row-main">⬆ Upload · ▦ From history</span>
        </button>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden
          onChange={(e) => { const fl = e.target.files; e.target.value = ""; a.upload(fl); }} />
        <PhoneGrid items={ids.map((m) => ({ id: m, thumb: "/api/train/thumb/" + m, reject: a.rejected.includes(m) ? "refused" : "" }))}
          onRemove={canChangeSet ? a.removeImage : null} />
        {a.err && <div className="trm-err">⚠ {a.err}</div>}
        <div className="trm-txt">At least {MIN_IMAGES}. Adding or taking out a picture changes the draft on PixAI (free). Long-press a picture to take it out.</div>
      </>
    );
    cta = <button type="button" className="trm-cta-btn" disabled={!a.enough || !!a.busy}
      onClick={() => { setMode(g.left === ids.length ? "grid" : "focus"); setScreen("descriptions"); }}>
      {a.enough ? "Continue to descriptions" : "Add " + (MIN_IMAGES - ids.length) + " more"}</button>;
  } else if (screen === "descriptions") {
    const mid = ids[cur];
    const text = mid ? a.textOf(mid) : undefined;
    const c = mid ? a.captions[mid] : null;
    const canRestore = editable && c && typeof c.machine_text === "string" && c.machine_text && text !== c.machine_text;
    step = mode === "focus" && ids.length ? (cur + 1) + " / " + ids.length : "3 / 4";
    tools = (
      <>
        <button type="button" className="trm-headbtn" aria-label={mode === "grid" ? "One at a time" : "Grid"}
          title={mode === "grid" ? "One at a time" : "Grid"} onClick={() => { if (mid) a.saveOne(mid); setMode(mode === "grid" ? "focus" : "grid"); }}>
          {mode === "grid" ? "⤢" : "▦"}</button>
        <button type="button" className="trm-headbtn" aria-label="More" title="Filter, find and replace"
          onClick={() => openSheet("more")}>⋯</button>
      </>
    );
    content = (
      <>
        {a.status === "captioning" && (
          <div className="trm-strip-note" role="status">PixAI is describing the images now. This checks again every few seconds; you can leave and come back from Runs.</div>
        )}
        {g.left > 0 && a.status !== "captioning" && (
          <div className="trm-txt">{g.left} of {ids.length} not described yet. PixAI describes them first (paid, quoted below); then you can rewrite each one.</div>
        )}
        {mode === "focus" && mid ? (
          <>
            <img className="trm-dimg" src={"/api/train/thumb/" + mid} alt=""
              onTouchStart={(e) => { touch.current = e.touches[0].clientX; }}
              onTouchEnd={(e) => {
                const x0 = touch.current; touch.current = null;
                if (x0 === null) return;
                const dx = e.changedTouches[0].clientX - x0;
                if (Math.abs(dx) > 40) move(dx < 0 ? 1 : -1);
              }} />
            {typeof text === "string" ? (
              <textarea className="trm-dtext" value={text} maxLength={CAPTION_MAX} disabled={!editable}
                aria-label="Description" onChange={(e) => a.editCaption(mid, e.target.value)} onBlur={() => a.saveOne(mid)} />
            ) : (
              <div className="trm-dtext none">{text === null ? "This description couldn't be read just now." : "Not described yet."}</div>
            )}
            <div className="trm-dmeta">
              <span>{credits(typeof text === "string" ? text.length : 0)} / {credits(CAPTION_MAX)}</span>
              <button type="button" className="trm-linkbtn" disabled={!canRestore} onClick={() => a.restoreAutomatic([mid])}>Restore automatic</button>
              <span className="trm-dnav">
                <button type="button" className="trm-navbtn" disabled={cur === 0} onClick={() => move(-1)} aria-label="Previous">‹</button>
                <button type="button" className="trm-navbtn" disabled={cur >= ids.length - 1} onClick={() => move(1)} aria-label="Next">›</button>
              </span>
            </div>
          </>
        ) : (
          <div className="trm-dgrid">
            {shown.map((m) => {
              const t = a.textOf(m);
              const st = captionState(m, a.captions);
              return (
                <button type="button" key={m} className="trm-dtile" onClick={() => { setFi(ids.indexOf(m)); setMode("focus"); }}>
                  <span className="trm-dtile-img"><img src={"/api/train/thumb/" + m} alt="" />
                    {(st === "edited" || a.edits[m] !== undefined) && <span className="mgtr-dtile-dot" />}</span>
                  <span className={"trm-dtile-text" + (typeof t === "string" ? "" : " none")}>
                    {typeof t === "string" ? t : t === null ? "couldn't be read" : "Not described yet"}</span>
                </button>
              );
            })}
          </div>
        )}
        {a.saving > 0 && <div className="trm-txt" role="status">Saving {a.saving} edit{a.saving === 1 ? "" : "s"}…</div>}
        {done && <div className="trm-txt">{done}</div>}
        {a.err && <div className="trm-err">⚠ {a.err}</div>}
        {!g.next && g.left === 0 && ids.length > 0 && <div className="trm-txt">{g.whyNoNext}</div>}
      </>
    );
    cta = g.left > 0 && a.status !== "captioning" ? (
      <button type="button" className="trm-cta-btn" disabled={!g.describe} onClick={() => openSheet("describe")}>
        {describeLabel(q)}</button>
    ) : (
      <button type="button" className="trm-cta-btn" disabled={!g.next} onClick={a.toParameters}>
        {a.busy === "quote" ? "asking PixAI's price…" : "Next: parameters"}</button>
    );
  } else {
    const ask = a.startAsk;
    const eta = (ask && ask.eta) || etaForSteps(ADVANCED_DEFAULTS.steps);
    step = "4 / 4";
    content = a.started ? (
      <div className="trm-done">
        ✓ Training started{a.started.used_free_training ? " — it used one of your free trainings" : ""}. It shows in Runs.
        <button type="button" className="trm-across" onClick={onRuns}>See it in Runs ›</button>
      </div>
    ) : (
      <>
        <div className="trm-h">Parameters</div>
        <div className="trm-txt">{title}{ask ? " · " + ask.image_count + " images, all described" : ""}</div>
        {[["Length (steps)", String(ADVANCED_DEFAULTS.steps), trackPercent(ADVANCED_DEFAULTS.steps, STEP_RANGE)],
          ["Learning rate", "6e-4 · default", trackPercent(ADVANCED_DEFAULTS.learningRate, LR_RANGE)],
          ["Detail capacity (rank)", ADVANCED_DEFAULTS.rank + " · default", null]].map(([n, v, fill]) => (
          <div key={n} className="mgtr-param locked" aria-disabled="true">
            <div className="mgtr-param-head"><span className="n">{n}</span><span className="v">{v}</span></div>
            {fill !== null && <div className="mgtr-param-track"><div style={{ width: fill + "%" }} /></div>}
            <div className="mgtr-param-note">Locked by PixAI for now</div>
          </div>
        ))}
        <div className="mgtr-ranks" aria-disabled="true">
          {RANKS.map((r) => <span key={r} className={"mgtr-rank" + (r === ADVANCED_DEFAULTS.rank ? " on" : "")}>{r}</span>)}
        </div>
        <div className="trm-txt">PixAI's own page sends these defaults today (325 steps, learning rate 6e-4, rank 64, gradient accumulation 2), and so does this app.</div>
        <div className="mgtr-quote">
          <div className="mgtr-quote-head"><span className="n">Quote</span>
            <span className="p">{ask ? (ask.is_free ? "free" : credits(ask.price)) : "—"}</span></div>
          <div className="mgtr-note">PixAI's price for this run today, by its base. Free to ask; nothing is spent until Start. {sentence(etaText(eta))}</div>
        </div>
        {!ask && !a.busy && <button type="button" className="trm-across" onClick={a.refreshQuote}>Ask PixAI's price again</button>}
        {a.err && <div className="trm-err">⚠ {a.err}</div>}
        {a.maybe && <div className="trm-warn">PixAI didn't answer clearly, so this run may have started; check Runs before starting again.</div>}
      </>
    );
    cta = a.started ? null : (
      <button type="button" className="trm-cta-btn" disabled={!ask || !!a.busy || a.saving > 0} onClick={() => openSheet("start")}>
        {!ask ? "Start training" : startLabel(ask)}</button>
    );
  }

  const describeQ = q && q.image_count > 0 ? q : null;
  const per = perImage(q);
  const target = () => {
    const described = shown.filter((m) => typeof a.textOf(m) === "string");
    return described;
  };
  const tool = (fn, verb) => {
    const k = a.applyAll(target(), fn);
    setDone(k ? verb + " " + k + " description" + (k === 1 ? "" : "s") + "." : "Nothing to change.");
    closeSheet();
  };
  const sheets = (
    <>
      <SourcesSheet open={sheet === "sources"} closing={closing} onClose={closeSheet}
        onUpload={() => { closeSheet(); if (fileRef.current) fileRef.current.click(); }}
        onHistory={() => openSheet("history")} />
      <MobileSheet open={sheet === "history"} closing={closing} onClose={closeSheet} className="trm-sheet" title="FROM HISTORY">
        <PhonePool have={have} room={Math.max(0, MAX_IMAGES - ids.length)} onCancel={closeSheet}
          onAdd={(entries) => { a.addImages(entries); closeSheet(); }} />
      </MobileSheet>
      <MobileSheet open={sheet === "describe"} closing={closing} className="trm-sheet"
        onClose={() => { if (!a.busy) closeSheet(); }} title="DESCRIBE AUTOMATICALLY">
        <div className="pubm-confirmmeta">
          <b>Describe {describeQ ? describeQ.image_count : g.left} image{describeQ && describeQ.image_count === 1 ? "" : "s"} automatically?</b>
          {describeQ && <span className="trm-gold"> {credits(describeQ.total_price)}</span>}
        </div>
        <div className="pubm-note" style={{ marginBottom: 12 }}>
          {per != null ? credits(per) + " credits per image, PixAI's quote for this set, " : ""}charged when it runs, on PixAI. PixAI describes first; you can rewrite every description afterwards.
        </div>
        {!g.describe && <div className="trm-txt">{g.whyNoDescribe}</div>}
        <div className="glm-sheet-actions">
          <button type="button" className="glm-metal glm-widebtn" onClick={closeSheet} disabled={!!a.busy}>Back</button>
          <button type="button" className="glm-primary glm-widebtn" disabled={!g.describe}
            onClick={async () => { await a.describe(); closeSheet(); }}>
            {a.busy === "describe" ? "sending…" : describeQ ? "Describe · " + credits(describeQ.total_price) : "Describe"}</button>
        </div>
      </MobileSheet>
      <MobileSheet open={sheet === "start"} closing={closing} className="trm-sheet"
        onClose={() => { if (!a.busy) closeSheet(); }} title="QUEUE TRAINING RUN">
        {a.startAsk && (
          <>
            <div className="pubm-confirmmeta">
              <b>{title || "Untitled LoRA"}</b> · Advanced · {a.detail ? a.detail.task.base_name : ""} · {a.startAsk.image_count} images
            </div>
            <div className="pubm-note" style={{ marginBottom: 12 }}>
              {a.startAsk.is_free ? "PixAI quotes this run as free." : "PixAI's price for this run: " + credits(a.startAsk.price) + " credits, charged when it starts."} Parameters at PixAI's defaults.
            </div>
            {a.err && <div className="trm-err">⚠ {a.err}</div>}
            <div className="glm-sheet-actions">
              <button type="button" className="glm-metal glm-widebtn" onClick={closeSheet} disabled={!!a.busy}>Back</button>
              <button type="button" className="glm-primary glm-widebtn" disabled={!!a.busy || !!a.started}
                onClick={async () => { await a.start(); closeSheet(); }}>
                {a.busy === "start" ? "starting…" : startLabel(a.startAsk)}</button>
            </div>
          </>
        )}
      </MobileSheet>
      <MobileSheet open={sheet === "more"} closing={closing} onClose={closeSheet} className="trm-sheet" title="DESCRIPTIONS">
        <div className="trm-lab">SHOW</div>
        <div className="trm-typerow">
          {CAPTION_FILTERS.map((fl) => (
            <button type="button" key={fl.key} className={"trm-typechip" + (filter === fl.key ? " on" : "")}
              onClick={() => { setFilter(fl.key); setMode("grid"); closeSheet(); }}>{fl.label} {counts[fl.key]}</button>
          ))}
        </div>
        {editable ? (
          <>
            <div className="trm-lab" style={{ marginTop: 12 }}>FIND AND REPLACE · TAGS</div>
            <input className="pubm-in" value={find} placeholder="⌕ find, or a tag" onChange={(e) => setFind(e.target.value)} />
            <input className="pubm-in" value={repl} placeholder="replace with…" onChange={(e) => setRepl(e.target.value)} />
            <div className="trm-txt">Changes every described image {filter === "all" ? "" : "in this filter "}and saves each one.</div>
            <div className="glm-sheet-actions">
              <button type="button" className="glm-metal glm-widebtn" disabled={!find}
                onClick={() => tool((t) => replaceIn(t, find, repl), "Changed")}>Replace</button>
              <button type="button" className="glm-metal glm-widebtn" disabled={!find.trim()}
                onClick={() => tool((t) => addTag(t, find), "Tagged")}>+ tag</button>
              <button type="button" className="glm-metal glm-widebtn" disabled={!find.trim()}
                onClick={() => tool((t) => removeTag(t, find), "Untagged")}>− tag</button>
            </div>
          </>
        ) : (
          <div className="trm-txt" style={{ marginTop: 12 }}>Find, replace and tags work once PixAI has described the images.</div>
        )}
      </MobileSheet>
    </>
  );

  return (
    <>
      <HeadAside head={head}>{tools}<span className="trm-step">{step}</span></HeadAside>
      <Screen cta={cta}>{content}</Screen>
      {host && createPortal(sheets, host)}
    </>
  );
}

/* ------------------------------------------------------------------------ shared pieces */

/* The three sources as ONE bottom sheet (handoff F2). Advanced has no dataset import. */
function SourcesSheet({ open, closing, onClose, onUpload, onHistory, onImport, withImport }) {
  return (
    <MobileSheet open={open} closing={closing} onClose={onClose} className="trm-sheet" title="ADD IMAGES">
      <div className="glm-sheet-list">
        <button type="button" className="trm-row" onClick={onUpload}><span className="trm-row-main">⬆ Upload from this phone</span></button>
        <button type="button" className="trm-row" onClick={onHistory}><span className="trm-row-main">▦ From history</span></button>
        {withImport && (
          <button type="button" className="trm-row" onClick={onImport}><span className="trm-row-main">⎘ Import a dataset</span></button>
        )}
      </div>
    </MobileSheet>
  );
}

/* The set as a 3-column grid; a long press takes a picture out (handoff F2). */
function PhoneGrid({ items, onRemove }) {
  const timer = useRef(null);
  const cancel = () => { clearTimeout(timer.current); timer.current = null; };
  if (!items.length) return <div className="trm-grid empty"><span>No pictures yet.</span></div>;
  return (
    <div className="trm-grid">
      {items.map((it) => (
        <div key={it.id} className={"trm-gtile" + (it.reject ? " reject" : "")} role="img"
          aria-label={it.reject ? "Rejected: " + it.reject : "Picture"} title={onRemove ? "Long-press to take it out" : ""}
          onContextMenu={(e) => e.preventDefault()}
          onPointerDown={() => { if (!onRemove) return; cancel(); timer.current = setTimeout(() => { timer.current = null; onRemove(it.id); }, 550); }}
          onPointerUp={cancel} onPointerLeave={cancel} onPointerCancel={cancel}>
          <img src={it.thumb} alt="" draggable={false} />
          {it.reject && <span className="trm-greject">{it.reject}</span>}
        </div>
      ))}
    </div>
  );
}

/* "From history" on the phone: the recent generations BY TASK, paging on scroll through a
   sentinel observed from the sheet's own scroller (issue #56's mechanism, the desktop pool's);
   a tile adds all of that generation's pictures. Nothing reaches PixAI from here. */
function PhonePool({ have, room, onAdd, onCancel }) {
  const pool = useHistoryPool({ mode: "grouped" });
  const [tray, setTray] = useState([]);              // [{key, entries}]
  const end = useRef(null);
  const { loadMore } = pool;
  useEffect(() => { loadMore(); }, [loadMore]);
  useEffect(() => {
    const el = end.current;
    if (!el || typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) loadMore();
    }, { root: scrollParentOf(el), rootMargin: "600px 0px", threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore, pool.items.length]);
  const picked = tray.flatMap((t) => t.entries);
  const toggle = (it) => {
    setTray((cur) => {
      if (cur.some((t) => t.key === it.key)) return cur.filter((t) => t.key !== it.key);
      const used = cur.reduce((n, t) => n + t.entries.length, 0);
      const fresh = (it.media_ids || []).map(String).filter((m) => !have.has(m))
        .map((m, i) => ({ media_id: m, thumb: i === 0 ? it.thumb : "/api/train/thumb/" + m }));
      const fit = fresh.slice(0, Math.max(0, room - used));
      return fit.length ? cur.concat([{ key: it.key, entries: fit }]) : cur;
    });
  };
  return (
    <>
      <div className="trm-tilehead">Recent generations — tap to add <i>· adds all of that task's images · {picked.length} picked, room for {room}</i></div>
      <div className="trm-tiles">
        {pool.items.map((it) => {
          const on = tray.some((t) => t.key === it.key);
          const already = (it.media_ids || []).every((m) => have.has(String(m)));
          return (
            <button type="button" key={it.key} className={"trm-tile" + (on ? " on" : "") + (already ? " have" : "")}
              disabled={already} onClick={() => toggle(it)}>
              <img src={it.thumb} alt="" loading="lazy" />
              <span className="trm-tilebadge">×{it.count}</span>
              {(on || already) && <span className="trm-tilecheck">✓</span>}
            </button>
          );
        })}
      </div>
      <div ref={end} className="trm-gridend" aria-hidden="true" />
      <div className="glm-sheet-actions">
        <button type="button" className="glm-metal glm-widebtn" onClick={onCancel}>Back</button>
        <button type="button" className="glm-primary glm-widebtn" disabled={!picked.length}
          onClick={() => onAdd(picked)}>Add {picked.length || ""}</button>
      </div>
    </>
  );
}
