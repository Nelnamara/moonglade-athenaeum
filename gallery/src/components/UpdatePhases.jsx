import React from "react";

/* UpdatePhases -- the apply flow's three phases, its meter and its hold line, lifted out of
   ControlPanelOverlay.jsx's UpdateModal on 2026-09-07 so the phone's Control tab can show
   the SAME running card rather than a second drawing of it (owner ruling that day: "phone
   gets update"). Same markup, same classes, same tokens: the desktop modal renders exactly
   what it rendered before this file existed, and the Identity Chrome C2 handoff still owns
   every pixel of it.

   The three phases advance on the server's REAL transitions (hooks/useControlPanel.js's
   applyUpdate polls /api/update/status; each finished phase is stamped with the time it
   actually took), and the meter is a function of how many have finished -- there is no timed
   animation pretending to know how long a pull takes.

   This file DRAWS the apply; it cannot start one. `steps`, `phase` and `refusal` all come
   from the hook, and the one POST to /api/update/apply stays in hooks/useControlPanel.js. */

/* A refusal replaces the METER, not the surface, in one of exactly three presentations the
   handoff draws: offline gray, busy gold, failed ruby. All three are tokens. The failed one
   keeps the tool's VERBATIM words (git's or pip's), which is the thing that actually tells
   you the fix. */
export const UPD_PHASE_HINT = {
  offline: "nothing was touched",
  busy: "nothing was touched — try again in a moment",
  failed: "nothing was touched",
};

/* The plain account of what "Update now" will do to a server you are using -- shown before
   the confirm on both surfaces, from one list so the two can never drift apart. */
export const UPDATE_WHAT = [
  "The update is pulled atomically — if it can't apply cleanly, nothing changes.",
  "Dependencies are installed only if they changed in this release.",
  "The server restarts. This tab reloads itself when it is back.",
];

export function UpdateRefusal({ refusal }) {
  return (
    <div className={"mgcp-updrefusal " + refusal.kind}>
      <span className="mgcp-updrefusal-kind">{refusal.kind}</span>
      <span className="mgcp-updrefusal-line">{refusal.line}</span>
      <span className="mgcp-updrefusal-note">{UPD_PHASE_HINT[refusal.kind]}</span>
    </div>
  );
}

export default function UpdatePhases({ steps, phase }) {
  const doneCount = (steps || []).filter((s) => s.state === "done").length;
  return (
    <>
      <ol className="mgcp-updphases">
        {(steps || []).map((s) => (
          <li key={s.key} className={"mgcp-updphase " + s.state}>
            <span className="mgcp-updphase-dot" aria-hidden="true">
              {s.state === "done" ? "✓" : s.state === "now" ? <i /> : null}
            </span>
            <span className="mgcp-updphase-lab">{s.label}</span>
            <span className="mgcp-updphase-t">
              {s.state === "done"
                ? (s.note || (s.secs != null ? s.secs.toFixed(1) + "s" : "done"))
                : s.state === "now" ? "now" : s.note}
            </span>
          </li>
        ))}
      </ol>
      {/* The meter is the phase count, not a clock: it can only move when a phase
          really finishes. CSS eases the width change so it reads as motion. */}
      <div className="mgcp-updmeter">
        <i style={{ width: [8, 38, 72, 100][doneCount] + "%" }} />
      </div>
      <div className="mgcp-updhold">
        {phase === "done" ? "done · reloading into the new version"
          : "do not close · resumes on its own"}
      </div>
    </>
  );
}
