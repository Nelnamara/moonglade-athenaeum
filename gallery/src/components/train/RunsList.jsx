import React, { useState } from "react";
import MoonGauge from "../MoonGauge.jsx";
import { fractionFromPercent, GAUGE_SIZES } from "../../lib/moonGaugeCore.js";
import { RUN_FILTERS, credits, etaLeftText, runMatches, runStatus, startLabel } from "../../gen/trainCore.js";

/* Runs (Training Handoff 5c): filters All / Drafts / Done / Failed, then one row per run --
   cover, name, mode · base · images, a status pill (Draft peach named by its step · Queued /
   Training lavender with PixAI's % · Done emerald · Failed ruby with PixAI's reason on hover)
   and ONE action (Continue / View / Publish / Retry / Use). Published rows show Private or
   Public · rebates; a Private one opens the make-public sheet. A training row carries the moon
   gauge (L4) when PixAI reports a percentage. `onAction(kind, row)` is the host's. */
export function RunRow({ row, onAction, gaugeSize = GAUGE_SIZES.runs, phone = false }) {
  const [open, setOpen] = useState(false);
  const s = runStatus(row);
  const f = row.status === "running" ? fractionFromPercent(row.progress) : null;
  const meta = [row.mode === "advanced" ? "Advanced" : "Basic", row.base_name,
    row.image_count ? row.image_count + " images" : ""].filter(Boolean).join(" · ");
  const act = (kind) => (kind === "view" ? setOpen((v) => !v) : onAction(kind, row));
  const primary = s.action === "continue" || s.action === "publish";
  return (
    <div className={"mgtr-run" + (open ? " open" : "")}>
      <div className="mgtr-run-main">
        {row.cover ? <img className="mgtr-run-cover" src={row.cover} alt="" /> : <span className="mgtr-run-cover" />}
        <div className="mgtr-run-text">
          <div className="mgtr-run-name">{row.title}</div>
          <div className="mgtr-run-meta">{meta}</div>
          {f !== null && (
            <MoonGauge fraction={f} size={gaugeSize} className="mgtr-run-gauge"
              label={row.title + " training progress"} />
          )}
        </div>
        {row.status === "done" && row.published && row.visibility === "private" && !phone ? (
          <button type="button" className="mgtr-pill emerald link" title="Make it public…"
            onClick={() => onAction("make-public", row)}>{s.label}</button>
        ) : (
          <span className={"mgtr-pill " + s.tone} title={row.reason || ""}>{s.label}</span>
        )}
        {s.action && (
          <button type="button" className={primary ? "mgtr-run-act primary" : "mgtr-run-act"}
            onClick={() => act(s.action)}>
            {s.action === "retry" ? "Retry" : s.actionLabel}
          </button>
        )}
      </div>
      {row.reason && phone && <div className="mgtr-run-reason">{row.reason}</div>}
      {phone && row.status === "done" && row.published && row.visibility === "private" && (
        <button type="button" className="mgtr-run-link" onClick={() => onAction("make-public", row)}>
          Make it public…</button>
      )}
      {open && (
        <div className="mgtr-run-detail">
          {row.status === "waiting" ? "Waiting for a free GPU. You can close this."
            : f !== null ? "Training now: " + Math.floor(f * 100) + "%" + (row.eta_left_ms ? ", " + etaLeftText(row.eta_left_ms) + " to go" : "") + ". You can close this."
              : "Training now. PixAI hasn't reported a percentage yet."}
          <span className="mgtr-mono"> · run {row.id}</span>
        </div>
      )}
    </div>
  );
}

export default function RunsList({ runs, filter, setFilter, onAction, phone = false }) {
  const rows = runs || [];
  const count = (k) => rows.filter((r) => runMatches(r, k)).length;
  const shown = rows.filter((r) => runMatches(r, filter));
  return (
    <div className="mgtr-runs">
      <div className="mgtr-runs-filters" role="tablist">
        {RUN_FILTERS.map((f) => (
          <button type="button" key={f.key} role="tab" aria-selected={filter === f.key}
            className={"mgtr-chip" + (filter === f.key ? " on" : "")} onClick={() => setFilter(f.key)}>
            {f.label}{f.key !== "all" ? " " + count(f.key) : ""}
          </button>
        ))}
      </div>
      {!shown.length && (
        <div className="mgtr-dim mgtr-runs-empty">
          {rows.length ? "Nothing here." : "Nothing here yet. A run you start shows up until it finishes, and stays once it has."}
        </div>
      )}
      {shown.map((r) => (
        <RunRow key={r.mode + r.id} row={r} onAction={onAction} phone={phone}
          gaugeSize={phone ? GAUGE_SIZES.phone : GAUGE_SIZES.runs} />
      ))}
    </div>
  );
}

/* The retry confirm (PAID, a new run): PixAI's quote, the amount ticked, then Retry. */
export function RetryConfirm({ retry }) {
  const a = retry.ask;
  if (!a) return null;
  return (
    <div className="mgtr-confirm">
      <div className="t">Retry {a.row.title} on PixAI?</div>
      <div className="b">
        A retry is a new run: the same set and descriptions, charged again at PixAI's price today.
        {!a.is_free && (
          <label className="mgtr-accept">
            <input type="checkbox" checked={retry.accepted} onChange={(e) => retry.setAccepted(e.target.checked)} />
            <span>Spend {credits(a.price)} credits on this retry.</span>
          </label>
        )}
      </div>
      {retry.err && <div className="mgtr-err">⚠ {retry.err}</div>}
      <div className="a">
        <button type="button" className="mgtr-ghost" onClick={() => retry.setAsk(null)} disabled={retry.busy}>Back</button>
        <button type="button" className="mgtr-go" disabled={retry.busy || (!a.is_free && !retry.accepted)}
          onClick={retry.confirm}>{retry.busy ? "starting…" : startLabel(a, "Retry")}</button>
      </div>
    </div>
  );
}
