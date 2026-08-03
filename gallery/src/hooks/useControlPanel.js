import { useEffect, useRef, useState } from "react";

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

export async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

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
// pickSkin() and static/mg-notify.js's applySkin() both write the SAME pair
// (html[data-skin], localStorage['skin']) after a successful POST, since every skin rule
// in the suite's CSS reads off that attribute, and the pre-paint inline script on next
// load reads localStorage first. Missing this meant picking a skin here changed nothing
// visible anywhere outside the clicked card's own checkmark.
async function applySkin(id, achievements, setAchievements) {
  const d = await postJSON("/api/skin", { skin: id });
  if (d.error) return d;
  setAchievements({ ...achievements, skin: id });
  if (id === "moonglade") document.documentElement.removeAttribute("data-skin");
  else document.documentElement.setAttribute("data-skin", id);
  try { localStorage.setItem("skin", id); } catch { /* private browsing etc -- cosmetic only */ }
  return d;
}

export default function useControlPanel() {
  const [summary, setSummary] = useState(null);
  const [achievements, setAchievements] = useState(null);
  const [summaryErr, setSummaryErr] = useState("");

  const [running, setRunning] = useState(null); // {action, label}
  const [progress, setProgress] = useState(null);
  const [log, setLog] = useState([]);
  const [jobError, setJobError] = useState("");
  const [jobResult, setJobResult] = useState(null); // last completed job's own tail, kept visible until the next run
  const [confirmArm, setConfirmArm] = useState(null); // action key awaiting inline confirm
  const [testPullN, setTestPullN] = useState(20);
  const pollRef = useRef(null);

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
      const r = await fetch("/api/panel/summary");
      if (!r.ok) throw new Error();
      setSummary(await r.json());
      setSummaryErr("");
    } catch {
      setSummaryErr("Couldn't load the Panel — network error, try reopening it.");
    }
  };
  const fetchAchievements = async () => {
    try {
      const r = await fetch("/api/achievements");
      setAchievements(await r.json());
    } catch { /* Skins sections just stay hidden without this — non-critical */ }
  };

  useEffect(() => {
    fetchSummary();
    fetchAchievements();
    // A job can already be running when this mounts -- the scheduler fires its own sync
    // on a timer with no browser tab involved, or another tab/session started one. Without
    // this check the console renders the idle grid as if nothing were happening, and
    // clicking a button just gets back a 409 with no progress ever shown. This is also
    // exactly what makes it safe for a mobile consumer to unmount/remount on every bottom-
    // nav tab switch (see this file's header comment's "OUTER-TAB-SWITCH SAFETY" section).
    (async () => {
      try {
        const r = await fetch("/api/panel/status");
        const d = await r.json();
        if (d.status === "running") {
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
      const r = await fetch("/api/panel/status");
      d = await r.json();
    } catch { return; }
    if (d.status === "running") {
      setProgress(d.progress || null);
      setLog(d.lines || []);
      return;
    }
    clearInterval(pollRef.current); pollRef.current = null;
    setRunning(null);
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
      fetchSummary();
    }
  };

  const runAction = async (key, extra) => {
    if (running) return;
    const spec = actionSpec(key);
    if (!spec) return;
    if (spec.destructive && confirmArm !== key) {
      setConfirmArm(key);
      return;
    }
    setConfirmArm(null);
    setJobError("");
    setJobResult(null);
    setProgress(null);
    setLog([]);
    const body = { action: key };
    if (spec.destructive) body.confirm = true;
    if (spec.int_param) body.n = extra != null ? extra : (spec.int_default || 1);
    const d = await postJSON("/api/panel/run", body);
    if (d.error) { setJobError(d.error); return; }
    setRunning({ action: key, label: d.label || spec.label || key });
    pollRef.current = setInterval(tick, POLL_MS);
    tick();
  };

  // /api/panel/cancel is LOCALHOST-only (docs/DECISIONS.md 2026-07-27: the button itself
  // stays visible to every session on purpose -- hiding it would move a security decision
  // into the UI -- but a LAN session's refusal must still be SEEN, not swallowed).
  const stopJob = async () => {
    const d = await postJSON("/api/panel/cancel", {});
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
    const d = await postJSON("/api/import-task", { task_id: id });
    if (d.error) { setTaskState({ error: d.error }); return; }
    setTaskState({ done: true, saved: d.saved });
    fetchSummary();
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
      const d = await postJSON("/api/server/stop", {}).catch(() => null);
      if (powerCancelledRef.current) return; // Cancel was clicked while this was in flight
      if (d && d.error) { setPowerErr(d.error); setPowerPhase("failed"); return; }
      _watch(false);
    } else {
      const d = await postJSON("/api/server/restart", {}).catch(() => null);
      if (powerCancelledRef.current) return;
      if (d && d.error) { setPowerErr(d.error); setPowerPhase("failed"); return; }
      _watch(true);
    }
  };
  // Ported verbatim from classic's own _watchServer() (moonglade_gallery.py) -- the REAL
  // mechanism the Stop/Restart reconnect overlay has used for a long time. Restart: poll
  // until it goes down, THEN comes back -> reload. Stop: poll until it stops answering.
  const _watch = (comeBack) => {
    let tries = 0, sawDown = false;
    pingRef.current = setInterval(() => {
      tries++;
      fetch("/api/ping", { cache: "no-store" }).then((r) => r.ok).then((ok) => {
        if (comeBack && ok && sawDown) { clearInterval(pingRef.current); window.location.reload(); }
        if (comeBack && ok && tries >= 8 && !sawDown) { clearInterval(pingRef.current); window.location.reload(); }
      }).catch(() => {
        sawDown = true;
        if (!comeBack) { clearInterval(pingRef.current); setPowerPhase("done"); }
      });
      if (tries > PING_TRIES_MAX) {
        clearInterval(pingRef.current);
        if (comeBack) { setPowerErr("Still restarting… give it a moment, then refresh."); setPowerPhase("failed"); }
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

  return {
    summary, summaryErr, achievements, skins, activeSkin, pickSkin,
    fetchSummary, fetchAchievements, actionSpec,
    running, progress, log, jobError, jobResult, setJobResult, confirmArm, runAction, stopJob,
    testPullN, setTestPullN,
    taskId, setTaskId, taskState, importTask,
    power, powerConfirm, powerPhase, powerErr, clickPower, closePower,
  };
}
