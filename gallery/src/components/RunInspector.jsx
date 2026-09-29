import React, { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import "../styles/runs.css";

/* The Inspector (NOTES 7, page M5 "Raw recipe inspector"): the exact request per job, after
   the variables are filled in, with the template and the drawn values alongside. Copy JSON;
   Copy as CLI -- the app's REAL command and flags (Settled 1), as the server wrote them.

   The secrets are stripped on the server before anything reaches here (removed from the
   data, never hidden in CSS): the API key, cookies, session tokens and the csrf field never
   ride a request body this panel can see. Read-only; it writes nothing.

   `source`: {kind: "plan", plan} -- the confirm's /plan answer, "preview · not sent yet"
           | {kind: "task", taskId} -- one sent task, GET /api/generate/request/<id> */
export default function RunInspector({ source, onClose, floating }) {
  const [tab, setTab] = useState("json");
  const [cell, setCell] = useState(0);
  const [task, setTask] = useState(null);
  const [copied, setCopied] = useState(false);
  const taskId = source && source.kind === "task" ? source.taskId : "";

  useEffect(() => {
    if (!taskId) { setTask(null); return undefined; }
    let live = true;
    setTask({ loading: true });
    apiGet("/api/generate/request/" + encodeURIComponent(taskId)).then((d) => {
      if (live) setTask(d);
    });
    return () => { live = false; };
  }, [taskId]);
  useEffect(() => { setCell(0); }, [source]);

  if (!source) return null;
  let what, entry, cells = [];
  if (source.kind === "plan") {
    cells = (source.plan && source.plan.cells) || [];
    entry = cells[Math.min(cell, Math.max(0, cells.length - 1))] || null;
    what = "preview · not sent yet";
  } else {
    entry = task && !task.loading && !task.error ? task : null;
    what = task && task.source === "pixai" ? "as PixAI stored it" : "as sent";
  }
  const json = entry && entry.request ? JSON.stringify(entry.request, null, 2) : "";
  const cli = entry && entry.cli ? entry.cli.command : "";
  const planError = source.kind === "plan" && source.plan && source.plan.error;
  const text = task && task.loading ? "Reading…" : task && task.error ? task.error
    : entry ? (tab === "cli" ? cli : json) : planError || "Nothing to show.";
  const meta = [];
  if (entry && entry.template && entry.template !== entry.prompt) meta.push("template: " + entry.template);
  if (entry && entry.vars && entry.vars.length) meta.push("vars: " + entry.vars.map((v) => v.token + " = " + v.value).join(" · "));
  if (source.kind === "plan" && source.plan && source.plan.run_seed != null) meta.push("run seed: " + source.plan.run_seed);
  const copy = () => {
    const out = tab === "cli" ? cli : json;
    if (!out) return;
    try { navigator.clipboard.writeText(out); } catch { /* the text is on screen to select */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  return (
    <div className={"mgrun-insp" + (floating ? " float" : "")} role="dialog" aria-label="Inspect the request">
      <div className="mgrun-insphead">
        <div className="mgrun-insptitle">{"{ } INSPECT · " + what}</div>
        {[["json", "JSON"], ["cli", "CLI"]].map(([k, l]) => (
          <button key={k} type="button" className={"mgrun-inspbtn" + (tab === k ? " on" : "")}
            onClick={() => setTab(k)}>{l}</button>
        ))}
        <button type="button" className="mgrun-copy" onClick={copy} disabled={!entry}>
          {copied ? "Copied ✓" : tab === "cli" ? "Copy as CLI" : "Copy JSON"}
        </button>
        <button type="button" className="mgrun-inspx" onClick={onClose} title="Close the inspector">×</button>
      </div>
      {cells.length > 1 && (
        <div className="mgrun-insphead">
          {cells.map((c, i) => (
            <button key={c.cell} type="button" className={"mgrun-inspbtn" + (i === cell ? " on" : "")}
              title={c.prompt} onClick={() => setCell(i)}>{i + 1}</button>
          ))}
        </div>
      )}
      {meta.length ? <div className="mgrun-inspmeta">{meta.join("\n")}</div> : null}
      <pre className="mgrun-inspbody">{text}</pre>
      <div className="mgrun-inspfoot">Read-only. The API key, cookies and session tokens are never in it.</div>
    </div>
  );
}
