import React from "react";

/* ActivityChip -- the header-docked trigger (Claude Design handoff 2026-08-09, drift item
   39): stacks up to 3 running jobs as small progress rings, "+N" past that, folded into ONE
   chip rather than a separate element (the one piece of the original multi-option exploration
   that survived into the shipped design). Idle state falls back to a quiet dot + text.

   Real generation jobs carry no percent (PixAI reports no progress on a running task -- see
   the queued/ETA copy elsewhere in this system) so their ring is INDETERMINATE (spinning,
   at-ring's own gen-spin animation). A job that DOES carry real total/done (a Panel job like
   sync counting files) gets a real static conic-gradient percent ring instead -- the
   distinction the design's own fake-data demo couldn't see, since its mock jobs all carried
   a fabricated startedAt/durMs pair no real generation job has. */

function ringPct(j) {
  if (j.status !== "running" || !j.total) return null;
  return Math.min(100, Math.round(((j.done || 0) / j.total) * 100));
}

export default function ActivityChip({ jobs, open, onToggle, title, max = 3 }) {
  const live = jobs.filter((j) => (j.status || "running") === "running");
  const hasLive = live.length > 0;
  const shown = live.slice(0, max);
  const overflow = live.length > max ? live.length - max : 0;

  return (
    <div
      className={"at-chip" + (hasLive ? " live" : "") + (open ? " open" : "")}
      onClick={onToggle} title={title || "Activity — recent jobs"}
      role="button" tabIndex={0} aria-haspopup="true" aria-expanded={open}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
    >
      {hasLive ? (
        <div className="at-stack">
          {shown.map((j, i) => {
            const pct = ringPct(j);
            return (
              <div
                key={j.job_id}
                className={"at-ministack" + (pct == null ? " indet" : "")}
                style={{
                  zIndex: max - i,
                  marginLeft: i ? -8 : 0,
                  background: pct == null ? undefined
                    : "conic-gradient(var(--accent) 0deg " + (pct * 3.6) + "deg, rgba(255,255,255,.16) " + (pct * 3.6) + "deg 360deg)",
                }}
              />
            );
          })}
          {overflow ? <div className="at-overflow">+{overflow}</div> : null}
        </div>
      ) : (
        <span className="at-dot" />
      )}
      <span className="at-chiptext">
        {hasLive
          ? live.length + (live.length === 1 ? " job" : " jobs") + " running"
          : "idle · nothing in the queue"}
      </span>
      <span className="at-caret">▾</span>
    </div>
  );
}
