import React, { useEffect, useRef, useState } from "react";
import "../styles/overlays.css";
import "../styles/control-panel.css";
import useControlPanel, { DEDUP_STAGES } from "../hooks/useControlPanel.js";
import { apiGet, apiPost, apiUpload } from "../api.js";
import GalleryPicker from "./GalleryPicker.jsx";
import useScrollLock from "../hooks/useScrollLock.js";
import AccountSubOverlay from "./AccountSubOverlay.jsx";

/* Control Panel -- design spec: Control Panel.dc.html. Ported as a MODAL, per the owner's
   live 2026-08-02 correction ("Control panel is now ALSO modal. no separate pages anymore")
   -- the DC file itself still says "the Panel is a page in the suite, not a floating
   window," which that correction supersedes. Content below is the DC's real spec (tabs,
   tiles, Users/Trash sub-overlays, power modal); only the container changed.

   Every action here is real, proven backend classic's own /panel page has driven for a
   long time -- confirmed by reading the actual route code before writing this component,
   not assumed: GET /api/panel/summary (new -- a JSON twin of /panel's own aggregation,
   nothing computed that route didn't already compute), POST /api/panel/run + polling
   /api/panel/status (the ~20 whitelisted PANEL_ACTIONS -- the same mechanism
   SetupWizard.jsx's sync phase already uses), /api/trash/*, /api/users/*, /api/branding(
   /shortcut), /api/achievements + /api/skin, /api/server/stop|restart, /api/import-task.

   TWO disclosed departures from the DC:
   - The job console's "ledger" (run history) and "checks" last-run timestamps are the
     DC's own in-memory demo state (`this.state.ledger`/`checks`) -- nothing in this app
     persists per-action run history. Dropped rather than fabricated; the idle console
     shows the real action list with no invented "last run" column.
   - The power modal's RESTART_STAGES (5 fake timed stages, "Draining running jobs...") are
     replaced with classic's own REAL mechanism (_watchServer() in moonglade_gallery.py):
     poll /api/ping until the server goes down then comes back (restart) or stops
     answering (stop), then reload -- the actual observable signal, not a fabricated
     progress bar with invented durations.
   The DC's Branding tab also specifies 5 image-upload slots (banners/mascots/rewards with
   crop + a "rotating source collection"); only "Icons & marks" is backed by a real route
   (/api/branding only stores mark + anim). The other four slots have no backend at all --
   not built, not stubbed, left out entirely rather than shipping dead UI.

   DATA LAYER (fetch/poll/action/power) lives in ../hooks/useControlPanel.js as of
   2026-08-03, extracted so the mobile Control tab (ControlMobile.jsx) can consume the
   IDENTICAL logic instead of a second, drifting copy -- see that hook's own header
   comment for the full "what moved, what didn't, and why" account, including the
   explicit outer-tab-switch job-polling safety check docs/DECISIONS.md's 2026-08-03
   entry asks every future Control/hamburger surface to make. ActionChip, SkinsRow,
   BrandingTab, UsersSubOverlay, TrashSubOverlay and PowerModal are exported (not just
   default-exported ControlPanelOverlay itself) for the exact same reason -- ControlMobile
   reuses these components verbatim rather than rebuilding equivalents. */

// Verbatim copy of ControlMobile.jsx's own helper (same tiny function, kept
// per-file rather than a new shared-utils module for one four-line helper --
// matches how small formatters already live alongside their own component
// elsewhere in this codebase).
function timeAgo(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h ago";
}

// Ledger timestamps -- Control Panel.dc.html:517's own "today 14:02" shape, extended
// with yesterday/date for real multi-day history the DC's demo data never had.
function fmtWhen(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const now = new Date();
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return "today " + hm;
  const yd = new Date(now); yd.setDate(now.getDate() - 1);
  if (d.toDateString() === yd.toDateString()) return "yesterday " + hm;
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + hm;
}

// One ledger row's result column, from the job's REAL terminal event fields
// (status/rc/error -- rc only exists on events written 2026-08-06+; older rows
// render without it rather than faking one).
function ledgerResult(j) {
  if (j.status === "failed") return { text: j.error || "failed", good: false };
  if (j.status === "done_with_errors")
    return { text: (j.error || "finished with warnings") + (j.rc != null ? " · rc " + j.rc : ""), good: false };
  if (j.status === "done") return { text: "done" + (j.rc != null ? " · rc " + j.rc : ""), good: true };
  return { text: j.status || "…", good: false };
}

/* "Mirror to PixAI website" — the credential-switch toggle. Self-contained: loads its
   own status (offline days-left, never the token), flips MIRROR_TO_PIXAI, and Connect
   runs the server-side browser-session bootstrap (the server reads ITS OWN local browser;
   no credential crosses the network). See moonglade_backup.py's mirror helpers + the
   submit-path invariants. */
function MirrorTile() {
  const [st, setSt] = useState(null);      // {enabled, connected, days_left} — null until loaded
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const refresh = async () => {
    // Always drive the tile from the SERVER's real state, never a fabricated object -- a
    // fabricated {connected:true} with no `enabled` key drove the toggle from `undefined`.
    const j = await apiGet("/api/mirror/status");
    if (j.error) return;                    // keep st
    setSt(j);
    // The always-mounted destinations nav reveals "✦ AI Tools" only while armed, but it
    // can't see this overlay's state. Announce every status read on a window event so
    // NavSpine refetches and the entry appears/vanishes the instant the mirror flips.
    window.dispatchEvent(new CustomEvent("mg-mirror-changed", { detail: j }));
  };
  useEffect(() => { refresh(); }, []);
  const toggle = async () => {
    if (!st || busy) return;
    const want = !st.enabled;
    if (want && !st.connected) {            // never enable the credential switch with no session
      setMsg("Connect a session first (the button below), then turn this on.");
      return;
    }
    setBusy(true); setMsg("");
    const d = await apiPost("/api/mirror/enable", { enabled: want });
    setBusy(false);
    if (d && d.error) { setMsg("⚠ " + d.error); return; }
    await refresh();                        // reflect the real persisted flag
  };
  const connect = async () => {
    if (busy) return;
    setBusy(true); setMsg("Reading this machine's browser session…");
    const d = await apiPost("/api/mirror/connect", {});
    setBusy(false);
    if (!d || !d.ok) { setMsg("⚠ " + ((d && d.error) || "couldn't connect")); return; }
    setMsg("Connected.");
    await refresh();                        // re-read real status (enabled + connected + days)
  };
  // §1 "The gate" (The Bridge.dc.html 65-135, renderVals 386-432): armed drives the chrome;
  // the ring reads the JWT's days-left, colour-coded emerald>7 / peach<=7 / ruby<=0 / grey when off.
  const armed = !!(st && st.enabled);
  const days = st && st.days_left != null ? Math.max(0, Math.min(40, st.days_left)) : 0;
  const C = 163.4;  // 2*pi*26
  let ringMod, sessionSub, connectLabel = "Refresh session";
  if (!st) { ringMod = "off"; sessionSub = "…"; connectLabel = "Connect"; }
  else if (!armed) { ringMod = "off"; sessionSub = "Not connected — Connect to arm the tier."; connectLabel = "Connect"; }
  else if (days <= 0) { ringMod = "expired"; sessionSub = "Session expired — reconnect to keep tools live."; connectLabel = "Reconnect"; }
  else if (days <= 7) { ringMod = "low"; sessionSub = "Expires soon — " + days + " day" + (days === 1 ? "" : "s") + " left."; }
  else { ringMod = "healthy"; sessionSub = "Healthy — decoded offline, no re-auth needed."; }
  const ringOffset = armed ? (C * (1 - days / 40)).toFixed(1) : C;

  return (
    <div className="mgcp-bridge">
      <div className={"mgbr-tile" + (armed ? " armed" : "")}>
        <span className="mgbr-halo" aria-hidden="true" />
        <div className="mgbr-head">
          <div className="mgbr-glyph"><span>M</span><i className="mgbr-dot" /></div>
          <div className="mgbr-titlewrap">
            <div className="mgbr-title">Mirror to PixAI</div>
            <div className="mgbr-status">{armed ? "Armed · tier live" : "Off · tier hidden"}</div>
          </div>
          <button type="button" className={"mgbr-pill" + (armed ? " on" : "")} onClick={toggle}
            disabled={busy || !st} title="Arm or disarm the mirror" aria-pressed={armed}><i /></button>
        </div>

        <div className="mgbr-ringrow">
          <div className={"mgbr-ring " + ringMod}>
            <svg viewBox="0 0 62 62" aria-hidden="true">
              <circle cx="31" cy="31" r="26" className="mgbr-ring-bg" />
              <circle cx="31" cy="31" r="26" className="mgbr-ring-fg"
                strokeDasharray="163.4" strokeDashoffset={ringOffset} />
            </svg>
            <div className="mgbr-ring-c"><div className="mgbr-days">{days}</div><div className="mgbr-dayslbl">days</div></div>
          </div>
          <div className="mgbr-session">
            <div className="mgbr-session-lbl">Web session</div>
            <div className={"mgbr-session-sub " + ringMod}>{sessionSub}</div>
          </div>
        </div>

        <div className="mgbr-connectrow">
          <button type="button" className={"mgbr-connect" + (armed ? " armed" : "")}
            onClick={connect} disabled={busy}>↻ {connectLabel}</button>
          <div className="mgbr-jwtnote">re-reads the browser JWT</div>
        </div>
        {msg && <div className={"mgbr-msg" + (msg[0] === "⚠" ? " err" : "")}>{msg}</div>}
      </div>

      <div className="mgbr-unlocks">
        <div className={"mgbr-unlock" + (armed ? " armed" : "")}>
          <div className="mgbr-unum">6</div>
          <div className="mgbr-utext">Enhance presets return to the <b>generate drawer</b></div>
        </div>
        <div className={"mgbr-unlock" + (armed ? " armed" : "")}>
          <div className="mgbr-unum">28</div>
          <div className="mgbr-utext">AI-Tools scenes open in a <b>new catalog modal</b></div>
        </div>
        <div className="mgbr-verdict">{armed
          ? "Live now — 34 surfaces reachable through one engine."
          : "All hidden. The toggle is the only way anyone finds this — which is exactly what the discovery achievement will reward."}</div>
      </div>
    </div>
  );
}

export default function ControlPanelOverlay({ onClose, boot, account }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const [tab, setTab] = useState("maint");
  const [subOverlay, setSubOverlay] = useState(null); // 'users' | 'trash' | 'account'

  // Control Panel.dc.html:240-243 -- the library-folder picker. The design's own
  // <input type="file" webkitdirectory> can't actually supply what /api/library-path
  // needs: browsers never expose a real absolute host path through a file input, for
  // security reasons (only file.webkitRelativePath, a relative in-picker structure) --
  // so this is a real text-path input instead of a fake native picker that couldn't
  // work anyway. GET is safe/read-only; POST is localhost-only (same trust class as
  // /api/setup/save-key) and never moves anything -- it only changes what folder the
  // NEXT server start loads.
  const [libOpen, setLibOpen] = useState(false);
  const [libInfo, setLibInfo] = useState(null); // {path, stored, configured, default}
  const [libInput, setLibInput] = useState("");
  const [libBusy, setLibBusy] = useState(false);
  const [libMsg, setLibMsg] = useState("");
  const [libNeedsCreate, setLibNeedsCreate] = useState(null); // path pending a create confirm
  const openLibPicker = async () => {
    setLibOpen(true);
    setLibMsg(""); setLibNeedsCreate(null);
    const d = await apiGet("/api/library-path");
    if (!d.error) { setLibInfo(d); setLibInput(d.stored || d.path || ""); }
  };
  const saveLibPath = async (createIfMissing) => {
    if (!libInput.trim()) return;
    setLibBusy(true); setLibMsg("");
    const d = await apiPost("/api/library-path", { path: libInput.trim(), create: !!createIfMissing });
    setLibBusy(false);
    if (d.needs_create) { setLibNeedsCreate(d.path); return; }
    setLibNeedsCreate(null);
    if (d.error) { setLibMsg("⚠ " + d.error); return; }
    setLibMsg("✓ Saved — takes effect on the next server restart.");
    setLibInfo((prev) => ({ ...prev, stored: libInput.trim() }));
  };

  // Live Mirror -- ControlMobile.jsx already ships this against the real,
  // read-only /api/watch/status route (its own header comment explains why
  // it stays a local fetch-on-mount rather than folding into
  // useControlPanel.js: no interval needed, the tab's own mount/unmount
  // cadence is the natural refresh trigger). Same pattern here, desktop side
  // -- was simply never ported when this file was first built.
  const [watch, setWatch] = useState(null);
  useEffect(() => {
    apiGet("/api/watch/status").then((d) => { if (!d.error) setWatch(d); });
  }, []);

  const {
    summary, summaryErr, skins, activeSkin, pickSkin, brandingUnlocked, achievements,
    panelHistory, schedule, saveSchedule,
    fetchSummary, actionSpec,
    running, progress, log, jobError, jobResult, setJobResult, confirmArm, runAction, stopJob,
    dedupDone, organizeRes,
    testPullN, setTestPullN,
    taskId, setTaskId, taskState, importTask,
    power, powerConfirm, powerPhase, powerErr, clickPower, closePower,
  } = useControlPanel();
  // Console heart: pipelines (the run buttons) vs ledger (the run history) --
  // Control Panel.dc.html's own consoleHeart enum, surfaced as the same segmented
  // control ControlMobile.jsx already ships for the identical choice.
  const [heart, setHeart] = useState("pipelines");
  const [schedMsg, setSchedMsg] = useState("");
  // Newest event per machine action key -- /api/jobs is newest-first, so the first
  // hit per action IS its latest run. Older events predate the `action` field
  // (2026-08-06) and simply don't index; their rows still render in the ledger.
  const lastByAction = {};
  for (const j of panelHistory) {
    if (j.action && !lastByAction[j.action]) lastByAction[j.action] = j;
  }

  // Belt-and-suspenders against the tab ever reading "brand" while locked --
  // can't happen today (the only way in is the button below, which doesn't
  // render unlocked=false), but this is cheap insurance against a future
  // second entry point reopening the gate the owner just asked to close.
  useEffect(() => {
    if (tab === "brand" && !brandingUnlocked) setTab("maint");
  }, [tab, brandingUnlocked]);

  // Escape closes whatever the TOP layer is -- a sub-overlay first, then the whole Panel --
  // component-local (not part of the shared hook) because it reads THIS component's own
  // subOverlay/onClose, not anything the data layer owns. See useControlPanel.js's header
  // comment for why this stayed behind rather than moving with everything else.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (power) return; // let the power modal's own logic decide
      if (subOverlay) setSubOverlay(null);
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [power, subOverlay]);

  if (summaryErr) {
    return (
      <>
        <div className="mgv-scrim" onClick={onClose} />
        <div className="mgv-host">
          <div className="mgv-slab" role="dialog" aria-label="Control Panel">
            <div className="mgv-titlerow">
              <div className="mgv-title">Control Panel</div>
              <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
            </div>
            <div className="mgcp-runerr">{summaryErr}</div>
          </div>
        </div>
      </>
    );
  }
  if (!summary) return null;

  const isLocal = summary.panel_is_local;
  const credits = account && account.credits != null ? Number(account.credits).toLocaleString() : "—";
  const cards = account && account.cards != null ? Number(account.cards) : null;

  // Design's own {{ mirrorLead }}/{{ mirrorRest }} split (bold lead-in +
  // plain rest, Control Panel.dc.html:64) -- built from the same real
  // /api/watch/status fields ControlMobile.jsx already renders, just split
  // into the two pieces the desktop design's markup expects instead of one
  // run-on string.
  const mirrorLead = !watch ? "Checking." : watch.connected ? "Listening." : "Reconnecting.";
  const mirrorRest = !watch
    ? ""
    : watch.connected
      ? [
          (watch.mirrored || 0) + " mirrored this session",
          watch.last_event_at ? "last event " + timeAgo(watch.last_event_at) : null,
        ].filter(Boolean).join(" · ")
      : (watch.last_error || "waiting to reconnect…");

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgcp-slab" role="dialog" aria-label="Control Panel">
          <div className="mgcp-head">
            {boot?.mark_url ? <img src={boot.mark_url} alt="" style={{ width: 34, height: 34, borderRadius: 9 }} /> : null}
            <div>
              <div className="mgcp-title">Moonglade Athenaeum</div>
              <div className="mgcp-titlesub">Control Panel</div>
            </div>
            <div className="mgcp-headright">
              {/* Control Panel.dc.html:42 -- the header's own right slot is credits,
                  not a build/version stamp (that belongs in the sidebar footer,
                  design line ~77 -- a separate, still-open gap; see
                  docs/DECISIONS.md's punch list). boot?.build_stamp was occupying
                  this slot before; credits is what the design actually puts here. */}
              <div className="mgcp-credits">
                <b>{credits}</b> credits
                {cards != null ? <><br />{cards} free card{cards !== 1 ? "s" : ""}</> : null}
              </div>
              <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
            </div>
          </div>

          <div className="mgcp-body">
            <div className="mgcp-side">
              <div>
                <div className="mgcp-sidekick">The library</div>
                <div className="mgcp-sidehead">At a glance</div>
                {[
                  ["images", summary.stats.images], ["videos", summary.stats.videos],
                  ["collections", summary.stats.collections],
                ].map(([label, num]) => (
                  <div className="mgcp-vital" key={label}>
                    <b>{typeof num === "number" ? num.toLocaleString() : num}</b><span>{label}</span>
                  </div>
                ))}
                {/* Credits vital gains the paid/free split sub-line (Account-detail design,
                    drift §37); null split -> an honest "unknown", never a fake zero. And
                    free cards is its own vital (owner priority: cards first). */}
                <div className="mgcp-vital">
                  <b>{credits}</b><span>credits</span>
                  <div className="mgcp-vitalsub">
                    {account && account.credits_paid != null && account.credits_free != null
                      ? Number(account.credits_paid).toLocaleString() + " paid · " + Number(account.credits_free).toLocaleString() + " free"
                      : "paid / free split — unknown"}
                  </div>
                </div>
                <div className="mgcp-vital">
                  <b>{cards != null ? cards.toLocaleString() : "—"}</b><span>free cards</span>
                </div>
              </div>

              <div>
                {/* Control Panel.dc.html:60-66 -- Live Mirror, its own section
                    (distinct from Server below, unlike ControlMobile's merged
                    card -- the desktop design keeps them separate). Ported from
                    ControlMobile.jsx's own real /api/watch/status wiring. */}
                <div className="mgcp-sidekick">Live Mirror</div>
                <div className="mgcp-mirror">
                  <span className={"mgcp-mirrordot" + (watch?.connected ? "" : " off")} />
                  <div><b className={watch?.connected ? "on" : ""}>{mirrorLead}</b> {mirrorRest}</div>
                </div>
              </div>

              <div>
                <div className="mgcp-sidekick">Server</div>
                <div className="mgcp-srvrow">
                  <span className={"mgcp-svtag" + (summary.supervised ? "" : " off")}>
                    {summary.supervised ? "supervised" : "unsupervised"}
                  </span>
                  <button type="button" className="mgcp-chip" onClick={() => clickPower("restart")}
                    disabled={!summary.supervised} title={summary.supervised ? "" : "Restart needs the managed launcher"}>
                    {powerConfirm === "restart" ? "Confirm — Restart?" : "⟳ Restart"}
                  </button>
                  <button type="button" className="mgcp-chip dgr" onClick={() => clickPower("stop")}>
                    {powerConfirm === "stop" ? "Confirm — Stop?" : "■ Stop"}
                  </button>
                </div>
                {!summary.supervised && (
                  <div className="mgcp-tilenote">Restart needs the managed launcher (Serve Gallery). Stop still works.</div>
                )}
              </div>

              {/* Control Panel.dc.html:77 -- a version/date footer, margin-top:auto to sit
                  at the sidebar's bottom. boot.build_stamp (git short SHA + version) is the
                  real content for this slot -- it used to occupy the HEADER's credits slot
                  instead (see the credits fix above); this is where it actually belongs.
                  out_dir (local-only) stays as a real, useful addition alongside it. */}
              <div className="mgcp-ver">
                {boot?.build_stamp || "—"}
                {isLocal && summary.out_dir ? <><br /><span title={summary.out_dir}>{summary.out_dir}</span></> : null}
              </div>
            </div>

            <div className="mgcp-main">
              <div className="mgcp-tabs">
                <button type="button" className={"mgv-x-off"} style={tabStyle(tab === "maint")}
                  onClick={() => setTab("maint")}>Maintenance</button>
                {brandingUnlocked && (
                  <button type="button" style={tabStyle(tab === "brand")}
                    onClick={() => setTab("brand")}>✦ Branding</button>
                )}
              </div>

              {tab === "maint" && (
                <>
                  <div className="mgcp-console">
                    {!running ? (
                      <>
                        <div className="mgcp-consolehead">
                          <h3>The job console</h3>
                          {/* consoleHeart: 'pipelines' | 'ledger' -- the DC models both views
                              behind a preview enum; the real control is the same segmented
                              toggle ControlMobile.jsx already ships for this exact choice. */}
                          <div className="mgcp-seg">
                            <button type="button" className={"mgcp-segbtn" + (heart === "pipelines" ? " on" : "")}
                              onClick={() => setHeart("pipelines")}>Pipelines</button>
                            <button type="button" className={"mgcp-segbtn" + (heart === "ledger" ? " on" : "")}
                              onClick={() => setHeart("ledger")}>Ledger</button>
                          </div>
                          <span className="mgcp-consolehint">one job at a time</span>
                        </div>
                        {jobResult && (
                          <div className={"mgcp-runresult" + (jobResult.ok ? "" : " warn")}>
                            <div className="mgcp-runresulthead">
                              {jobResult.ok ? "✓ Finished" : "⚠ Finished with " + jobResult.warnCount + " warning" + (jobResult.warnCount !== 1 ? "s" : "")}
                              <button type="button" className="mgcp-run" onClick={() => setJobResult(null)}>dismiss</button>
                            </div>
                            {jobResult.lines.length > 0 && (
                              <div className="mgcp-runresultlog">
                                {jobResult.lines.map((ln, i) => <div key={i}>{ln}</div>)}
                              </div>
                            )}
                          </div>
                        )}
                        {heart === "pipelines" && (
                        <div className="mgcp-grid">
                          <div>
                            <div className="mgcp-grp">Sync — the daily pull</div>
                            <button type="button" className="mgcp-syncbtn" onClick={() => runAction("sync")}>
                              <b>↻ Sync now</b>
                              <span>pull new + fill metadata</span>
                            </button>
                            {/* Control Panel.dc.html:106-107 -- the sync meta line. Real
                                fields only: the latest sync run off the jobs paper trail
                                (rc included once the event carries one), and the real
                                standing-order state off schedule.json. */}
                            <div className="mgcp-syncmeta">
                              {lastByAction.sync ? (
                                <>last run <b>{fmtWhen(lastByAction.sync.ts)}</b>{" · "}
                                  <b className={ledgerResult(lastByAction.sync).good ? "ok" : ""}>
                                    {ledgerResult(lastByAction.sync).text}</b><br /></>
                              ) : (
                                <>last run <b>—</b><br /></>
                              )}
                              {schedule && (
                                <>auto <b className={schedule.enabled ? "ok" : ""}>{schedule.enabled ? "on" : "off"}</b>
                                  {" — every "}<b>{schedule.interval_hours || 6} hours</b> · safe jobs only</>
                              )}
                            </div>
                          </div>

                          <div>
                            <div className="mgcp-grp">Tend — care for the files</div>
                            <div className="mgcp-tendrow">
                              <div className="mgcp-tendlbl">Organize into month folders</div>
                              <div className="mgcp-chips">
                                <ActionChip spec={actionSpec("organize-dry")} armed={confirmArm === "organize-dry"} onRun={() => runAction("organize-dry")} />
                                <span className="mgcp-arr">→</span>
                                {/* Control Panel.dc.html:117 -- {{ organizeRes }}, real
                                    output parsed from cmd_organize()'s own dry-run line
                                    (useControlPanel.js), not a fabricated preview count. */}
                                <span className="mgcp-res">{organizeRes || "—"}</span>
                                <span className="mgcp-arr">→</span>
                                <ActionChip spec={actionSpec("organize")} dgr armed={confirmArm === "organize"} onRun={() => runAction("organize")} />
                                <ActionChip spec={actionSpec("undo-organize")} dgr label="Undo" armed={confirmArm === "undo-organize"} onRun={() => runAction("undo-organize")} />
                              </div>
                            </div>
                            <div className="mgcp-tendrow">
                              <div className="mgcp-tendlbl">Dedup</div>
                              <div className="mgcp-chips">
                                {DEDUP_STAGES.map((st, i) => (
                                  <React.Fragment key={st.key}>
                                    <ActionChip spec={actionSpec(st.key)} label={st.label}
                                      armed={confirmArm === st.key} onRun={() => runAction(st.key)}
                                      disabled={i > dedupDone}
                                      title={i > dedupDone ? "Run the earlier stages first" : undefined} />
                                    {i < DEDUP_STAGES.length - 1 && <span className="mgcp-arr">→</span>}
                                  </React.Fragment>
                                ))}
                              </div>
                            </div>
                            <div className="mgcp-tendrow">
                              <div className="mgcp-tendlbl">Thumbnails &amp; Similar index</div>
                              <div className="mgcp-chips">
                                <ActionChip spec={actionSpec("rebuild-thumbs")} label="Rebuild ALL thumbnails" armed={confirmArm === "rebuild-thumbs"} onRun={() => runAction("rebuild-thumbs")} />
                                <ActionChip spec={actionSpec("sync-similar")} label="Top up Similar" onRun={() => runAction("sync-similar")} />
                                <ActionChip spec={actionSpec("rebuild-similar")} label="Rebuild Similar (slow)" onRun={() => runAction("rebuild-similar")} />
                                <ActionChip spec={actionSpec("backfill-phash")} label="Backfill perceptual hashes" onRun={() => runAction("backfill-phash")} />
                              </div>
                            </div>
                          </div>

                          <div>
                            <div className="mgcp-grp">Check — read-only</div>
                            {[["stats", "Catalog stats"], ["inventory", "Inventory count"],
                              ["verify-dupes", "Verify _duplicates/"],
                              ["sync-artworks", "Sync published-artwork metadata"],
                              ["sync-videos", "Sync i2v videos"]].map(([key, label]) => (
                              actionSpec(key) ? (
                                <div className="mgcp-checkrow" key={key}>
                                  <b>{label}</b>
                                  {/* Control Panel.dc.html:149 -- the row remembers its last
                                      answer. Real per-action stamp off the jobs paper trail;
                                      "—" until an action's first run under the (2026-08-06)
                                      action-keyed events. */}
                                  <span className={"mgcp-checklast" + (lastByAction[key] && ledgerResult(lastByAction[key]).good ? " ok" : "")}>
                                    {lastByAction[key] ? fmtWhen(lastByAction[key].ts) : "—"}
                                  </span>
                                  <button type="button" className="mgcp-run" onClick={() => runAction(key)}>run ▸</button>
                                </div>
                              ) : null
                            ))}
                            <div className="mgcp-tendrow" style={{ marginTop: 10 }}>
                              <div className="mgcp-tendlbl">Test pull</div>
                              <div className="mgcp-chips">
                                <input type="number" min={1} max={200} value={testPullN}
                                  onChange={(e) => setTestPullN(Math.max(1, Math.min(200, Number(e.target.value) || 1)))}
                                  className="mgcp-taskinput" style={{ width: 60 }} />
                                <ActionChip spec={actionSpec("test-pull")} label="Fetch N recent"
                                  onRun={() => runAction("test-pull", testPullN)} />
                              </div>
                            </div>
                          </div>
                        </div>
                        )}

                        {/* ---- The ledger: run history + the standing order ----
                            Control Panel.dc.html:157-181 (heartLedger). Rows are the REAL
                            jobs.jsonl paper trail (type:"panel"), the standing-order line
                            is the real schedule.json, and "Never run here:" lists the safe
                            actions with no recorded run yet -- each a live run chip, per
                            the DC's own onRun handlers on those chips. */}
                        {heart === "ledger" && (
                          <div className="mgcp-ledger">
                            {schedule && (
                              <div className="mgcp-standing">
                                <b className="mgcp-standing-lab">⏱ Standing order</b>
                                <span className="mgcp-standing-body">
                                  run <b>{(summary.all_actions || summary.actions || []).find((a) => a.action === schedule.action)?.label || schedule.action}</b>
                                  {" every "}
                                  {isLocal ? (
                                    <select className="mgcp-standing-sel" value={schedule.interval_hours || 6}
                                      onChange={async (e) => {
                                        const d = await saveSchedule({ interval_hours: Number(e.target.value) });
                                        setSchedMsg(d.error ? "⚠ " + d.error : "");
                                      }}>
                                      {[1, 3, 6, 12, 24].map((h) => <option key={h} value={h}>{h} hour{h > 1 ? "s" : ""}</option>)}
                                    </select>
                                  ) : (
                                    <b>{schedule.interval_hours || 6} hours</b>
                                  )}
                                  {" — "}
                                  {isLocal ? (
                                    <button type="button" className={"mgcp-standing-toggle" + (schedule.enabled ? " on" : "")}
                                      onClick={async () => {
                                        const d = await saveSchedule({ enabled: !schedule.enabled });
                                        setSchedMsg(d.error ? "⚠ " + d.error : "");
                                      }}>{schedule.enabled ? "on" : "off"}</button>
                                  ) : (
                                    <b className={schedule.enabled ? "ok" : ""}>{schedule.enabled ? "on" : "off"}</b>
                                  )}
                                  {" · "}{schedule.workers || 4} workers
                                </span>
                                <span className="mgcp-standing-next">
                                  {schedule.enabled && schedule.last_run
                                    ? (() => {
                                        const left = (schedule.last_run + (schedule.interval_hours || 6) * 3600) - Date.now() / 1000;
                                        if (left <= 0) return "due now";
                                        return "next in " + Math.floor(left / 3600) + "h " + Math.floor((left % 3600) / 60) + "m";
                                      })()
                                    : schedule.enabled ? "next: on schedule" : ""}
                                </span>
                              </div>
                            )}
                            {schedMsg && <div className="mgcp-tilenote">{schedMsg}</div>}
                            {panelHistory.length === 0 && (
                              <div className="mgcp-ledger-empty">
                                No maintenance runs recorded yet — jobs land here as they finish.
                              </div>
                            )}
                            {panelHistory.slice(0, 20).map((j) => {
                              const res = ledgerResult(j);
                              return (
                                <div className="mgcp-ledgerrow" key={j.job_id}>
                                  <span className="mgcp-ledger-when">{fmtWhen(j.ts)}</span>
                                  <b className="mgcp-ledger-name">{j.label || j.action || j.job_id}</b>
                                  <span className={"mgcp-ledger-result" + (res.good ? " ok" : "")}>{res.text}</span>
                                  <span className="mgcp-ledger-spacer" />
                                  {/* Safe actions only: a destructive re-run belongs to the
                                      pipelines chips, whose arm-then-confirm UI is the real
                                      guard -- a bare link here would invisibly half-arm it. */}
                                  {j.action && actionSpec(j.action) && !actionSpec(j.action).destructive && !running && (
                                    <button type="button" className="mgcp-run"
                                      onClick={() => runAction(j.action)}>↻ run again</button>
                                  )}
                                </div>
                              );
                            })}
                            {(() => {
                              const never = (summary.actions || []).filter(
                                (a) => !a.destructive && !lastByAction[a.action]);
                              return never.length > 0 && (
                                <div className="mgcp-neverrun">
                                  Never run here:
                                  {never.map((a) => (
                                    <button type="button" className="mgcp-neverchip" key={a.action}
                                      onClick={() => runAction(a.action)}>{a.label}</button>
                                  ))}
                                </div>
                              );
                            })()}
                          </div>
                        )}
                        {!isLocal && (
                          <div className="mgcp-footnote">
                            <span>🔒 destructive stages: serving machine only</span>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="mgcp-running">
                        <div className="mgcp-runhead">
                          <span className="mgcp-runspin" />
                          <b className="mgcp-runname">{running.label}</b>
                          <button type="button" className="mgcp-chip dgr" style={{ marginLeft: "auto" }}
                            onClick={stopJob}>■ Stop this job</button>
                        </div>
                        <div className="mgcp-runbar">
                          <i className={progress?.pct == null ? "indeterminate" : ""}
                            style={progress?.pct != null ? { width: progress.pct + "%" } : undefined} />
                        </div>
                        <div className="mgcp-runlog">
                          {log.slice(-6).map((ln, i) => (
                            <div key={i} className={ln.indexOf("✓") === 0 ? "ok" : ""}>{ln}</div>
                          ))}
                        </div>
                        {/* Control Panel.dc.html:205-210's lockedMinis -- real other-action
                            labels from summary.actions (the same list actionSpec() already
                            reads), not the design's fixed 3-example array. */}
                        <div className="mgcp-lockedrow">
                          {(summary.actions || []).filter((a) => a.action !== running.action)
                            .slice(0, 3).map((a) => (
                              <span className="mgcp-lockchip" key={a.action}>{a.label}</span>
                            ))}
                          {(summary.actions || []).length - 1 > 3 && (
                            <span className="mgcp-lockchip">
                              +{(summary.actions || []).length - 1 - 3} more · one job at a time
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                    {jobError && <div className="mgcp-runerr">{jobError}</div>}
                  </div>

                  <div className="mgcp-tiles">
                    <div className="mgcp-tile mgcp-tile4">
                      <div className="mgcp-mkick">Recover a task by ID</div>
                      <div className="mgcp-taskrow">
                        <input className="mgcp-taskinput" value={taskId} placeholder="task or media id…"
                          onChange={(e) => setTaskId(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") importTask(); }} />
                        <button type="button" className="mgcp-chip" onClick={importTask}>⬇ Import</button>
                      </div>
                      <div className={"mgcp-tilenote" + (taskState === "running" ? " busy" : taskState?.done ? " ok" : "")}>
                        {taskState === "running" ? "⟳ resolving the task on PixAI…"
                          : taskState?.done ? "✓ imported — " + taskState.saved + " added to the catalog"
                          : taskState?.error ? "⚠ " + taskState.error
                          : "spends nothing — edits and Favorites strays Sync misses"}
                      </div>
                    </div>

                    <div className="mgcp-tile mgcp-tile2 click" onClick={() => setSubOverlay("trash")}>
                      <div className="mgcp-mkick">Trash</div>
                      <div className="mgcp-tilebig">{summary.trash_count.toLocaleString()}</div>
                      <button type="button" className="mgcp-smallchip">Open…</button>
                    </div>

                    <div className="mgcp-tile mgcp-tile3 click" onClick={() => setSubOverlay("users")}>
                      <div className="mgcp-mkick">Accounts</div>
                      <div className="mgcp-tilesmall">
                        {(summary.web_users || []).map((u) => u.username).join(" · ") || "none yet"}
                      </div>
                      <button type="button" className="mgcp-smallchip">Manage…</button>
                    </div>

                    {/* PixAI account (cards · coupons · credit ledger) -- named "PixAI
                        account" to avoid colliding with the local-users "Accounts" tile
                        above. Read-only launcher (Account-detail design, drift §37). */}
                    <div className="mgcp-tile mgcp-tile3 click" onClick={() => setSubOverlay("account")}>
                      <div className="mgcp-mkick">PixAI account</div>
                      <div className="mgcp-tilesmall">
                        {credits} credits{cards != null ? " · " + cards + " free cards on hand" : ""}
                      </div>
                      <button type="button" className="mgcp-smallchip">Open…</button>
                    </div>

                    <MirrorTile />

                    <div className="mgcp-tile mgcp-tile3">
                      <div className="mgcp-mkick">Catalog &amp; files</div>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                        <a className="mgcp-smallchip" href="/export-csv" style={{ textDecoration: "none" }}>⬇ Download catalog (CSV)</a>
                        {isLocal && (
                          <button type="button" className="mgcp-smallchip" onClick={openLibPicker}>library folder…</button>
                        )}
                      </div>
                      {libOpen ? (
                        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                          <input value={libInput} onChange={(e) => { setLibInput(e.target.value); setLibNeedsCreate(null); setLibMsg(""); }}
                            placeholder={libInfo?.default || "absolute path"} disabled={libBusy}
                            style={{ fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11, background: "var(--base)",
                              border: "1px solid var(--surface1)", borderRadius: 6, color: "var(--text)", padding: "5px 8px" }} />
                          <div style={{ display: "flex", gap: 6 }}>
                            <button type="button" className="mgcp-smallchip" disabled={libBusy}
                              onClick={() => saveLibPath(!!libNeedsCreate)}>
                              {libNeedsCreate ? "Create + Save" : "Save"}
                            </button>
                            <button type="button" className="mgcp-smallchip" onClick={() => setLibOpen(false)}>Cancel</button>
                          </div>
                          {libNeedsCreate && <div style={{ fontSize: 10.5, color: "var(--peach)" }}>Doesn't exist yet — Create + Save makes it.</div>}
                          {libMsg && <div style={{ fontSize: 10.5, color: libMsg[0] === "⚠" ? "var(--red)" : "var(--emerald)" }}>{libMsg}</div>}
                        </div>
                      ) : (
                        isLocal && <div className="mgcp-ver" style={{ marginTop: "auto" }}>{summary.out_dir}</div>
                      )}
                    </div>

                    {/* Control Panel.dc.html:250-286 -- once Branding is unlocked, the
                        mark/skins pickers LEAVE Maintenance: one pointer tile replaces
                        them ("moved out on unlock"). Pre-unlock, the inline pickers are
                        the only home those controls have. */}
                    {brandingUnlocked ? (
                      <div className="mgcp-tile mgcp-tile5">
                        <div className="mgcp-mkick">Branding &amp; skins</div>
                        <div className="mgcp-tilesmall">
                          Marks, animation, launcher icon, skins and banners now live in
                          their own <b style={{ color: "var(--text)" }}>✦ Branding</b> tab.
                        </div>
                        <button type="button" className="mgcp-openbrandbtn" onClick={() => setTab("brand")}>
                          Open Branding ▸
                        </button>
                      </div>
                    ) : (
                      skins.length > 0 && (
                        <div className="mgcp-tile mgcp-tile7" style={{ gridColumn: "span 12" }}>
                          <div className="mgcp-mkick">Skins</div>
                          <div className="mgcp-tilesmall">Cosmetic palette swaps for the whole suite — unlock more by earning epic achievements in the gallery (🏆).</div>
                          <SkinsRow skins={skins} active={activeSkin} onPick={pickSkin} />
                        </div>
                      )
                    )}
                  </div>
                </>
              )}

              {tab === "brand" && brandingUnlocked && (
                <BrandingTab summary={summary} onSaved={fetchSummary} isLocal={isLocal}
                  skins={skins} activeSkin={activeSkin} onPickSkin={pickSkin} achievements={achievements} />
              )}
            </div>
          </div>
        </div>
      </div>

      {subOverlay === "users" && (
        <UsersSubOverlay summary={summary} isLocal={isLocal} onClose={() => setSubOverlay(null)} onChanged={fetchSummary} />
      )}
      {subOverlay === "trash" && (
        <TrashSubOverlay isLocal={isLocal} onClose={() => setSubOverlay(null)} />
      )}
      {subOverlay === "account" && (
        <AccountSubOverlay onClose={() => setSubOverlay(null)} />
      )}
      {power && (
        <PowerModal mode={power} phase={powerPhase} error={powerErr} onClose={closePower} />
      )}
    </>
  );
}

function tabStyle(on) {
  return {
    fontSize: 13.5, padding: "8px 18px", borderRadius: 999, cursor: "pointer",
    color: on ? "var(--text)" : "var(--subtext)",
    border: "1px solid " + (on ? "var(--surface1)" : "transparent"),
    background: on ? "var(--surface0)" : "transparent",
    fontWeight: on ? 600 : 400, fontFamily: "inherit",
  };
}

export function ActionChip({ spec, dgr, label, armed, onRun, disabled, title }) {
  if (!spec) return null;
  const text = armed ? "Confirm — " + (label || spec.label) : (label || spec.label);
  return (
    <button type="button" className={"mgcp-chip" + (dgr || spec.destructive ? " dgr" : "")}
      onClick={onRun} disabled={disabled} title={title}>
      {text}
    </button>
  );
}

const SKIN_SW = {
  moonglade: ["#0c0a1c", "#b692e6", "#4fc99a", "#d4af37"],
  nightfallen: ["#0a0713", "#a678f0", "#7f6fe0", "#d9b3ff"],
  moonlit: ["#0b1018", "#8fb8e8", "#68d5e0", "#cfe1f5"],
  ember: ["#160c0c", "#e8935f", "#e0a94b", "#ffcf7a"],
  verdant: ["#0a1410", "#5fd39a", "#4fc99a", "#c8e6a8"],
};

export function SkinsRow({ skins, active, onPick }) {
  // Local, not lifted: the achievements fetch is a mount-time snapshot (see the "picking
  // a skin never refreshes achievements" gap noted in docs/DECISIONS.md), so a card this
  // client still believes is unlocked can get a real 403 "skin locked" back from the
  // server -- that refusal must be visible right on the card that was clicked, not
  // silently dropped.
  const [err, setErr] = useState("");
  const pick = async (sk) => {
    if (!sk.earned) return;
    setErr("");
    const d = await onPick(sk.id);
    if (d && d.error) setErr(sk.id + ": " + d.error);
  };
  return (
    <div className="mgcp-skinsrow-wrap">
      <div className="mgcp-skinsrow">
        {skins.map((sk) => {
          const sw = SKIN_SW[sk.id] || SKIN_SW.moonglade;
          const on = sk.id === active;
          return (
            <div key={sk.id}
              className={"mgcp-skincard" + (on ? " on" : "") + (!sk.earned ? " locked" : "")}
              onClick={() => pick(sk)}>
              <div className="mgcp-swrow">{sw.map((c, i) => <i key={i} style={{ background: c }} />)}</div>
              <div className="mgcp-skinname">{sk.name}{on ? " ✓" : ""}</div>
              <div className="mgcp-skindesc">{sk.desc}</div>
              {!sk.earned && <div className="mgcp-skinlock">🔒 locked</div>}
              {!sk.earned && sk.unlock && <div className="mgcp-skinunlock">{sk.unlock}</div>}
            </div>
          );
        })}
      </div>
      {err && <div className="mgcp-usererr" style={{ marginTop: 6 }}>⚠ {err}</div>}
    </div>
  );
}

// One Banner slot (banner_main / banner_login) -- Control Panel.dc.html's slot editor
// (lines 291-315), scoped to just these 2 real slots (mascots/rewards are permanently
// excluded from Branding, 2026-08-05 owner correction; Icons & marks already has its own
// working picker above and isn't refit into this pattern). Reuses the Phase 1 backend
// routes shipped 2026-08-05 (add_slot_asset/set_slot_crop/set_slot_active) verbatim --
// no backend change in this pass. "From the gallery…" and the rotating-source chip are
// deliberately not built here (the former needs wiring into PickerHost, the latter is an
// owner-deferred feature pending the SQLite-bundle work) -- disclosed below, not silently
// dropped.
/* The three banner slots, in the DC's own pill order (Control Panel.dc.html:566-573,
   BANNER_IDX = [1, 2, 5]). spec strings verbatim from the SLOTS array. */
const BANNER_SLOTS = [
  { slot: "banner_main", icon: "🖼", name: "Banner — main", title: "Banner — main",
    spec: "1920 × 480 · 4:1 · subject-left", ratio: "4 / 1",
    ph: "your banner art — cropped live, subject-left honored" },
  { slot: "banner_login", icon: "🔐", name: "Banner — login", title: "Banner — login",
    spec: "1920 × 480 · 4:1", ratio: "4 / 1",
    ph: "the login banner — same canvas, quieter mood" },
  { slot: "banner_loom", icon: "🎬", name: "Banner — Loom", title: "Banner — Loom",
    spec: "1920 × 160 · 12:1 · workspace strip", ratio: "12 / 1",
    ph: "the Loom workspace banner — wide and low" },
];

/* Per-skin var subset for the live sample frame (Control Panel.dc.html:354-370): the
   sample repaints under the SELECTED card's palette, which may not be the applied skin,
   so the html[data-skin] cascade can't paint it -- these are the same literal values as
   static/design-tokens.css's html[data-skin=...] blocks (source of truth:
   moonglade_gallery.DESIGN_TOKENS_CSS; sync-pinned there, spot-check here on drift). */
const SKIN_VARS = {
  moonglade:   { mantle: "#0a0818", surface0: "#211f3a", surface1: "#3a3460", text: "#d6d2e2", subtext: "#9a93ab", overlay0: "#6a6088", accent: "#b692e6", mauve: "#c4a6f0", emerald: "#4fc99a" },
  nightfallen: { mantle: "#080610", surface0: "#241a3f", surface1: "#3c2b63", text: "#e7ddff", subtext: "#a493c9", overlay0: "#7a6aa6", accent: "#a678f0", mauve: "#d3b6ff", emerald: "#7f6fe0" },
  moonlit:     { mantle: "#080d15", surface0: "#1c2735", surface1: "#334358", text: "#e6eefb", subtext: "#93a6bd", overlay0: "#6f8298", accent: "#8fb8e8", mauve: "#c6dbf7", emerald: "#68d5e0" },
  ember:       { mantle: "#120909", surface0: "#33201c", surface1: "#5a352c", text: "#fbe6df", subtext: "#c79b8d", overlay0: "#a5786a", accent: "#e8935f", mauve: "#f3c3a5", emerald: "#e0a94b" },
  verdant:     { mantle: "#08110d", surface0: "#173026", surface1: "#2a5140", text: "#e2f5ea", subtext: "#93bda6", overlay0: "#6f9d84", accent: "#5fd39a", mauve: "#a5f3cf", emerald: "#4fc99a" },
};

function MarksSection({
  summary, busy, msg, pickMark, pickAnim, setShortcut, isLocal,
  greatLibrary, uploadCustomMark, removeCustomMark,
}) {
  const marks = summary.branding.marks || [];
  const anims = summary.branding.anims || [];
  const cur = marks.find((m) => m.id === summary.branding.mark) || null;
  const anim = summary.branding.anim || "classic";
  // handoff-2026-08-09-branding-integration.md's 6th tile: locked pre-unlock,
  // an upload tile once earned, then the uploaded mark itself (already present
  // in `marks` -- list_marks() has no separate "custom" concept, it's just
  // another kind:"upload" entry, so it renders via the normal map() below like
  // any other mark; this only covers the two states before that exists).
  const customMark = marks.find((m) => m.kind === "upload") || null;
  return (
    <div className="mgcp-brandsec">
      <h3 className="mgcp-brandh">Icons, marks &amp; animation</h3>
      <div className="mgcp-markprevrow">
        {/* DC:396 -- the 168px live preview. The inner element is the REAL header mark
            (Strip.jsx:74's exact .mk markup, real anim-<name> classes from styles.css),
            scaled up from its 56px chrome size -- so what animates here is literally
            what the header will do, not a re-implementation of it. */}
        <div className="mgcp-markprevbox">
          <div className="mgcp-markprevscale">
            <span className={"mk anim-" + anim + (cur && cur.kind === "tile" ? " mk-tile" : "")}
              style={{ "--mark-url": "url('" + ((cur && cur.png) || "/branding/logo.png") + "')" }}>
              <span className="mark-m">M</span>
              <img src={(cur && cur.png) || "/branding/logo.png"} alt=""
                onError={(e) => e.currentTarget.remove()} />
            </span>
          </div>
        </div>
        <div className="mgcp-markprevside">
          <div className="mgcp-markprevcap">Shown at 44px · animated live</div>
          <div className="mgcp-marksbig">
            {marks.map((m) => {
              const on = m.id === summary.branding.mark;
              return (
                <button type="button" key={m.id}
                  className={"mgcp-markbig" + (on ? " on" : "")}
                  onClick={() => pickMark(m.id)} disabled={busy} title={m.label || m.id}>
                  {m.png
                    ? <img src={m.png} alt="" onError={(e) => e.currentTarget.remove()} />
                    : (m.id === "logo" ? "🌙" : "◈")}
                  {on && <span className="mgcp-markbig-check">✓</span>}
                </button>
              );
            })}
            {/* handoff-2026-08-09-branding-integration.md: 6th tile, gated to
                the-great-library. Locked placeholder pre-unlock; an upload
                tile once earned (only while no custom mark exists yet -- once
                uploaded it's just another entry in `marks` above). */}
            {!greatLibrary && !customMark && (
              <button type="button" className="mgcp-markbig locked" disabled
                title="The Great Library — unlocks a custom mark of your own">
                🔒
              </button>
            )}
            {greatLibrary && !customMark && (
              <label className="mgcp-markbig upload" title="Upload a custom mark">
                ⬆
                <input type="file" accept="image/*" disabled={busy} style={{ display: "none" }}
                  onChange={(e) => { uploadCustomMark(e.target.files[0]); e.target.value = ""; }} />
              </label>
            )}
          </div>
          {greatLibrary && (
            <div className="mgcp-tilesmall" style={{ marginTop: 2 }}>
              PNG · square (1:1) · 256px or larger — shown at 44px
            </div>
          )}
          {customMark && (
            <div className="mgcp-markreplace">
              <label className="mgcp-chip mgcp-slotcard-uploadchip">
                ↻ Replace…
                <input type="file" accept="image/*" disabled={busy} style={{ display: "none" }}
                  onChange={(e) => { uploadCustomMark(e.target.files[0]); e.target.value = ""; }} />
              </label>
              <button type="button" className="mgcp-chip" disabled={busy}
                onClick={() => removeCustomMark(customMark.id)}>
                ✕ Remove
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="mgcp-mkick">Animation</div>
      <div className="mgcp-animchips">
        {anims.map((a) => (
          <button type="button" key={a}
            className={"mgcp-animchip" + (a === summary.branding.anim ? " on" : "")}
            onClick={() => pickAnim(a)} disabled={busy}>
            {a.charAt(0).toUpperCase() + a.slice(1)}
          </button>
        ))}
      </div>
      {isLocal && (
        <>
          <div className="mgcp-tilesmall" style={{ marginTop: 4 }}>
            The selected mark doubles as this machine's app launcher and browser-tab icon.
          </div>
          <button type="button" className="mgcp-launcherbtn" onClick={setShortcut} disabled={busy}>
            Set {cur ? (cur.label || cur.id) : "mark"} as launcher
          </button>
        </>
      )}
      {msg && <div className="mgcp-tilenote">{msg}</div>}
    </div>
  );
}

function SkinsSection({ skins, activeSkin, onPickSkin }) {
  // The sample previews the SELECTED card (hover-free: last clicked), which is also the
  // applied skin -- picking a card both applies it and repaints the sample, exactly the
  // coupling the DC's own onPick uses.
  const v = SKIN_VARS[activeSkin] || SKIN_VARS.moonglade;
  const name = (skins.find((s) => s.id === activeSkin) || {}).name || activeSkin;
  return (
    <div className="mgcp-brandsec">
      <h3 className="mgcp-brandh">Skins</h3>
      {/* DC:354-370 -- the core-element sample frame, repainted under the selected
          skin's own vars. Every color below comes from SKIN_VARS, not the page. */}
      <div className="mgcp-skinsample" style={{ background: v.mantle, borderColor: v.surface1 }}>
        <div className="mgcp-skinsample-kick" style={{ color: v.overlay0 }}>Preview · {name}</div>
        <div className="mgcp-skinsample-row">
          <div className="mgcp-skinsample-mark" style={{ background: v.surface0, color: v.accent }}>✦</div>
          <div style={{ flex: "1 1 auto", minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: v.text }}>Nelnamara turns to camera</div>
            <div style={{ fontSize: 11, color: v.subtext }}>R2V · 5s · queued</div>
          </div>
        </div>
        <div className="mgcp-skinsample-row">
          {/* DC:939 samplePrimaryBtn -- the skin-aware metallic recipe, gradient built
              from the skin's accent+mauve, scrolled by the shared mgMetal keyframes. */}
          <span className="mgcp-skinsample-primary" style={{
            color: "color-mix(in oklab, " + v.accent + " 26%, #08040f)",
            /* backgroundImage, NOT the background shorthand -- the shorthand resets
               background-size and kills the class's 220% mgMetal scroll (caught live). */
            backgroundImage: "linear-gradient(100deg, color-mix(in oklab, " + v.accent + " 50%, #06030d) 0%, "
              + v.accent + " 18%, color-mix(in oklab, " + v.accent + " 22%, #ffffff) 34%, "
              + v.accent + " 50%, color-mix(in oklab, " + v.accent + " 74%, #06030d) 68%, "
              + v.mauve + " 84%, color-mix(in oklab, " + v.accent + " 50%, #06030d) 100%)",
          }}>✦ Generate</span>
          <span className="mgcp-skinsample-ghost" style={{ color: v.subtext, background: v.surface0, borderColor: v.surface1 }}>Preview</span>
          <span className="mgcp-skinsample-chip" style={{ color: v.mantle, background: v.emerald }}>emerald magic</span>
        </div>
        <div className="mgcp-skinsample-track" style={{ background: v.surface0 }}>
          <div className="mgcp-skinsample-fill" style={{ background: "linear-gradient(90deg, " + v.accent + ", " + v.emerald + ")" }} />
        </div>
      </div>
      {skins.length > 0 && <SkinsRow skins={skins} active={activeSkin} onPick={onPickSkin} />}
    </div>
  );
}

function BannerEditor({ summary, onSaved, achievements }) {
  const [slotIdx, setSlotIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [picking, setPicking] = useState(false);
  // Live slider state: local while dragging (the preview must track the thumb with no
  // network in the loop), committed to /api/branding/slot/crop on release.
  const [t, setT] = useState(null);       // {zoom, cropX, cropY} or null = mirror server
  // Earned-banner picks (SCOPE_bundle-v2-contract.md §6). Roster + per-banner earned
  // bools come from the server -- the same _mark_earned check that 403s the POST
  // below -- so a tile can never promise what a click would then be refused.
  // `achievements` is only the refetch trigger (its reference changes when earned
  // state could have); the lock here is cosmetic, the server gate is authoritative.
  const [earnedBanners, setEarnedBanners] = useState([]);

  const cfg = BANNER_SLOTS[slotIdx];
  const data = (summary.branding.slots || {})[cfg.slot] || { assets: [], active: null };
  const assets = data.assets || [];
  const active = assets.find((a) => a.id === data.active) || assets[0] || null;
  const shown = t || active || { zoom: 100, cropX: 50, cropY: 50 };

  useEffect(() => { setT(null); setMsg(""); }, [slotIdx, data.active]);
  useEffect(() => {
    apiGet("/api/branding/banners/earned").then((d) => setEarnedBanners(d.banners || []));
  }, [achievements]);

  const refresh = async (d) => { if (d && d.error) { setMsg("⚠ " + d.error); } else { setMsg(""); onSaved(); } };
  const upload = async (file) => {
    if (!file) return;
    setBusy(true); setMsg("");
    const fd = new FormData(); fd.append("slot", cfg.slot); fd.append("file", file);
    const d = await apiUpload("/api/branding/slot", fd);
    setBusy(false); refresh(d);
  };
  const fromGallery = async (mediaId) => {
    setBusy(true); setMsg("");
    const fd = new FormData(); fd.append("slot", cfg.slot); fd.append("media_id", mediaId);
    const d = await apiUpload("/api/branding/slot", fd);
    setBusy(false); refresh(d);
  };
  const commit = async (next) => {
    if (!active) return;
    setBusy(true);
    const d = await apiPost("/api/branding/slot/crop",
      { slot: cfg.slot, id: active.id, zoom: next.zoom, cropX: next.cropX, cropY: next.cropY });
    setBusy(false); refresh(d);
  };
  const resetCrop = () => { const n = { zoom: 100, cropX: 50, cropY: 50 }; setT(n); commit(n); };
  const pickActive = async (id) => {
    setBusy(true); setMsg("");
    refresh(await apiPost("/api/branding/slot/active", { slot: cfg.slot, id }));
  };
  const pickEarned = async (id) => {
    setBusy(true); setMsg("");
    refresh(await apiPost("/api/branding/banner/earned", { id }));
  };

  const slider = (label, key, min, max) => (
    <div className="mgcp-sliderrow">
      <div className="mgcp-sliderhead">
        <span>{label}</span>
        <span className="mgcp-sliderval">{shown[key]}%</span>
      </div>
      <input type="range" min={min} max={max} value={shown[key]} disabled={!active || busy}
        onChange={(e) => setT({ ...shown, [key]: +e.target.value })}
        onPointerUp={() => t && commit(t)}
        onKeyUp={(e) => { if (t && (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End")) commit(t); }} />
    </div>
  );

  return (
    <div className="mgcp-brandsec">
      <div className="mgcp-bannerpills">
        {BANNER_SLOTS.map((b, i) => (
          <button type="button" key={b.slot}
            className={"mgcp-bannerpill" + (i === slotIdx ? " on" : "")}
            onClick={() => setSlotIdx(i)}>
            <span className="ic">{b.icon}</span>{b.name}
          </button>
        ))}
      </div>
      <div className="mgcp-bannerhead">
        <h3 className="mgcp-brandh">{cfg.title}</h3>
        <span className="mgcp-bannerspec">{cfg.spec}</span>
      </div>
      <div className="mgcp-bannerprev" style={{ aspectRatio: cfg.ratio }}>
        {active
          ? <img src={active.png} alt="" style={{
              /* DC:953 verbatim -- the same expression _banner_window() replicates
                 server-side, so this preview IS what the saved flat will show. */
              objectPosition: shown.cropX + "% " + shown.cropY + "%",
              transform: "scale(" + (shown.zoom / 100) + ")",
              transformOrigin: shown.cropX + "% " + shown.cropY + "%",
            }} />
          : <span className="mgcp-bannerph">{cfg.ph}</span>}
        {active && (
          <div className="mgcp-bannerguide">
            <i className="tl" /><i className="tr" /><i className="bl" /><i className="br" />
          </div>
        )}
      </div>
      <div className="mgcp-sliderbox">
        {slider("Zoom", "zoom", 100, 250)}
        {slider("Horizontal", "cropX", 0, 100)}
        {slider("Vertical", "cropY", 0, 100)}
      </div>
      <div className="mgcp-bannerchips">
        <label className="mgcp-chip mgcp-slotcard-uploadchip">
          ⬆ From disk
          <input type="file" accept="image/*" disabled={busy} style={{ display: "none" }}
            onChange={(e) => { upload(e.target.files[0]); e.target.value = ""; }} />
        </label>
        {/* Rendering IS opening for <GalleryPicker> (2026-08-08 React port of the
            <mg-gallery-picker> web component -- same conditional-render pattern). */}
        <button type="button" className="mgcp-chip" disabled={busy} onClick={() => setPicking(true)}>
          🖼 From the gallery…
        </button>
        <button type="button" className="mgcp-chip" disabled={!active || busy} onClick={resetCrop}>
          ↺ Reset crop
        </button>
      </div>
      {assets.length > 1 && (
        <div className="mgcp-slotcard-thumbs">
          {assets.map((a) => {
            const on = a.id === data.active;
            return (
              <button type="button" key={a.id}
                className={"mgcp-slotcard-thumb" + (on ? " on" : "")}
                onClick={() => pickActive(a.id)} disabled={busy}
                title={on ? "active" : "Set active"}>
                <img src={a.png} alt="" />
                {on && <span className="mgcp-slotcard-thumb-check">✓</span>}
              </button>
            );
          })}
        </div>
      )}
      {/* Earned row (banner_main only): shipped reward banners, gated per-banner.
          Locked wears the same mystery mask the Folio puts on hidden feats -- and,
          deliberately, NO reward name in the tooltip (the art is sealed until
          earned; a title would spoil what the mask exists to hide). Earned is a
          live preview tile: click stamps it onto the banner flat server-side
          (same ratio pipeline as an upload), then the normal onSaved refresh
          repaints. */}
      {cfg.slot === "banner_main" && earnedBanners.length > 0 && (
        <>
          <div className="mgcp-mkick">Earned</div>
          <div className="mgcp-slotcard-thumbs">
            {earnedBanners.map((b) =>
              b.earned ? (
                <button type="button" key={b.id} className="mgcp-slotcard-thumb"
                  /* 120px puts the 30px-tall thumb at the banner's own 4:1, not the row's near-square crop */
                  style={{ width: 120 }}
                  onClick={() => pickEarned(b.id)} disabled={busy} title={b.label}>
                  <img src={b.png} alt="" />
                </button>
              ) : (
                <button type="button" key={b.id} className="mgcp-markbig locked" disabled
                  title="Hidden until earned">
                  <img src="/branding/mystery/secret_feat.png" alt=""
                    onError={(e) => e.currentTarget.remove()} />
                </button>
              )
            )}
          </div>
        </>
      )}
      {msg && <div className="mgcp-tilenote">{msg}</div>}
      {picking && <GalleryPicker defaultType="image"
        onPick={(m) => { setPicking(false); fromGallery(m.media_id); }}
        onClose={() => setPicking(false)} />}
    </div>
  );
}

export function BrandingTab({ summary, onSaved, isLocal, skins, activeSkin, onPickSkin, achievements }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  // DC:895-909 -- brandSections sub-nav; marks is the default section.
  const [section, setSection] = useState("marks");
  // The-Great-Library gate for the Custom Mark tile -- real earned state, the
  // exact same array/shape brandingUnlocked already reads off useControlPanel's
  // achievements for the whole tab, just checked for a different id. (The
  // banner row's earned art is REAL now too -- BannerEditor's Earned row -- but
  // it reads per-banner earned bools off /api/branding/banners/earned rather
  // than this check; `achievements` is threaded there only as a refetch trigger.)
  const greatLibrary = (achievements?.achievements || []).some(
    (a) => a.id === "the-great-library" && a.earned
  );

  const pickMark = async (id) => {
    setBusy(true); setMsg("");
    const d = await apiPost("/api/branding", { mark: id });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onSaved();
  };
  const pickAnim = async (anim) => {
    setBusy(true); setMsg("");
    const d = await apiPost("/api/branding", { anim });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onSaved();
  };
  const setShortcut = async () => {
    setBusy(true); setMsg("");
    const d = await apiPost("/api/branding/shortcut", {});
    setBusy(false);
    setMsg(d.error ? "⚠ " + d.error : "✓ Desktop shortcut updated");
  };
  const uploadCustomMark = async (file) => {
    if (!file) return;
    setBusy(true); setMsg("");
    const fd = new FormData(); fd.append("file", file);
    const d = await apiUpload("/api/branding/mark/custom", fd);
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onSaved();
  };
  const removeCustomMark = async (id) => {
    setBusy(true); setMsg("");
    const d = await apiPost("/api/branding/mark/custom/remove", { id });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onSaved();
  };

  const SECTIONS = [
    { key: "marks", label: "Icons, marks & animation" },
    { key: "skins", label: "Skins" },
    { key: "banners", label: "Banner slots" },
  ];

  return (
    <div className="mgcp-brandgrid">
      <div className="mgcp-brandside">
        <div className="mgcp-mkick">Make it yours</div>
        {SECTIONS.map((sec) => (
          <button type="button" key={sec.key}
            className={"mgcp-brandnav" + (section === sec.key ? " on" : "")}
            onClick={() => setSection(sec.key)}>{sec.label}</button>
        ))}
        {/* DC:299 -- the sealed note, verbatim. */}
        <div className="mgcp-sealed"><b>Sealed:</b> badges, tier frames, achievement data.</div>
      </div>
      <div className="mgcp-brandmain">
        {section === "marks" && (
          <MarksSection summary={summary} busy={busy} msg={msg} isLocal={isLocal}
            pickMark={pickMark} pickAnim={pickAnim} setShortcut={setShortcut}
            greatLibrary={greatLibrary} uploadCustomMark={uploadCustomMark} removeCustomMark={removeCustomMark} />
        )}
        {section === "skins" && (
          <SkinsSection skins={skins} activeSkin={activeSkin} onPickSkin={onPickSkin} />
        )}
        {section === "banners" && (
          <BannerEditor summary={summary} onSaved={onSaved} achievements={achievements} />
        )}
      </div>
    </div>
  );
}

export function UsersSubOverlay({ summary, isLocal, onClose, onChanged }) {
  const [users, setUsers] = useState(summary.web_users || []);
  const [newUser, setNewUser] = useState("");
  const [newPass, setNewPass] = useState("");
  const [newConfirm, setNewConfirm] = useState("");
  const [addErr, setAddErr] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [pwNew, setPwNew] = useState("");
  const [pwCurrent, setPwCurrent] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [removeErr, setRemoveErr] = useState("");
  const [removeBusy, setRemoveBusy] = useState(null); // username being removed
  // A LOCAL session may reset any OTHER account's password with no current_password
  // (api_users_password's whole reason to exist -- "closes the last CLI-only account
  // operation"). resetTarget scopes a second, per-row inline form to that one route call.
  const [resetTarget, setResetTarget] = useState(null);
  const [resetNew, setResetNew] = useState("");
  const [resetMsg, setResetMsg] = useState("");
  const [resetBusy, setResetBusy] = useState(false);

  const refresh = async () => {
    try {
      const d = await apiGet("/api/panel/summary");
      if (!d.error) setUsers(d.web_users || []);   // else keep showing the last-known list
    } catch { /* keep showing the last-known list */ }
  };

  const addUser = async () => {
    if (addBusy) return;
    setAddBusy(true); setAddErr("");
    const d = await apiPost("/api/users/add", {
      username: newUser, password: newPass, confirm: newConfirm, csrf: summary.csrf,
    });
    setAddBusy(false);
    if (d.error) { setAddErr(d.error); return; }
    setNewUser(""); setNewPass(""); setNewConfirm("");
    refresh(); onChanged();
  };

  const removeUser = async (username) => {
    if (removeBusy) return;
    setRemoveBusy(username); setRemoveErr("");
    const d = await apiPost("/api/users/remove", { username, csrf: summary.csrf });
    setRemoveBusy(null);
    if (d.error) { setRemoveErr(d.error); return; }
    refresh(); onChanged();
  };

  const changePassword = async (username) => {
    if (pwBusy || !pwNew) return;
    setPwBusy(true); setPwMsg("");
    const body = { username, new_password: pwNew, csrf: summary.csrf };
    if (username === summary.current_username) body.current_password = pwCurrent;
    const d = await apiPost("/api/users/password", body);
    setPwBusy(false);
    setPwMsg(d.error ? "⚠ " + d.error : "✓ password changed");
    if (!d.error) { setPwNew(""); setPwCurrent(""); }
  };

  const resetOtherPassword = async (username) => {
    if (resetBusy || !resetNew) return;
    setResetBusy(true); setResetMsg("");
    const d = await apiPost("/api/users/password", {
      username, new_password: resetNew, csrf: summary.csrf,
    });
    setResetBusy(false);
    if (d.error) { setResetMsg("⚠ " + d.error); return; }
    setResetMsg("✓ password reset");
    setResetNew("");
    setTimeout(() => { setResetTarget(null); setResetMsg(""); }, 1200);
  };

  return (
    <>
      <div className="mgcp-sub-scrim" onClick={onClose} />
      <div className="mgcp-sub-host">
        <div className="mgcp-sub-slab" role="dialog" aria-label="Accounts">
          <div className="mgcp-sub-titlerow">
            <h3>Accounts</h3>
            <button type="button" className="mgv-x" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close">×</button>
          </div>
          {users.map((u) => (
            <React.Fragment key={u.username}>
              <div className="mgcp-userrow">
                <b>{u.username}</b>
                {u.username === summary.current_username && <span>(you)</span>}
                {u.username !== summary.current_username && (
                  <>
                    {isLocal && (
                      <button type="button" className="mgcp-useraction"
                        onClick={() => { setResetTarget(resetTarget === u.username ? null : u.username); setResetNew(""); setResetMsg(""); }}>
                        reset password…
                      </button>
                    )}
                    <button type="button" className="mgcp-useraction" disabled={removeBusy === u.username}
                      onClick={() => removeUser(u.username)}>
                      {removeBusy === u.username ? "removing…" : "remove"}
                    </button>
                  </>
                )}
              </div>
              {resetTarget === u.username && (
                <div className="mgcp-userform" style={{ marginTop: -2, marginBottom: 6 }}>
                  <input className="mgcp-userinput" type="password" placeholder={"new password for " + u.username}
                    value={resetNew} onChange={(e) => setResetNew(e.target.value)} />
                  <button type="button" className="mgcp-chip" disabled={resetBusy}
                    onClick={() => resetOtherPassword(u.username)}>Reset…</button>
                  {resetMsg && <span className={resetMsg[0] === "⚠" ? "mgcp-usererr" : "mgcp-usermsg"}>{resetMsg}</span>}
                </div>
              )}
            </React.Fragment>
          ))}
          {removeErr && <div className="mgcp-usererr">{removeErr}</div>}
          <div className="mgcp-mkick" style={{ marginTop: 14 }}>Change your password</div>
          <div className="mgcp-userform">
            <input className="mgcp-userinput" type="password" placeholder="current password"
              value={pwCurrent} onChange={(e) => setPwCurrent(e.target.value)} />
            <input className="mgcp-userinput" type="password" placeholder="new password"
              value={pwNew} onChange={(e) => setPwNew(e.target.value)} />
            <button type="button" className="mgcp-chip" onClick={() => changePassword(summary.current_username)} disabled={pwBusy}>Change…</button>
          </div>
          {pwMsg && <div className={pwMsg[0] === "⚠" ? "mgcp-usererr" : "mgcp-usermsg"}>{pwMsg}</div>}
          <div className="mgcp-mkick" style={{ marginTop: 14 }}>Add user</div>
          <div className="mgcp-userform">
            <input className="mgcp-userinput" placeholder="username" value={newUser} maxLength={64}
              onChange={(e) => setNewUser(e.target.value)} />
            <input className="mgcp-userinput" type="password" placeholder="password" value={newPass} onChange={(e) => setNewPass(e.target.value)} />
            <input className="mgcp-userinput" type="password" placeholder="confirm" value={newConfirm} onChange={(e) => setNewConfirm(e.target.value)} />
            <button type="button" className="mgcp-chip" onClick={addUser} disabled={addBusy}>+ Add</button>
          </div>
          {addErr && <div className="mgcp-usererr">{addErr}</div>}
        </div>
      </div>
    </>
  );
}

const TRASH_LIMIT = 60;

export function TrashSubOverlay({ isLocal, onClose }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState(() => new Set());
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const [confirmWord, setConfirmWord] = useState("");
  const [confirmMode, setConfirmMode] = useState(null); // 'selected' | 'all'
  // Snapshot of what "selected" meant AT THE MOMENT the dialog opened -- sel itself keeps
  // changing if the grid stays interactive, so the delete call must use this, not the
  // live Set (see docs/DECISIONS.md's Control Panel review entry, 2026-08-02).
  const [confirmIds, setConfirmIds] = useState([]);

  const load = async (p) => {
    setLoading(true);
    try {
      const d = await apiGet("/api/trash/list?page=" + p + "&limit=" + TRASH_LIMIT);
      if (d.error) { setMsg("Network error loading the trash."); }
      else { setItems(d.items || []); setTotal(d.total || 0); setPage(d.page || p); }
    } catch { setMsg("Network error loading the trash."); }
    setLoading(false);
  };
  useEffect(() => { load(1); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.max(1, Math.ceil(total / TRASH_LIMIT));

  const toggle = (id) => setSel((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const selectAll = () => setSel((s) => (
    s.size === items.length ? new Set() : new Set(items.map((it) => it.media_id))
  ));

  const openConfirm = (mode) => {
    setConfirmMode(mode);
    setConfirmWord(""); // a mode switch must never inherit the OTHER mode's typed word
    setConfirmIds(mode === "all" ? [] : [...sel]);
  };
  const cancelConfirm = () => { setConfirmMode(null); setConfirmWord(""); setConfirmIds([]); };

  const restore = async () => {
    if (!sel.size) return;
    try {
      const d = await apiPost("/api/trash/restore", { media_ids: [...sel] });
      if (d.error) { setMsg("⚠ " + d.error); return; }
      setMsg((d.restored || []).length + " restored" + ((d.errors || []).length ? ", " + d.errors.length + " failed" : ""));
      setSel(new Set());
      load(page);
    } catch { setMsg("Network error — nothing was restored."); }
  };
  const deleteForever = async (all) => {
    const ids = all ? [] : confirmIds;
    if (!all && !ids.length) return;
    const body = all ? { confirm: true } : { media_ids: ids, confirm: true };
    try {
      const d = await apiPost(all ? "/api/trash/empty" : "/api/trash/delete-forever", body);
      if (d.error) { setMsg("⚠ " + d.error); cancelConfirm(); return; }
      setMsg((d.deleted || 0) + " deleted forever");
      setSel(new Set()); cancelConfirm();
      load(1);
    } catch { setMsg("Network error — nothing was deleted."); cancelConfirm(); }
  };

  const confirming = !!confirmMode;

  return (
    <>
      <div className="mgcp-sub-scrim" onClick={onClose} />
      <div className="mgcp-sub-host">
        <div className="mgcp-sub-slab wide" role="dialog" aria-label="Trash">
          <div className="mgcp-sub-titlerow">
            <h3>🗑 Trash</h3>
            <button type="button" className="mgv-x" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close">×</button>
          </div>
          <div className="mgcp-trashhead">
            {total} item{total !== 1 ? "s" : ""} in the trash
            {totalPages > 1 ? " · page " + page + " of " + totalPages : ""}
            {msg ? " · " + msg : ""}
          </div>
          <div className="mgcp-trashbar">
            <button type="button" className="mgcp-selectall" onClick={selectAll} disabled={confirming}>
              <span className={"mgcp-checkbox" + (sel.size && sel.size === items.length ? " on" : "")} />
              Select all loaded
            </button>
            <div style={{ flex: 1 }} />
            <button type="button" className="mgcp-chip" onClick={restore} disabled={!sel.size || confirming}>
              ↺ Restore selected{sel.size ? " (" + sel.size + ")" : ""}
            </button>
            {isLocal && (
              <button type="button" className="mgcp-pinkpill" disabled={!sel.size || confirming} onClick={() => openConfirm("selected")}>
                Delete forever
              </button>
            )}
          </div>
          {loading ? (
            <div className="mgcp-trashempty">Loading…</div>
          ) : items.length ? (
            <div className="mgcp-trashgrid">
              {items.map((it) => (
                <button type="button" key={it.media_id}
                  className={"mgcp-trashtile" + (sel.has(it.media_id) ? " on" : "")}
                  onClick={() => toggle(it.media_id)} disabled={confirming}>
                  <img src={it.thumb} alt="" loading="lazy" />
                  {sel.has(it.media_id) && <span className="mgcp-trashcheck">✓</span>}
                </button>
              ))}
            </div>
          ) : (
            <div className="mgcp-trashempty">Nothing in the trash.</div>
          )}
          {totalPages > 1 && (
            <div className="mgcp-trashpager">
              <button type="button" className="mgcp-chip" disabled={page <= 1 || confirming} onClick={() => load(page - 1)}>← Prev</button>
              <span>page {page} of {totalPages}</span>
              <button type="button" className="mgcp-chip" disabled={page >= totalPages || confirming} onClick={() => load(page + 1)}>Next →</button>
            </div>
          )}
          {isLocal && (
            <div className="mgcp-trashfoot">
              <span>emptying is destructive — serving machine only, asks first</span>
              <div style={{ flex: 1 }} />
              <button type="button" className="mgcp-pinkpill" disabled={!total || confirming} onClick={() => openConfirm("all")}>
                Empty trash…
              </button>
            </div>
          )}
          {confirmMode && (
            <div className="mgcp-userform" style={{ marginTop: 12 }}>
              <span className="mgcp-tilenote" style={{ padding: 0 }}>
                Type DELETE to permanently {confirmMode === "all"
                  ? "empty the trash (" + total + " items)"
                  : "delete " + confirmIds.length + " selected file" + (confirmIds.length !== 1 ? "s" : "")}:
              </span>
              <input className="mgcp-userinput" value={confirmWord} onChange={(e) => setConfirmWord(e.target.value)} />
              <button type="button" className="mgcp-pinkpill"
                disabled={confirmWord !== "DELETE" || (confirmMode === "selected" && !confirmIds.length)}
                onClick={() => deleteForever(confirmMode === "all")}>Confirm</button>
              <button type="button" className="mgcp-chip" onClick={cancelConfirm}>Cancel</button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export function PowerModal({ mode, phase, error, onClose }) {
  const isRestart = mode === "restart";
  const done = phase === "done";
  const failed = phase === "failed";
  const busy = !done && !failed; // still spinning / still polling
  const title = failed
    ? (isRestart ? "Restart didn't start" : "Stop didn't start")
    : mode === "stop"
      ? (done ? "The Athenaeum is dark" : "Stopping the server…")
      : (done ? "Back online" : "Restarting the Athenaeum");
  // On failure the error itself is the whole story -- shown once, in .mgcp-pwr-err below,
  // not duplicated into this line too (a real, confirmed defect: the busy chrome used to
  // keep showing "jobs drain first" right next to the refusal text, reading as though a
  // restart already refused outright was still somehow in progress).
  const line = failed ? "" : mode === "stop"
      ? (done ? "Server stopped. There's no restart-from-here — close this tab or window to finish." : "The web interface goes offline until you relaunch it.")
      : (done ? "Reconnected." : "It goes offline for a few seconds, then this page reconnects automatically.");

  return (
    <>
      <div className="mgcp-pwr-scrim" />
      <div className="mgcp-pwr-host">
        <div className="mgcp-pwr-card">
          <div className="mgcp-pwr-mascotwrap">
            <div className={"mgcp-pwr-halo" + (busy && isRestart ? " busy" : "")} />
            <div className={"mgcp-pwr-mascot" + (mode === "stop" || failed ? " off" : "") + (isRestart && busy ? " spin" : "")}
              style={{ backgroundImage: "url(/branding/mascots/" + (mode === "stop" ? "nel_shutdown.png" : "nel_restart.png") + ")" }} />
          </div>
          <div className="mgcp-pwr-title">{title}</div>
          {line && <div className="mgcp-pwr-line">{line}</div>}
          {/* Control Panel.dc.html:687's powerBarStyle drove a discrete 0-100% bar off
              RESTART_STAGES' fake stage index -- replaced (disclosed above) with real
              ping-polling that has no stage index to compute a real percentage from.
              An indeterminate bar (same real pattern the job console already uses,
              .mgcp-runbar i.indeterminate) is the honest middle ground: visible progress
              feedback without claiming a fake percentage. Restart-busy only -- stop has
              no comeback signal to show progress toward (see below). */}
          {isRestart && busy && (
            <div className="mgcp-runbar mgcp-pwr-bar"><i className="indeterminate" /></div>
          )}
          {error && <div className="mgcp-pwr-err">{error}</div>}
          {failed ? (
            <button type="button" className="mgcp-pwr-primary" onClick={onClose}>Close</button>
          ) : isRestart ? (
            done ? (
              <button type="button" className="mgcp-pwr-primary" onClick={onClose}>Return to the Panel</button>
            ) : (
              <>
                <div className="mgcp-pwr-hint">jobs drain first — nothing is lost mid-write</div>
                <button type="button" className="mgcp-pwr-ghost" onClick={onClose}>Cancel</button>
              </>
            )
          ) : (
            done ? (
              // window.close() only succeeds on a tab/window the page itself opened via
              // script; a normally-navigated tab silently ignores it (browser security,
              // not a bug here). onClose is kept as a fallback so the button still does
              // *something* -- it dismisses back to the (now server-less) Panel -- rather
              // than looking dead if the close is blocked.
              <button type="button" className="mgcp-pwr-primary"
                onClick={() => { window.close(); onClose(); }}>Close this tab</button>
            ) : (
              <div className="mgcp-pwr-hint">this tab can be closed — the archive sleeps until the server returns</div>
            )
          )}
        </div>
      </div>
    </>
  );
}
