import React, { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import { matrixGrid } from "../gen/templateCore.js";
import { PresetsPanel } from "./PowerControls.jsx";
import "../styles/power.css";

/* The phone's half of Session M's power tools (Generate Power Tools Handoff, the Phone
   paragraph and rules M1 / M3 / M4 / M6):

     - ↺ Last and Presets as two chips above the prompt (presets open as a sheet);
     - the quick-pick chips as ONE horizontally scrolling row, models then LoRAs, 36 px chips;
     - the prompt toolbar's { } key (inserts a variable) and Lists (opens the sheet);
     - a matrix run's results as a grid (setting a matrix up is desktop-only).

   Drawing only. What a chip does, what a preset holds and how a default fills are
   gen/powerCore.js and gen/useGenerate.js (`g.power`), the same road the dock takes. */

export function PhoneChips({ power, onPresets }) {
  const hasLast = !!power.last;
  return (
    <div className="pm-chips">
      <button type="button" className="pm-chip" disabled={!hasLast || power.restoring}
        title={hasLast ? "Refill from your last send" : "Available after your first send"}
        onClick={power.restoreLast}>↺ Last</button>
      <button type="button" className="pm-chip" aria-haspopup="dialog" onClick={onPresets}>Presets</button>
    </div>
  );
}

/* One scrolling row: models, then LoRAs (a LoRA for another family dimmed, its reason in the
   title), then "+ more" into the picker. Shown only while there is a chip to show. */
export function PhoneQuickRow({ power, ctxOn, onMore }) {
  const models = power.modelChips, loras = ctxOn ? [] : power.loraChips;
  if (!models.length && !loras.length) return null;
  return (
    <div className="pm-quick" role="group" aria-label="Quick picks">
      {models.map((c) => (
        <button key={"m" + c.id} type="button" className={"pm-chip" + (c.on ? " on" : "")}
          title={c.title} aria-pressed={c.on} onClick={() => power.pickModelChip(c.entry)}>{c.label}</button>
      ))}
      {loras.map((c) => (
        <button key={"l" + c.id} type="button" className={"pm-chip" + (c.on ? " on" : "") + (c.dim ? " dim" : "")}
          title={c.title} aria-pressed={c.on} aria-disabled={c.dim || undefined}
          onClick={() => { if (!c.dim) power.toggleLoraChip(c.entry); }}>{c.label}</button>
      ))}
      <button type="button" className="pm-chip" title="Opens the picker" onClick={onMore}>+ more</button>
    </div>
  );
}

/* The prompt toolbar: { } puts a variable at the caret with its options selected, ready to
   type over; Lists opens the saved-lists sheet. Nothing here writes until the prompt is
   sent or a list is saved. */
export function PromptTools({ taRef, prompt, set, onLists }) {
  const insert = () => {
    const ta = taRef && taRef.current;
    const text = "{a|b}";
    const at = ta && typeof ta.selectionStart === "number" ? ta.selectionStart : prompt.length;
    const end = ta && typeof ta.selectionEnd === "number" ? ta.selectionEnd : at;
    set({ prompt: prompt.slice(0, at) + text + prompt.slice(end), note: "" });
    // select "a|b" once React has written the value, so the next keystrokes replace it
    setTimeout(() => {
      const el = taRef && taRef.current;
      if (!el) return;
      try { el.focus(); el.setSelectionRange(at + 1, at + text.length - 1); } catch { /* not focusable */ }
    }, 0);
  };
  return (
    <div className="pm-tools">
      <button type="button" className="pm-key" title="Insert a variable: {a|b|c}" aria-label="Insert a variable"
        onClick={insert}>{"{ }"}</button>
      <button type="button" className="pm-chip" style={{ height: 36 }} title="Your saved lists — __name__ in a prompt"
        onClick={onLists}>Lists</button>
    </div>
  );
}

export function PresetsSheetBody({ power, onDone }) {
  return (
    <div className="pm-sheetbody">
      <PresetsPanel power={power} onDone={onDone} phone />
    </div>
  );
}

/* A matrix run's results as a grid (NOTES 8, phone): the last axis across, the rest down,
   labelled from the run's own axes; each cell a normal picture (a tap opens its details). A
   cell that was not sent, was refused or may have started is peach, never ruby. Read only:
   GET /api/generate/runs/<id> and GET /api/jobs; nothing is written. */
export function MatrixGrid({ runId, onOpenImage }) {
  const [rec, setRec] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    let timer = 0;
    const load = async () => {
      const [r, j] = await Promise.all([apiGet("/api/generate/runs/" + encodeURIComponent(runId)), apiGet("/api/jobs")]);
      if (!live) return;
      if (!r || r.error) { setErr((r && r.error) || "Couldn't read this run."); return; }
      setRec(r);
      const mine = ((j && j.jobs) || []).filter((x) => x.run === runId);
      setJobs(mine);
      const running = mine.some((x) => !["done", "failed", "done_with_errors", "stale"].includes(x.status || "running"));
      if (running || r.status === "sending") timer = setTimeout(load, 4000);
    };
    load();
    return () => { live = false; clearTimeout(timer); };
  }, [runId]);
  if (err) return <div className="pm-gridnote">{err}</div>;
  if (!rec) return <div className="pm-gridnote">Reading the run…</div>;
  const byTask = {};
  for (const j of jobs) byTask[j.job_id] = j;
  const cells = (rec.jobs || []).map((c) => ({ ...c, job: c.task_id ? byTask[c.task_id] : null }));
  const grid = matrixGrid(rec.axes, cells);
  if (!grid) return <div className="pm-gridnote">This run has no grid.</div>;
  const cols = grid.across.length;
  return (
    <div>
      <div className="pm-gridnote">{cells.length} cells · {grid.across.length} across · tap a picture to open it</div>
      <div className="pm-grid" style={{ gridTemplateColumns: "56px repeat(" + cols + ", minmax(58px, 1fr))" }}>
        <span />
        {grid.across.map((a, i) => <span key={"a" + i} className="pm-axis" title={a}>{a}</span>)}
        {grid.rows.map((row, r) => (
          <React.Fragment key={"r" + r}>
            <span className="pm-rowlbl" title={row.label}>{row.label}</span>
            {row.cells.map((c, k) => {
              const j = c && c.job;
              const done = j && j.status === "done" && (j.media_ids || []).length;
              const running = j && !["done", "failed", "done_with_errors", "stale"].includes(j.status || "running");
              const held = !c || (!j && c.state !== "sent") || (j && j.status === "failed");
              const why = !c ? "not sent" : c.state === "may_have_started"
                ? "may have started on PixAI — check the Activity tray" : c.state === "refused"
                  ? "refused by PixAI" + (c.error ? ": " + c.error : "") : c.state === "not_sent" ? "not sent" : "";
              return (
                <button key={"c" + r + ":" + k} type="button" disabled={!done}
                  className={"pm-cell" + (done ? " done" : "") + (held && !done ? " held" : "")}
                  title={(c && c.prompt ? c.prompt : "") + (why ? " — " + why : "")}
                  onClick={done ? () => onOpenImage(j.media_ids[0]) : undefined}>
                  {done ? <img src={"/thumbs/" + encodeURIComponent(j.media_ids[0]) + ".jpg"} alt="" /> : null}
                  {running && !done ? "…" : null}
                  {held && !done ? "⚠" : null}
                </button>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
