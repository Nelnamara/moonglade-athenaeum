import React, { useRef, useState } from "react";
import TrainPool from "./TrainPool.jsx";
import DatasetImport from "./DatasetImport.jsx";
import GoalTile from "./GoalTile.jsx";
import {
  GOALS, MAX_IMAGES, MIN_IMAGES, SOURCE_MARK, credits, etaText, roomLeft, startLabel,
} from "../../gen/trainCore.js";

/* Basic training, desktop (Training Handoff B / decision 2a, base picker 6a): PixAI's three
   steps -- 1 Choose a goal · 2 Add images · 3 Review and start -- with ‹ Back to the chooser and
   a link across to Advanced on every step. `b` is useBasicTraining(). Start is a preview (the
   server's quote, the free position) and then the ONE confirm: the quoted amount on its button
   and, on a paid run, ticked (the shipped rule). An unclear failure says the run may have
   started (BUILD 7.1). The step lives in the overlay so a trip to Advanced and back keeps it. */

const STEPS = ["Choose a goal", "Add images", "Review and start"];
const GOAL_TINT = ["lavender", "mauve", "emerald", "peach"];

export default function TrainBasic({ b, setup, step, setStep, onBack, onAdvanced, onRuns }) {
  const [src, setSrc] = useState("");               // "", "history", "import"
  const fileRef = useRef(null);
  const have = new Set(b.items.map((x) => x.media_id));
  const go = (n) => { if (n < step || (n === 2 && b.goal) || (n === 3 && b.enough && b.goal)) setStep(n); };
  const goalLabel = (GOALS.find((g) => g.value === b.goal) || {}).label || "";
  const tab = b.tab !== null ? b.tabs[b.tab] : null;
  const eta = setup.cfg && setup.cfg.eta;
  const f = b.footer;

  return (
    <div className="mgtr-wiz">
      <div className="mgtr-wizhead">
        <button type="button" className="mgtr-back" onClick={onBack}>‹ Back</button>
        <span className="mgtr-badge">Basic training</span>
        <ol className="mgtr-stepper">
          {STEPS.map((s, i) => (
            <li key={s} className={step === i + 1 ? "on" : step > i + 1 ? "done" : ""}>
              <button type="button" onClick={() => go(i + 1)}>{i + 1} {s}</button>
            </li>
          ))}
        </ol>
      </div>

      {step === 1 && (
        <div className="mgtr-card">
          <div className="mgtr-kick">1 · CHOOSE A GOAL</div>
          <div className="mgtr-h">What do you want to train?</div>
          <div className="mgtr-goals">
            {GOALS.map((g, i) => (
              <button type="button" key={g.value} className={"mgtr-goal" + (b.goal === g.value ? " on" : "")}
                onClick={() => { b.setGoal(g.value); setStep(2); }}>
                <GoalTile goal={g} tint={GOAL_TINT[i]} />
                <span><span className="n">{g.label}</span><span className="d">{g.desc}</span></span>
              </button>
            ))}
          </div>
          <button type="button" className="mgtr-across" onClick={onAdvanced}>Need to edit descriptions or parameters? Use Advanced</button>
        </div>
      )}

      {step === 2 && (
        <div className="mgtr-card">
          <div className="mgtr-kick">2 · ADD IMAGES</div>
          <div className="mgtr-sources">
            <button type="button" className="mgtr-src" onClick={() => fileRef.current && fileRef.current.click()}>⬆ Upload</button>
            <button type="button" className={"mgtr-src" + (src === "history" ? " on" : "")}
              onClick={() => setSrc(src === "history" ? "" : "history")}>▦ From history</button>
            <button type="button" className={"mgtr-src" + (src === "import" ? " on" : "")}
              onClick={() => { b.loadDatasets(); setSrc(src === "import" ? "" : "import"); }}>⎘ Import a dataset</button>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden
              onChange={(e) => { const fl = e.target.files; e.target.value = ""; b.upload(fl); }} />
          </div>
          {src === "import" && (
            <DatasetImport datasets={b.datasets} items={b.items} imported={b.imported}
              onImport={(sets) => { b.importSets(sets); if (sets.length === 1) b.takeDetails(sets[0]); }}
              onClose={() => setSrc("")} />
          )}
          {src === "history" && (
            <TrainPool have={have} room={roomLeft(b.items)}
              onAdd={(tray) => b.addImages(tray, "history")} onClose={() => setSrc("")} />
          )}
          <div className="mgtr-grid">
            {b.items.map((it) => (
              <div key={it.media_id} className={"mgtr-gtile" + (it.reject ? " reject" : "")}
                title={it.reject ? "PixAI won't train on this one: " + it.reject : ""}>
                <img src={it.thumb || "/api/train/thumb/" + it.media_id} alt="" />
                <span className="mgtr-gsrc" title={it.source}>{SOURCE_MARK[it.source] || ""}</span>
                {it.reject && <span className="mgtr-greject">{it.reject}</span>}
                <button type="button" className="mgtr-gx" onClick={() => b.removeImage(it.media_id)}
                  aria-label="Take it out" title="Take it out">×</button>
              </div>
            ))}
            {Array.from({ length: Math.max(0, 16 - b.items.length) }, (_, i) => (
              <div key={"e" + i} className="mgtr-gtile empty" />
            ))}
          </div>
          <div className="mgtr-count">
            <div className="mgtr-countbar"><div className={b.enough ? "ok" : "low"}
              style={{ width: Math.min(100, b.counted.length) + "%" }} /></div>
            <div className={"mgtr-mono " + (b.enough ? "ok" : "low")}>{b.counted.length} / {MAX_IMAGES}</div>
          </div>
          {b.rejects.length > 0 && (
            <div className="mgtr-rejects">
              {b.rejects.length} left out: {b.rejects.map((r) => r.name + " (" + r.reason + ")").join(" · ")}
              <button type="button" className="mgtr-linkbtn" onClick={b.clearRejects}>dismiss</button>
            </div>
          )}
          <div className="mgtr-note">PNG, JPG or WebP, at least 512×512, no wider than 3:1. At least {MIN_IMAGES}. Rejected files show with a peach reason and aren't counted. Tiles carry a source mark (⬆ ▦ ⎘).</div>
          <div className="mgtr-row-end">
            <button type="button" className="mgtr-across" onClick={onAdvanced}>Need to edit descriptions or parameters? Use Advanced</button>
            <button type="button" className="mgtr-go" disabled={!b.enough} onClick={() => setStep(3)}>
              {b.enough ? "Continue to review" : "Add " + (MIN_IMAGES - b.counted.length) + " more"}</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="mgtr-card">
          <div className="mgtr-kick">3 · REVIEW AND START</div>
          <label className="mgtr-lab" htmlFor="mgtr-name">LoRA name <span>required</span></label>
          <input id="mgtr-name" className="mgtr-in" value={b.name} placeholder="Name your LoRA"
            onChange={(e) => b.setName(e.target.value)} />
          <label className="mgtr-lab" htmlFor="mgtr-trig">Trigger words <span>required</span></label>
          <input id="mgtr-trig" className={"mgtr-in mono" + (b.trigger && !b.trig.ok ? " warn" : "")}
            value={b.trigger} placeholder="e.g. kaia" onChange={(e) => b.setTrigger(e.target.value)} />
          <div className={"mgtr-hint" + (b.trigger && !b.trig.ok ? " warn" : "")}>
            {b.trigger && !b.trig.ok ? b.trig.length + " / 256: " + b.trig.problem + "."
              : "Short, unusual words work best. Add it to a prompt to use the LoRA."}
          </div>
          <div className="mgtr-lab">Base model</div>
          <div className="mgtr-basebox">
            <div className="mgtr-tabs" role="tablist">
              {b.tabs.map((t, i) => (
                <button type="button" key={t.arch} role="tab" aria-selected={b.tab === i}
                  className={"mgtr-tab" + (b.tab === i ? " on" : "")} onClick={() => b.pickTab(i)}>
                  {t.label}{t.recommended ? " · Recommended" : ""}
                </button>
              ))}
            </div>
            <div className="mgtr-bases">
              {(tab ? tab.models : []).map((m) => (
                <button type="button" key={m.version_id} title={m.title}
                  className={"mgtr-base" + (b.base === m.version_id ? " on" : "")} onClick={() => b.setBase(m.version_id)}>
                  {m.cover ? <img src={"/api/train/cover?u=" + encodeURIComponent(m.cover)} alt="" /> : <span className="ph" />}
                  {m.title}
                </button>
              ))}
            </div>
            <div className="mgtr-note">Your LoRA only works with this model. It's selected automatically when you use the LoRA.</div>
          </div>
          <button type="button" className="mgtr-across left" onClick={onAdvanced}>Switch to Advanced to edit descriptions and parameters</button>

          {b.done ? (
            <div className="mgtr-ok">
              ✓ Training started{b.done.used_card ? " — it used your training free card"
                : b.done.was_free ? " — it used one of your free trainings" : ""}. It shows in Runs.
              {onRuns && <button type="button" className="mgtr-linkbtn" onClick={onRuns}>See it in Runs ›</button>}
            </div>
          ) : b.ask ? (
            <div className="mgtr-confirm">
              <div className="t">Start this training on PixAI?</div>
              <div className="b">
                <b>{b.ask.title}</b> · {b.ask.image_count} images · {goalLabel} · {b.baseName}
                {b.ask.reuse ? " · reusing a dataset" : ""}
                <div className="n">{b.ask.cost_note}{b.ask.image_note ? " " + b.ask.image_note : ""}</div>
                {!b.ask.is_free && (
                  <label className="mgtr-accept">
                    <input type="checkbox" checked={b.accepted} onChange={(e) => b.setAccepted(e.target.checked)} />
                    <span>{b.ask.price != null ? "Spend " + credits(b.ask.price) + " credits on this training."
                      : "Spend credits on this training — the amount could not be quoted."}</span>
                  </label>
                )}
              </div>
              {b.err && <div className="mgtr-err">⚠ {b.err}</div>}
              <div className="a">
                <button type="button" className="mgtr-ghost" onClick={() => b.setAsk(null)} disabled={b.busy}>Back</button>
                <button type="button" className="mgtr-go" disabled={b.busy || (!b.ask.is_free && !b.accepted)}
                  onClick={b.confirm}>{b.busy ? "starting…" : startLabel(b.ask)}</button>
              </div>
            </div>
          ) : (
            <div className="mgtr-foot">
              <div className="mgtr-foot-sum">
                ✓ {goalLabel || "—"} · ✓ {b.counted.length} images · ✓ {b.baseName || "—"} · Standard settings
                {f.reason ? " · " + f.reason : ""}
              </div>
              <div className="mgtr-foot-price">
                <div className="p">
                  {f.free && f.struck != null && <span className="struck">{credits(f.struck)}</span>}
                  <span className="gold">🪙 {f.price != null ? credits(f.price) : "?"}</span>
                  {f.badge && <span className="freebadge">{f.badge}</span>}
                </div>
                <div className="eta">{etaText(eta)}</div>
              </div>
              <button type="button" className="mgtr-go big" disabled={!b.ready || b.busy} onClick={b.preview}>
                {b.busy ? "checking…" : "Start training"}</button>
            </div>
          )}
          {!b.ask && b.err && !b.maybe && <div className="mgtr-err">⚠ {b.err}</div>}
          {b.maybe && (
            <div className="mgtr-warnnote">
              PixAI didn't answer clearly, so this run may have started; check Runs before starting again.
              {onRuns && <button type="button" className="mgtr-linkbtn" onClick={onRuns}>Check Runs ›</button>}
            </div>
          )}
          {setup.paused && <div className="mgtr-warnnote">PixAI has paused new training runs{setup.resumesAt ? " until about " + setup.resumesAt : ""}; Start waits until it opens again.</div>}
        </div>
      )}
    </div>
  );
}
