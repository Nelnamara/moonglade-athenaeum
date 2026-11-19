import React, { useEffect, useRef, useState } from "react";
import Icon from "../icons/Icons.jsx";
import JobResultBox from "./JobResultBox.jsx";
import BrokenFiles from "./BrokenFiles.jsx";
import { ActionChip, JobRunning } from "./JobConsole.jsx";
import useHealth, { fmt, lastVerified } from "../hooks/useHealth.js";
import useBrokenFiles from "../hooks/useBrokenFiles.js";
import { DEDUP_STAGES } from "../hooks/useControlPanel.js";
import { fixPlan } from "../lib/brokenFilesCore.js";
import { subscribeBrokenFilesIntent, takeBrokenFilesIntent } from "../lib/brokenFilesNav.js";
import { onRunEnd } from "../lib/brokenFixRun.js";

/* THE TIDY TAB -- One Tidy place (owner pick 2026-11-19, round 2 option B; pixel source
   moonglade-internal/design/board/LOOK_BOARD_2026-11-19_round2.html, topic 5, option B).

   Duplicates, stray files and broken files used to live in three places: Health's Duplicate
   Review and Broken files list, the Panel's five-step Dedup chain beside "Organize into month
   folders", and "Verify library integrity" under Check. They are one tab now, one column per
   job, each with its count and its buttons, exactly as the board draws it.

   NOTHING DESTRUCTIVE GOT EASIER. Every button but one is a job or a route the app already
   had:
     Duplicates  Find = Audit then Preview (both read-only, useControlPanel's runFind);
                 Review = the one Duplicate Review (keep one in each group, move the rest to
                 _duplicates/, Undo per group), opened over the Panel;
                 then Move all to _duplicates/ (only after Find), Check _duplicates/ (read-only,
                 any time), and the road's last step, Empty _duplicates/ (2026-11-19, the one
                 new job): only straight after a Check that found every file safe, its confirm
                 naming the count and size, to the Recycle Bin -- and the CLI command behind
                 it re-checks everything itself (moonglade/organize.py, cmd_empty_duplicates).
                 Apart from the road, Delete library copies outright keeps the chain's own gate
                 (DEDUP_STAGES / dedupDone: Find, Move all and Check, in order).
     Stray files Organize's Preview, Move and Undo.
     Broken      Fix all (the Broken files list's own one confirm) and Check (the integrity
                 pass, read-only); the list itself sits under the columns.
   A job that changes files arms first ("Confirm — ...") and runs only for a session on the
   serving machine: summary.actions carries a destructive action only for a local session, so
   ActionChip draws nothing on the LAN, and the server refuses it there anyway. READ_ONLY
   refuses Duplicate Review's moves and a re-download server-side, as it always has.

   The counts are Health's own (/api/health, useHealth), re-read when a job here finishes,
   when Duplicate Review moved something, and when a fix run ends. */

const stageIndex = (key) => DEDUP_STAGES.findIndex((s) => s.key === key);

export default function TidyTab({
  isLocal, actionSpec, runAction, runFind, confirmArm, dedupDone, organizeRes,
  running, progress, log, jobResult, setJobResult, jobError, stopJob, actions,
  changed = 0, onOpenReview, onOpenDetails, emptyReady = null, clearEmptyReady,
}) {
  // Duplicate Review moved or restored something: the last Check no longer describes
  // _duplicates/, so Empty closes until the next one.
  useEffect(() => { if (changed && clearEmptyReady) clearEmptyReady(); }, [changed]);   // eslint-disable-line react-hooks/exhaustive-deps
  // Re-read the counts after anything here changed the library.
  const [rev, setRev] = useState(0);
  const wasRunning = useRef(!!running);
  useEffect(() => {
    if (wasRunning.current && !running) setRev((n) => n + 1);
    wasRunning.current = !!running;
  }, [running]);
  useEffect(() => { if (changed) setRev((n) => n + 1); }, [changed]);
  useEffect(() => onRunEnd(() => setRev((n) => n + 1)), []);
  const { h } = useHealth(rev);

  /* Broken files: the list, its chip, and the doors into it (Health's problem tiles, a fix
     run's Activity row: lib/brokenFilesNav.js, on mount or live). */
  const bf = useBrokenFiles();
  const [chip, setChip] = useState("all");
  const [asking, setAsking] = useState(false);
  const listRef = useRef(null);
  const [go, setGo] = useState(() => takeBrokenFilesIntent());
  useEffect(() => subscribeBrokenFilesIntent(() => setGo(takeBrokenFilesIntent())), []);
  const counts = bf.doc && bf.doc.counts;
  const listShown = !!(counts && counts.all > 0);
  useEffect(() => {
    if (!go || !listShown) return;
    setChip(counts[go] > 0 ? go : "all");
    const el = listRef.current;
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "start" });
    setGo(null);
  }, [go, listShown]);   // eslint-disable-line react-hooks/exhaustive-deps
  const plan = fixPlan(bf.doc, bf.readOnly, bf.done);
  const fixAll = () => {
    if (!plan.total || bf.running) return;
    setAsking(true);
    const el = listRef.current;
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const busy = !!running;
  // A chain step: the same order gate the Dedup chain always had (useControlPanel's runAction
  // refuses an out-of-order stage too -- this only greys the button).
  const step = (key, label, opts = {}) => {
    const i = stageIndex(key);
    const early = i > dedupDone;
    return (
      <ActionChip spec={actionSpec(key)} label={label} locked={!!opts.locked}
        armed={confirmArm === key} onRun={() => runAction(key)} disabled={busy || early}
        title={early ? opts.early : (actionSpec(key) || {}).label} />
    );
  };

  const stray = h && h.per_bucket
    ? (h.per_bucket.images || 0) + (h.per_bucket.batches || 0) : null;

  return (
    <div className="mgcp-tidy">
      {running ? (
        <div className="mgcp-console">
          <JobRunning running={running} progress={progress} log={log} actions={actions} onStop={stopJob} />
        </div>
      ) : jobResult ? (
        <JobResultBox jobResult={jobResult} onDismiss={() => setJobResult(null)} />
      ) : null}
      {jobError && <div className="mgcp-runerr">{jobError}</div>}

      <div className="mgcp-tidycols">
        <section className="mgcp-tidycol" aria-label="Duplicates">
          <div className="mgcp-mkick">Duplicates</div>
          <div className="mgcp-tidynum">{h ? fmt(h.dup_redundant) : "—"}</div>
          <div className="mgcp-tidysub">{(h && h.dup_bytes_h) || "—"}</div>
          <div className="mgcp-chips mgcp-tidychips">
            {actionSpec("audit") && (
              <button type="button" className="mgcp-chip" onClick={runFind} disabled={busy}
                title="Audit and Preview together. Read-only: nothing moves.">Find</button>
            )}
            <button type="button" className="mgcp-chip" onClick={onOpenReview}
              title="Keep one in each group; the rest move to _duplicates/, with Undo">Review</button>
          </div>
          <div className="mgcp-tidythen">
            <div className="mgcp-tidythenlbl">then</div>
            <div className="mgcp-chips">
              {step("dedup-apply", "Move all to _duplicates/", { locked: true, early: "Run Find first" })}
              <ActionChip spec={actionSpec("verify-dupes")} label="Check _duplicates/" disabled={busy}
                title="Is every file in _duplicates/ the same as a copy kept in the library? Read-only."
                armed={confirmArm === "verify-dupes"} onRun={() => runAction("verify-dupes")} />
              {/* The road's last step. Open only straight after a Check that found every file
                  safe; the confirm says how many files and how much. */}
              <ActionChip spec={actionSpec("empty-dupes")} locked disabled={busy || !emptyReady}
                label={confirmArm === "empty-dupes" && emptyReady
                  ? "send " + emptyReady.count + " file" + (emptyReady.count === "1" ? "" : "s")
                    + " (" + emptyReady.size + ") to the Recycle Bin"
                  : "Empty _duplicates/"}
                title={emptyReady
                  ? "Send the " + emptyReady.count + " checked files (" + emptyReady.size + ") to the Recycle Bin"
                  : "Run Check _duplicates/ first: it must find every file safe"}
                armed={confirmArm === "empty-dupes"} onRun={() => runAction("empty-dupes")} />
            </div>
          </div>
          {/* Not part of the road: it deletes duplicate copies IN THE LIBRARY, never _duplicates/,
              with no safety net -- so it keeps the chain's own gate (Find, Move all, Check). */}
          <div className="mgcp-tidythen">
            <div className="mgcp-tidythenlbl">or, with no _duplicates/ safety net</div>
            <div className="mgcp-chips">
              {step("dedup-delete", "Delete library copies outright", { locked: true,
                early: "Run Find, Move all and Check first" })}
            </div>
          </div>
        </section>

        <section className="mgcp-tidycol" aria-label="Stray files">
          <div className="mgcp-mkick">Stray files</div>
          <div className="mgcp-tidynum">{stray == null ? "—" : fmt(stray)}</div>
          {/* After a Preview, what it found (useControlPanel's organizeRes, read off
              cmd_organize's own plan line); before one, what the count is. */}
          <div className="mgcp-tidysub">{organizeRes || "not in a month folder"}</div>
          <div className="mgcp-chips mgcp-tidychips">
            <ActionChip spec={actionSpec("organize-dry")} label="Preview" disabled={busy}
              armed={confirmArm === "organize-dry"} onRun={() => runAction("organize-dry")} />
            <ActionChip spec={actionSpec("organize")} dgr label="Move" disabled={busy}
              title="Organize into month folders (writes an undo manifest)"
              armed={confirmArm === "organize"} onRun={() => runAction("organize")} />
            <ActionChip spec={actionSpec("undo-organize")} dgr label="Undo" disabled={busy}
              armed={confirmArm === "undo-organize"} onRun={() => runAction("undo-organize")} />
          </div>
        </section>

        <section className="mgcp-tidycol" aria-label="Broken files">
          <div className="mgcp-mkick">Broken</div>
          <div className="mgcp-tidynum">{counts ? fmt(counts.all || 0) : "—"}</div>
          <div className="mgcp-tidysub">
            {counts ? plan.total + " recoverable" : "not checked yet"}
          </div>
          <div className="mgcp-chips mgcp-tidychips">
            {plan.total > 0 && (
              <button type="button" className="mgcp-chip" onClick={fixAll} disabled={bf.running}>Fix all</button>
            )}
            <ActionChip spec={actionSpec("verify-library")} label="Check" disabled={busy}
              title="Verify library integrity (read-only)"
              armed={confirmArm === "verify-library"} onRun={() => runAction("verify-library")} />
          </div>
          <div className="mgcp-tidynote">last checked {lastVerified(bf.doc && bf.doc.verified_at ? bf.doc : h && h.integrity)}</div>
        </section>
      </div>

      {!isLocal && (
        <div className="mgcp-footnote">
          <span><Icon name="lock" /> moving and deleting files: serving machine only</span>
        </div>
      )}

      {listShown ? (
        <BrokenFiles bf={bf} chip={chip} setChip={setChip} sectionRef={listRef}
          onOpenDetails={onOpenDetails} asking={asking} setAsking={setAsking} />
      ) : null}
    </div>
  );
}
