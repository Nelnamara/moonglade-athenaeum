import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { invalidate, peek, put } from "./swrCache.js";

/* Control Panel's own fetch/poll/action/power data layer, mechanically lifted out of
   ControlPanelOverlay.jsx (2026-08-03) into its own hook -- summary/achievements fetch,
   the job console's run/poll/cancel machinery, "recover a task by id", and the real
   Stop/Restart ping-poll flow. A byte-for-byte copy of that same logic, not a rewrite of
   it, following the EXACT precedent useLibrary.js set for App.jsx (see docs/DECISIONS.md
   2026-08-03, "App.jsx's browse/search/filter/sort/paginate logic gets refactored to
   consume its own extracted hook, not left as a divergent duplicate"): ControlPanelOverlay
   is the ONE place this state has ever lived, so it gets refactored to CONSUME this hook
   rather than left holding a second copy -- and the new mobile Control tab (ControlMobile.jsx)
   consumes the exact same hook instance-per-mount, never a reimplementation of its own.

   What deliberately did NOT move here, and why:
   - `tab` (Maintenance/Branding) and `subOverlay` (Users/Trash) -- which TOP-LEVEL section
     or sub-overlay is showing is a presentation decision each consumer makes its own way
     (desktop: two tabs in one modal; mobile: Branding is its own MobileScreen push, Trash/
     Accounts are the same UsersSubOverlay/TrashSubOverlay dialogs reused as-is). Neither
     consumer's data needs the other's notion of "which panel is currently visible".
   - The Escape-key listener -- it closes whatever the TOP layer is (sub-overlay, then the
     whole panel), which only makes sense against a component's own `onClose`/`subOverlay`
     pairing; ControlPanelOverlay.jsx keeps its own copy, matching MobileScreen.jsx's own
     documented choice to skip Escape handling entirely for the mobile push-chrome pattern.
   - `boot` (mark_url/build_stamp) -- purely rendered in the desktop modal's own header
     chrome, never read by any fetch/poll/action logic, so it was never a hook input.

   OUTER-TAB-SWITCH SAFETY (checked explicitly per docs/DECISIONS.md's 2026-08-03 entry,
   which names this exact console as the next surface to verify): unlike the Create tab's
   <mg-generate-drawer> -- whose disconnectedCallback actively SWEEPS every poll timer with
   no way back, forcing that element to never conditionally unmount -- a maintenance job
   here keeps running server-side with "no browser tab involved" (see the mount-effect
   comment below, ported verbatim from the original file). Unmounting ControlMobile just
   clears a local setInterval; nothing server-side stops or loses track of the job. Every
   fresh mount of THIS hook re-fetches /api/panel/status and rebuilds `running`/`progress`/
   `log` from that server truth, so switching the bottom-nav tab away from Control and back
   resumes tracking correctly instead of silently losing it -- a different, but equally
   real, fix for the same class of bug, not an oversight. (One disclosed gap this does NOT
   cover, pre-existing on desktop too, not introduced by this port: if a job both starts AND
   finishes entirely while unmounted, the mount check only asks "is one running right now" --
   it does not retroactively show the finished job's own jobResult/jobError banner, so a
   job that completed while the tab was away renders as a plain idle console on return, not
   silently mistracked, just not retroactively narrated.) The Stop/Restart ping-poll (`power`)
   has NO equivalent resume-on-mount check on either surface -- a pre-existing gap, not
   introduced here, and not fixed in this pass (no server-side "restart in progress" signal
   exists to resume FROM; /api/ping only answers up/down, it can't distinguish "mid-restart"
   from "briefly slow" on a fresh mount). Not a billing/credit risk either way: the POST that
   starts it fires once, before any unmount could happen, and there is no retry-on-remount
   path that could double-fire it. */

const POLL_MS = 1200;
const PING_MS = 800;
const PING_TRIES_MAX = 50;

// Ported verbatim from ControlPanelOverlay.jsx's own DEDUP_STAGES -- the Tend section's
// dedup pipeline order, shared so a second, drifting copy never has to exist.
export const DEDUP_STAGES = [
  { key: "audit", label: "Audit" },
  { key: "dedup-dry", label: "Preview" },
  { key: "dedup-apply", label: "Quarantine 🔒" },
  { key: "verify-dupes", label: "Verify" },
  { key: "dedup-delete", label: "Delete 🔒" },
];

// Applies a skin app-wide, not just inside whichever component called this -- classic's
// pickSkin() and the notify module's applySkin (gallery/src/notify/ach.js) both write the SAME pair
// (html[data-skin], localStorage['skin']) after a successful POST, since every skin rule
// in the suite's CSS reads off that attribute, and the pre-paint inline script on next
// load reads localStorage first. Missing this meant picking a skin here changed nothing
// visible anywhere outside the clicked card's own checkmark.
async function applySkin(id, achievements, setAchievements) {
  const d = await apiPost("/api/skin", { skin: id });
  if (d.error) return d;
  const next = { ...achievements, skin: id };
  setAchievements(next);
  // The roster the Folio and the Panel share now says a different skin is active; write the
  // mutated copy through rather than leaving the cache to hand the OLD one to the next open.
  // Only when there WAS a roster: a spread of null is {skin}, and seeding the Folio from
  // that stub would be worse than not caching at all.
  if (achievements) put("/api/achievements", next);
  if (id === "moonglade") document.documentElement.removeAttribute("data-skin");
  else document.documentElement.setAttribute("data-skin", id);
  try { localStorage.setItem("skin", id); } catch { /* private browsing etc -- cosmetic only */ }
  return d;
}

export default function useControlPanel() {
  /* THE FOUR OPEN-TIME READS ARE SEEDED FROM THE SHARED CACHE (hooks/swrCache.js), so a
     reopened Panel paints its summary, its skins, its run history and its standing order in
     the first frame and refreshes them behind. /api/panel/status is deliberately NOT among
     them and never will be: it is the live-job resume check, and "is a job running RIGHT
     NOW" is the one question a stale answer gets wrong.

     ONE DISCLOSED CONSEQUENCE, checked rather than assumed: a SEEDED `summary` carries no
     csrf, because the cache refuses to store one (swrStore.js's second refusal). Four
     things read summary.csrf -- the Users sub-overlay's add/remove/change/reset -- plus the
     updater's apply. Every one of them is behind opening a sub-overlay or a confirm modal
     and typing into it, which cannot happen before fetchSummary() below lands (milliseconds
     after mount) and replaces the seed with the live object, token included. If one somehow
     did, the server refuses it and the surface shows that refusal; nothing spends and
     nothing is silently mis-recorded. */
  const [summary, setSummary] = useState(() => peek("/api/panel/summary"));
  const [achievements, setAchievements] = useState(() => peek("/api/achievements"));
  const [summaryErr, setSummaryErr] = useState("");
  const [panelHistory, setPanelHistory] = useState(() => (peek("/api/jobs.panel") || {}).rows || []);
  const [schedule, setSchedule] = useState(() => peek("/api/panel/schedule"));

  const [running, setRunning] = useState(null); // {action, label}
  const [progress, setProgress] = useState(null);
  const [log, setLog] = useState([]);
  const [jobError, setJobError] = useState("");
  const [jobResult, setJobResult] = useState(null); // last completed job's own tail, kept visible until the next run
  // Control Panel.dc.html:117's {{ organizeRes }} chip, between Preview and Apply --
  // parsed from cmd_organize()'s own real stdout line (moonglade_backup.py, "Organize
  // plan: N file(s) -> YYYY-MM/..."), not fabricated. `jobResult.lines` alone can't
  // supply this: it's trimmed to the tail 6 lines for the log view, and the plan-count
  // line is near the TOP of organize-dry's output (ahead of the per-file preview rows),
  // so this is parsed from the job's full, untrimmed line list in tick() instead.
  const [organizeRes, setOrganizeRes] = useState(null);
  const [confirmArm, setConfirmArm] = useState(null); // action key awaiting inline confirm
  const [testPullN, setTestPullN] = useState(20);
  const pollRef = useRef(null);
  const runningKeyRef = useRef(null); // the action key tick() is currently polling for --
  // a ref (not `running` state) because runAction() sets this synchronously before the
  // interval is ever created, avoiding the stale-closure trap `tick`'s own closure over
  // `running` would otherwise hit (setRunning triggers a re-render; the specific `tick`
  // function instance handed to setInterval was created during THIS render, before that
  // re-render happens, so its own closed-over `running` would still read null).

  // Dedup stage sequential gating (Control Panel.dc.html:637-641, `dedupDone`/`st.onRun`'s
  // `i <= s.dedupDone` check) -- session-local, matching the design's own `dedupDone: 0`
  // in-memory-only state (never persisted there either, confirmed at design line 508). NOT
  // the same gap as the disclosed "no run-history persisted" one above: this doesn't need
  // to survive a reload, it only needs to survive within one open Panel session, exactly
  // like the design's own state does.
  const [dedupDone, setDedupDone] = useState(0);

  const [taskId, setTaskIdRaw] = useState("");
  const [taskState, setTaskState] = useState(null); // 'running' | 'done' | {error}

  const [power, setPower] = useState(null); // 'restart' | 'stop'
  const [powerConfirm, setPowerConfirm] = useState(null); // mode awaiting a first click before it actually fires
  const [powerPhase, setPowerPhase] = useState("busy"); // 'busy' | 'done' | 'failed'
  const [powerErr, setPowerErr] = useState("");
  const pingRef = useRef(null);
  const powerCancelledRef = useRef(false);

  const fetchSummary = async () => {
    try {
      const d = await apiGet("/api/panel/summary");
      if (d.error) throw new Error(d.error);
      put("/api/panel/summary", d);
      setSummary(d);
      setSummaryErr("");
    } catch {
      // Same rule the shared cache applies everywhere: an error only surfaces when there is
      // nothing cached to keep showing.
      if (peek("/api/panel/summary") == null) {
        setSummaryErr("Couldn't load the Panel — network error, try reopening it.");
      }
    }
  };
  // ---- Run-history ledger + the standing order (Control Panel.dc.html:157-181) ----
  // History is the REAL jobs.jsonl paper trail filtered to type:"panel" -- the same
  // /api/jobs feed the Activity card already polls, not a second bespoke store. The
  // schedule is /api/panel/schedule's real persisted settings (GET login-tier;
  // writes are localhost-only server-side, so saveSchedule surfaces the 403 as its
  // error string rather than pretending a LAN toggle stuck).
  const fetchPanelHistory = async () => {
    try {
      const d = await apiGet("/api/jobs");
      const rows = (d.jobs || []).filter((j) => j.type === "panel" && !j.dismissed);
      // Cached under a DERIVED key ("/api/jobs.panel", never "/api/jobs"): what is stored is
      // this hook's filtered panel-only view, not the raw feed the Activity tray reads, so
      // the two can never be handed each other's rows.
      put("/api/jobs.panel", { rows });
      setPanelHistory(rows);
    } catch { /* the ledger view just renders empty -- non-critical */ }
  };
  const fetchSchedule = async () => {
    try {
      const d = await apiGet("/api/panel/schedule");
      if (!d.error) { put("/api/panel/schedule", d); setSchedule(d); }
    } catch { /* standing-order row stays hidden -- non-critical */ }
  };
  const saveSchedule = async (patch) => {
    const d = await apiPost("/api/panel/schedule", patch);
    if (!d.error) { put("/api/panel/schedule", d); setSchedule(d); }
    return d;
  };
  const fetchAchievements = async () => {
    try {
      const d = await apiGet("/api/achievements");
      if (!d.error) { put("/api/achievements", d); setAchievements(d); }
    } catch { /* Skins sections just stay hidden without this — non-critical */ }
  };

  useEffect(() => {
    fetchSummary();
    fetchAchievements();
    fetchPanelHistory();
    fetchSchedule();
    // A job can already be running when this mounts -- the scheduler fires its own sync
    // on a timer with no browser tab involved, or another tab/session started one. Without
    // this check the console renders the idle grid as if nothing were happening, and
    // clicking a button just gets back a 409 with no progress ever shown. This is also
    // exactly what makes it safe for a mobile consumer to unmount/remount on every bottom-
    // nav tab switch (see this file's header comment's "OUTER-TAB-SWITCH SAFETY" section).
    (async () => {
      try {
        const d = await apiGet("/api/panel/status");
        if (d.status === "running") {
          runningKeyRef.current = d.action;
          setRunning({ action: d.action, label: d.label || d.action });
          setProgress(d.progress || null);
          setLog(d.lines || []);
          pollRef.current = setInterval(tick, POLL_MS);
        }
      } catch { /* fall through to idle -- the next real click still works */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (pingRef.current) clearInterval(pingRef.current);
  }, []);

  // The LOCALITY-FILTERED list (matching classic's own /panel: panel_visible actions,
  // destructive ones ONLY for a local session) -- summary.all_actions exists purely to
  // feed a scheduler dropdown neither consumer has, and using it here would render every
  // destructive Maintenance button live for a LAN session, which then 403s on the real
  // confirm click. The Trash/Users/Branding localhost-only controls already gate on
  // isLocal directly; this is that same rule for the Maintenance job console.
  const actionSpec = (key) => (summary?.actions || []).find((a) => a.action === key);

  const tick = async () => {
    let d;
    try {
      d = await apiGet("/api/panel/status");
      if (d.error) return;
    } catch { return; }
    if (d.status === "running") {
      setProgress(d.progress || null);
      setLog(d.lines || []);
      return;
    }
    clearInterval(pollRef.current); pollRef.current = null;
    setRunning(null);
    const finishedKey = runningKeyRef.current;
    runningKeyRef.current = null;
    const lines = d.lines || [];
    if (d.status === "failed") {
      const rc = d.rc != null ? " (exit " + d.rc + ")" : "";
      if (lines.length === 1 && String(lines[0]).indexOf("only on the server") !== -1) {
        setJobError("Job failed" + rc + " — open Moonglade on the server itself to see why.");
      } else {
        const tail = lines.slice(-3).filter(Boolean);
        setJobError(tail.length ? "Job failed" + rc + ": " + tail.join(" · ")
                                : "Job failed" + rc + " — it ended without printing a reason.");
      }
      setJobResult(null);
    } else {
      // done / done_with_errors / cancelled -- capture the job's own tail output so it
      // doesn't vanish the instant `running` flips false (the idle grid has no other
      // place left to show it), and call out done_with_errors + warn_count specifically
      // rather than folding it into an identical-looking "done".
      const tail = lines.slice(-6).filter(Boolean);
      setJobResult({
        ok: d.status !== "done_with_errors",
        warnCount: d.warn_count || 0,
        lines: tail,
      });
      if (finishedKey === "organize-dry") {
        const planLine = lines.find((ln) => /^Organize plan:/.test(ln));
        const m = planLine && planLine.match(/^Organize plan:\s*(\d+)\s*file/);
        setOrganizeRes(m ? m[1] + " would move" : (planLine || "checked"));
      }
      // Advance dedup gating only on a real, clean "done" -- not
      // done_with_errors or cancelled, so a partial/interrupted stage never
      // unlocks the next (possibly destructive) one on a false pretense.
      if (d.status === "done") {
        const idx = DEDUP_STAGES.findIndex((s) => s.key === finishedKey);
        if (idx !== -1) setDedupDone((prev) => Math.max(prev, idx + 1));
      }
      fetchSummary();
    }
    // A maintenance job that just finished moved the library under every OTHER surface's
    // cached answer -- the Health walk and the achievement roster most of all (a sync
    // collects new art, which is what earns things). Purge those two READ caches so the
    // next Health/Folio open re-reads instead of painting a pre-job snapshot; fetchSummary
    // above and fetchPanelHistory below refresh this hook's own two directly.
    invalidate(["/api/health", "/api/achievements", "/api/your-art", "/api/next/detail/"]);
    // Either branch: the run just wrote its terminal event to jobs.jsonl, so the
    // ledger has a new row to show (failed runs are ledger rows too, by design --
    // the DC colors them, it doesn't hide them).
    fetchPanelHistory();
  };

  const runAction = async (key, extra) => {
    if (running) return;
    const spec = actionSpec(key);
    if (!spec) return;
    // Explicit early-return guard, not just the button's disabled attribute
    // (same rule this app applies everywhere a real gate matters -- see
    // DuplicateReviewOverlay's resolveGroup for the precedent): a dedup
    // stage clicked out of order is refused here regardless of how it got
    // clicked.
    const dedupIdx = DEDUP_STAGES.findIndex((s) => s.key === key);
    if (dedupIdx !== -1 && dedupIdx > dedupDone) return;
    if (spec.destructive && confirmArm !== key) {
      setConfirmArm(key);
      return;
    }
    setConfirmArm(null);
    setJobError("");
    setJobResult(null);
    setProgress(null);
    setLog([]);
    if (key === "organize-dry") setOrganizeRes(null);
    runningKeyRef.current = key;
    const body = { action: key };
    if (spec.destructive) body.confirm = true;
    if (spec.int_param) body.n = extra != null ? extra : (spec.int_default || 1);
    const d = await apiPost("/api/panel/run", body);
    if (d.error) { runningKeyRef.current = null; setJobError(d.error); return; }
    setRunning({ action: key, label: d.label || spec.label || key });
    pollRef.current = setInterval(tick, POLL_MS);
    tick();
  };

  // /api/panel/cancel is LOCALHOST-only (docs/DECISIONS.md 2026-07-27: the button itself
  // stays visible to every session on purpose -- hiding it would move a security decision
  // into the UI -- but a LAN session's refusal must still be SEEN, not swallowed).
  const stopJob = async () => {
    const d = await apiPost("/api/panel/cancel", {});
    if (d && d.error) setJobError(d.error);
  };

  // Typing a new task id must invalidate whatever the PREVIOUS id's taskState was showing
  // (running/done/error) -- bundled here so both consumers get this for free from a plain
  // setTaskId(value) call, instead of each remembering to pair it with setTaskState(null).
  const setTaskId = (v) => { setTaskIdRaw(v); setTaskState(null); };

  const importTask = async () => {
    const id = taskId.trim();
    if (!id || taskState === "running") return;
    setTaskState("running");
    const d = await apiPost("/api/import-task", { task_id: id });
    if (d.error) { setTaskState({ error: d.error }); return; }
    setTaskState({ done: true, saved: d.saved, already: !!d.already, media_ids: d.media_ids });
    fetchSummary();
  };

  /* ---- the auto-updater (P4) --------------------------------------------------
     ON DEMAND, once per Panel open (owner ruling, 2026-09-01: no background tick
     anywhere). The server caches for its own TTL, so opening the Panel repeatedly
     costs GitHub nothing. A failed check answers behind:false with a reason and is
     simply not shown -- an offline machine gets a Panel, not an error. */
  const [update, setUpdate] = useState(null);      // the check payload
  const [updOpen, setUpdOpen] = useState(false);   // the confirm modal
  const [updPhase, setUpdPhase] = useState("");    // "" | applying | done | refused
  // The refusal currently replacing the meter: {kind: offline|busy|failed, line}. One of
  // exactly three presentations (Identity Chrome handoff C2) -- see classifyRefusal below.
  const [updRefusal, setUpdRefusal] = useState(null);
  // The three phases, in order, as the modal draws them. `state` is done|now|wait; `secs`
  // is a REAL measured duration once the phase has passed (never a decorative number), and
  // `note` carries the one case where a duration would lie (deps that never had to run).
  const [updSteps, setUpdSteps] = useState(null);
  const updPollRef = useRef(null);
  const updClockRef = useRef(null);   // {at, sawDeps} -- when the current phase started
  useEffect(() => {
    let dead = false;
    apiGet("/api/update/check").then((d) => { if (!dead && d && !d.error) setUpdate(d); });
    return () => {
      dead = true;
      if (updPollRef.current) clearInterval(updPollRef.current);
      if (pingRef.current) clearInterval(pingRef.current);
    };
  }, []);

  /* THE RESTART ESTIMATE, and why it is a memory rather than a constant: the third phase
     is the only one nobody can measure while it happens (the server is not answering, so
     there is nothing to ask). What CAN be honest is what this machine's own last restart
     actually took, so that is what is shown -- written on the way out of a successful
     apply, read on the way into the next one. With no memory yet it falls back to the ten
     seconds the modal's own "what will happen" list has always quoted. */
  const RESTART_MS_KEY = "mg_update_restart_ms";
  const lastRestartMs = () => {
    let v = 0;
    try { v = Number(localStorage.getItem(RESTART_MS_KEY)) || 0; } catch { v = 0; }
    return v > 500 && v < 600000 ? v : 10000;
  };
  const rememberRestartMs = (ms) => {
    if (!(ms > 500 && ms < 600000)) return;
    try { localStorage.setItem(RESTART_MS_KEY, String(Math.round(ms))); } catch { /* private mode */ }
  };

  const freshSteps = () => ([
    { key: "pull", label: "Pull " + ((update && update.latest) || "the release") + " from the mirror",
      state: "now", secs: null, note: "" },
    { key: "apply", label: "Applying files", state: "wait", secs: null, note: "" },
    { key: "restart", label: "Restart", state: "wait", secs: null,
      note: "~" + Math.round(lastRestartMs() / 1000) + "s" },
  ]);

  /* Advance the list to `key`, closing every step before it and stamping the one that just
     ended with the time it REALLY took (measured between the two transitions this client
     observed, not a figure the server invents). `key` of null closes all three.

     ONE HONEST LIMIT, stated rather than hidden: the transitions are seen by a 1.5s poll,
     so a duration is real to about a second and a half -- a 2.2s pull can print 3.0s. That
     is a measurement of something that happened, which is the property that matters here;
     the alternative on offer was a fixed animation that measures nothing at all. */
  const advanceSteps = (key, extra) => {
    const now = Date.now();
    const started = (updClockRef.current && updClockRef.current.at) || now;
    updClockRef.current = { at: now, sawDeps: !!(updClockRef.current && updClockRef.current.sawDeps) };
    setUpdSteps((prev) => {
      const steps = (prev || freshSteps()).map((s) => ({ ...s }));
      const idx = key == null ? steps.length : steps.findIndex((s) => s.key === key);
      for (let i = 0; i < steps.length; i++) {
        if (i < idx) {
          if (steps[i].state !== "done") {
            steps[i].state = "done";
            steps[i].secs = (now - started) / 1000;
          }
        } else if (i === idx) {
          steps[i].state = "now";
        }
      }
      // The one duration that would be a lie: with no dependency change the server goes
      // straight from pulling to restarting, so "Applying files" is measured at ~0s. Say
      // what actually happened instead of printing a stopwatch reading of nothing.
      const apply = steps.find((s) => s.key === "apply");
      if (apply && apply.state === "done" && !(extra && extra.sawDeps) && !updClockRef.current.sawDeps) {
        apply.secs = null;
        apply.note = "no new dependencies";
      }
      return steps;
    });
  };

  /* Which of the three presentations a refusal wears. The SERVER decides between busy and
     failed (its `kind`, added 2026-09-04) -- this never reads its prose. Offline is the
     one this side owns, because it is the case where no answer arrived at all: api.js
     turns a transport failure into "network error: ...", and that is not the server
     saying no, it is the server not being there. */
  const classifyRefusal = (d, fallback) => {
    if (!d) return { kind: "offline", line: "The mirror is dark — connect it before pulling an update." };
    const msg = d.error || fallback || "The update failed.";
    if (/^network error/i.test(msg)) {
      return { kind: "offline", line: "The mirror is dark — connect it before pulling an update." };
    }
    return { kind: d.kind === "busy" ? "busy" : "failed", line: msg };
  };

  /* Apply: one POST behind the modal's explicit yes, then WATCH. The server does the
     work off the panel-job slot and reports its phase; when it reaches `restarting` we
     hand over to the exact ping-watch the Restart chip uses -- the server is about to
     stop answering, so the update's own status route cannot be what tells us it worked.
     A failure keeps the tool's verbatim words: that text is the fix. */
  const applyUpdate = async () => {
    // The confirm MORPHS into the progress list in place (handoff C2): same modal, same
    // card, the buttons give way to three phases and one meter. Nothing new opens, and
    // nothing closes -- which is why the phases live in this hook's state rather than in a
    // second component that would have to be mounted over the first.
    setUpdPhase("applying"); setUpdRefusal(null);
    updClockRef.current = { at: Date.now(), sawDeps: false };
    setUpdSteps(freshSteps());
    const d = await apiPost("/api/update/apply",
                            { confirm: true, csrf: summary?.csrf || "" }).catch(() => null);
    if (!d || d.error) {
      // A refusal arriving here means the work never started: the meter must not have
      // moved at all, so the phase list is dropped rather than left frozen mid-pull.
      setUpdSteps(null);
      setUpdPhase("refused");
      setUpdRefusal(classifyRefusal(d, "Network error — try again."));
      return;
    }
    // THE HANDOVER, on any of three signals -- because the server is about to stop
    // answering and the status route cannot be what tells us it worked:
    //   1. it says "restarting" (the clean case; the server sleeps ~2s there so a poll
    //      at this cadence can actually see it);
    //   2. the poll stops connecting AFTER we saw real work -- that IS the restart, seen
    //      from the outside;
    //   3. it answers "idle" after having been busy -- a server that came back so fast
    //      its fresh process is already serving.
    // Only (1) was handled before, and only (1) is a timing assumption, which is exactly
    // why the happy path used to strand on "updating…".
    let sawWork = false;
    let sawDeps = false;
    const handover = () => {
      clearInterval(updPollRef.current);
      updPollRef.current = null;
      // Third phase begins here, and it is the one nobody can watch: the server is going
      // away. Its clock starts now so the ping-watch below can record what the restart
      // really took and hand the NEXT apply a true estimate instead of a guess.
      advanceSteps("restart", { sawDeps });
      const restartAt = Date.now();
      _watch(true, (msg) => { setUpdPhase("refused"); setUpdRefusal({ kind: "failed", line: msg }); },
             () => {
               rememberRestartMs(Date.now() - restartAt);
               // THE THIRD ✓. The modal closes itself and the sidebar's version stamp
               // updates -- and on this surface both of those ARE the reload: the bundle
               // still running is the code that was just replaced, so the only honest way
               // to show the new version stamp is to load the new build. The hold is what
               // makes the completed list legible before the page goes; the old
               // "Updated Moonglade — done" toast that used to be the receipt is retired
               // (notify/jobsStore.js), because this list is the receipt now.
               advanceSteps(null, { sawDeps });
               setUpdPhase("done");
               setTimeout(() => window.location.reload(), 900);
             });
    };
    updPollRef.current = setInterval(() => {
      apiGet("/api/update/status", null, { cache: "no-store" })
        .then((st) => {
          if (!st || st.error) { if (sawWork) handover(); return; }
          if (st.phase === "failed") {
            clearInterval(updPollRef.current);
            updPollRef.current = null;
            setUpdPhase("refused");
            setUpdRefusal({ kind: "failed", line: st.error || "The update failed." });
          } else if (st.phase === "restarting") {
            sawWork = true;
            handover();
          } else if (st.phase === "idle") {
            if (sawWork) handover();
          } else {
            sawWork = true;                                // pulling | deps
            // `deps` is the server saying the pull is finished and dependencies are
            // installing -- the real boundary between phase one and phase two. Without a
            // requirements change it never arrives at all, and the list says so rather
            // than timing an event that did not happen.
            if (st.phase === "deps" && !sawDeps) {
              sawDeps = true;
              if (updClockRef.current) updClockRef.current.sawDeps = true;
              advanceSteps("apply", { sawDeps: true });
            }
          }
        })
        .catch(() => { if (sawWork) handover(); });
    }, 1500);
  };
  const closeUpdate = () => {
    if (updPollRef.current) clearInterval(updPollRef.current);
    updPollRef.current = null;
    updClockRef.current = null;
    setUpdOpen(false); setUpdPhase(""); setUpdRefusal(null); setUpdSteps(null);
  };

  // Sidebar chips arm on the first click ("Confirm -- Restart?") and only actually fire
  // on the second -- classic gates the same actions behind window.confirm(); this is the
  // same inline-confirm language ActionChip already uses for destructive Maintenance
  // actions, reused here rather than a native browser dialog.
  const clickPower = (mode) => {
    if (powerConfirm === mode) { setPowerConfirm(null); startPower(mode); }
    else setPowerConfirm(mode);
  };
  const startPower = (mode) => {
    powerCancelledRef.current = false;
    setPower(mode); setPowerPhase("busy"); setPowerErr("");
  };
  const doPower = async () => {
    if (power === "stop") {
      const d = await apiPost("/api/server/stop", {}).catch(() => null);
      if (powerCancelledRef.current) return; // Cancel was clicked while this was in flight
      if (d && d.error) { setPowerErr(d.error); setPowerPhase("failed"); return; }
      _watch(false);
    } else {
      const d = await apiPost("/api/server/restart", {}).catch(() => null);
      if (powerCancelledRef.current) return;
      if (d && d.error) { setPowerErr(d.error); setPowerPhase("failed"); return; }
      _watch(true);
    }
  };
  // Ported verbatim from classic's own _watchServer() (moonglade_gallery.py) -- the REAL
  // mechanism the Stop/Restart reconnect overlay has used for a long time. Restart: poll
  // until it goes down, THEN comes back -> reload. Stop: poll until it stops answering.
  const _watch = (comeBack, onFail, onBack) => {
    let tries = 0, sawDown = false;
    // `onBack` exists for the same reason `onFail` does: the updater rides this same loop
    // while ITS modal is the one on screen, and "the server answered again" is the moment
    // that modal has to record (how long the restart took) and show (its third ✓) before
    // the page goes. Without it the reload fired from in here, mid-list, and the completed
    // phase list was never on screen for a single frame. The power modal passes nothing
    // and keeps the straight reload it has always had.
    const back = () => {
      clearInterval(pingRef.current);
      if (onBack) onBack();
      else window.location.reload();
    };
    pingRef.current = setInterval(() => {
      tries++;
      // A refused ping is a refused ping: a dropped connection AND an error status both mean
      // this server is not answering, which is the whole signal here. (It used to be only the
      // transport rejection -- a 5xx from a half-down server read as "still up".)
      apiGet("/api/ping", null, { cache: "no-store" }).then((d) => {
        const ok = !d.error;
        if (comeBack && ok && sawDown) { back(); return; }
        if (comeBack && ok && tries >= 8 && !sawDown) { back(); return; }
        if (!ok) {
          sawDown = true;
          if (!comeBack) { clearInterval(pingRef.current); setPowerPhase("done"); }
        }
      });
      if (tries > PING_TRIES_MAX) {
        clearInterval(pingRef.current);
        // `onFail` exists because the updater watches through this same loop while the
        // POWER modal is not on screen: without it, a timed-out update reported into an
        // invisible UI and the update modal sat on "updating…" telling the user nothing.
        const msg = "Still restarting… give it a moment, then refresh.";
        if (onFail) onFail(msg);
        else if (comeBack) { setPowerErr(msg); setPowerPhase("failed"); }
        else setPowerPhase("done");
      }
    }, PING_MS);
  };
  useEffect(() => { if (power) doPower(); /* eslint-disable-next-line */ }, [power]);
  const closePower = () => {
    powerCancelledRef.current = true;
    if (pingRef.current) clearInterval(pingRef.current);
    setPower(null); setPowerConfirm(null); setPowerPhase("busy"); setPowerErr("");
  };

  const skins = achievements?.skins || [];
  const activeSkin = achievements?.skin || "moonglade";
  const pickSkin = (id) => applySkin(id, achievements, setAchievements);

  // Control Panel.dc.html's own `underTheHood` editor prop (Branding tab
  // visibility) maps to a REAL, already-shipped hidden feat -- 'under-the-hood'
  // (moonglade_gallery.py's ACHIEVEMENTS, metric branding_custom_file) -- not a
  // UI-only toggle. Owner call, 2026-08-05: gate for real, since the DC itself
  // never had this code/achievement in context when it defaulted the prop to
  // always-visible. Achievements masks an unearned hidden feat's id to
  // "hidden-feat-N" (/api/achievements' own docstring), so this correctly reads
  // false until it's real -- no separate "is it hidden" check needed.
  const brandingUnlocked = (achievements?.achievements || []).some(
    (a) => a.id === "under-the-hood" && a.earned
  );

  return {
    summary, summaryErr, achievements, skins, activeSkin, pickSkin, brandingUnlocked,
    panelHistory, schedule, saveSchedule,
    fetchSummary, fetchAchievements, actionSpec,
    running, progress, log, jobError, jobResult, setJobResult, confirmArm, runAction, stopJob,
    dedupDone, organizeRes,
    testPullN, setTestPullN,
    taskId, setTaskId, taskState, importTask,
    power, powerConfirm, powerPhase, powerErr, clickPower, closePower,
    update, updOpen, setUpdOpen, updPhase, updRefusal, updSteps, applyUpdate, closeUpdate,
  };
}
