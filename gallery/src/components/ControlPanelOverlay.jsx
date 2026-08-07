import React, { useEffect, useState } from "react";
import "../styles/overlays.css";
import "../styles/control-panel.css";
import useControlPanel, { postJSON, DEDUP_STAGES } from "../hooks/useControlPanel.js";

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

export default function ControlPanelOverlay({ onClose, boot, account }) {
  const [tab, setTab] = useState("maint");
  const [subOverlay, setSubOverlay] = useState(null); // 'users' | 'trash'
  const [markBusy, setMarkBusy] = useState(false); // inline mark-pick from the Branding tile

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
    const r = await fetch("/api/library-path");
    const d = await r.json().catch(() => null);
    if (d) { setLibInfo(d); setLibInput(d.stored || d.path || ""); }
  };
  const saveLibPath = async (createIfMissing) => {
    if (!libInput.trim()) return;
    setLibBusy(true); setLibMsg("");
    const d = await postJSON("/api/library-path", { path: libInput.trim(), create: !!createIfMissing });
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
    fetch("/api/watch/status").then((r) => r.json()).then(setWatch).catch(() => {});
  }, []);

  const {
    summary, summaryErr, skins, activeSkin, pickSkin, brandingUnlocked,
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
                  ["collections", summary.stats.collections], ["credits", credits],
                ].map(([label, num]) => (
                  <div className="mgcp-vital" key={label}>
                    <b>{typeof num === "number" ? num.toLocaleString() : num}</b><span>{label}</span>
                  </div>
                ))}
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

                    {brandingUnlocked && (
                      <div className="mgcp-tile mgcp-tile5">
                        <div className="mgcp-mkick">Branding</div>
                        <div className="mgcp-marks">
                          {/* Control Panel.dc.html:246-254 -- sl.onPick sets the mark
                              in place, right from this tile; clicking here used to just
                              redirect to the Branding tab instead of doing anything.
                              Same real /api/branding call BrandingTab's own pickMark()
                              already uses (not a second, forked write path). */}
                          {(summary.branding.marks || []).slice(0, 6).map((m) => (
                            <button type="button" key={m.id}
                              className={"mgcp-mark" + (m.id === summary.branding.mark ? " on" : "")}
                              disabled={markBusy}
                              title={(m.label || m.id) + (m.id === summary.branding.mark ? " (active)" : "")}
                              onClick={async () => {
                                if (m.id === summary.branding.mark) return;
                                setMarkBusy(true);
                                await postJSON("/api/branding", { mark: m.id });
                                setMarkBusy(false);
                                fetchSummary();
                              }}>
                              {m.png
                                ? <img src={m.png} alt=""
                                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: m.kind === "tile" ? 6 : 0 }}
                                    onError={(e) => e.currentTarget.remove()} />
                                : (m.id === "logo" ? "🌙" : "◈")}
                            </button>
                          ))}
                        </div>
                        <div className="mgcp-tilenote">
                          <span onClick={() => setTab("brand")} style={{ cursor: "pointer", textDecoration: "underline dotted" }}>
                            mark · animation
                          </span> — click a glyph to set it, or open the Branding tab for more
                        </div>
                      </div>
                    )}

                    {skins.length > 0 && (
                      <div className="mgcp-tile mgcp-tile7"
                        style={!brandingUnlocked ? { gridColumn: "span 12" } : undefined}>
                        <div className="mgcp-mkick">Skins</div>
                        <div className="mgcp-tilesmall">Cosmetic palette swaps for the whole suite — unlock more by earning achievements.</div>
                        <SkinsRow skins={skins} active={activeSkin} onPick={pickSkin} />
                      </div>
                    )}
                  </div>
                </>
              )}

              {tab === "brand" && brandingUnlocked && (
                <BrandingTab summary={summary} onSaved={fetchSummary} isLocal={isLocal}
                  skins={skins} activeSkin={activeSkin} onPickSkin={pickSkin} />
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
function BannerSlotCard({ slot, title, spec, ph, data, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const assets = data.assets || [];
  const active = assets.find((a) => a.id === data.active) || assets[0] || null;
  const cropCls = active ? (active.crop || "center") : "center";

  const upload = async (file) => {
    if (!file) return;
    setBusy(true); setMsg("");
    const fd = new FormData();
    fd.append("slot", slot);
    fd.append("file", file);
    const r = await fetch("/api/branding/slot", { method: "POST", body: fd });
    const d = await r.json();
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onChanged();
  };
  const cycleCrop = async () => {
    if (!active) return;
    const order = ["left", "center", "right"];
    const next = order[(order.indexOf(active.crop || "center") + 1) % order.length];
    setBusy(true); setMsg("");
    const d = await postJSON("/api/branding/slot/crop", { slot, id: active.id, crop: next });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onChanged();
  };
  const pick = async (id) => {
    setBusy(true); setMsg("");
    const d = await postJSON("/api/branding/slot/active", { slot, id });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onChanged();
  };

  return (
    <div className="mgcp-slotcard">
      <div className="mgcp-slotcard-head">
        <span className="mgcp-slotcard-title">{title}</span>
        <span className="mgcp-slotcard-spec">{spec}</span>
      </div>
      <div className="mgcp-slotcard-prev">
        {active
          ? <img src={active.png} alt="" />
          : <span className="mgcp-slotcard-ph">{ph}</span>}
        {active && (
          <div className={"mgcp-slotcard-cropguide " + cropCls}>
            <i className="tl" /><i className="tr" /><i className="bl" /><i className="br" />
          </div>
        )}
      </div>
      <div className="mgcp-slotcard-chips">
        <label className="mgcp-chip mgcp-slotcard-uploadchip">
          ⬆ From disk
          <input type="file" accept="image/*" disabled={busy} style={{ display: "none" }}
            onChange={(e) => { upload(e.target.files[0]); e.target.value = ""; }} />
        </label>
        {active && (
          <button type="button" className="mgcp-chip" disabled={busy} onClick={cycleCrop}>
            ✂ Size &amp; crop · subject-{cropCls}
          </button>
        )}
      </div>
      {assets.length > 1 && (
        <div className="mgcp-slotcard-thumbs">
          {assets.map((a) => (
            <button type="button" key={a.id}
              className={"mgcp-slotcard-thumb" + (a.id === data.active ? " on" : "")}
              onClick={() => pick(a.id)} disabled={busy}
              title={a.id === data.active ? "active" : "Set active"}>
              <img src={a.png} alt="" />
            </button>
          ))}
        </div>
      )}
      {msg && <div className="mgcp-tilenote" style={{ marginTop: 4 }}>{msg}</div>}
    </div>
  );
}

export function BrandingTab({ summary, onSaved, isLocal, skins, activeSkin, onPickSkin }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const marks = summary.branding.marks || [];
  const anims = summary.branding.anims || [];

  const pickMark = async (id) => {
    setBusy(true); setMsg("");
    const d = await postJSON("/api/branding", { mark: id });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onSaved();
  };
  const pickAnim = async (anim) => {
    setBusy(true); setMsg("");
    const d = await postJSON("/api/branding", { anim });
    setBusy(false);
    if (d.error) { setMsg("⚠ " + d.error); return; }
    onSaved();
  };
  const setShortcut = async () => {
    setBusy(true); setMsg("");
    const d = await postJSON("/api/branding/shortcut", {});
    setBusy(false);
    setMsg(d.error ? "⚠ " + d.error : "✓ Desktop shortcut updated");
  };

  return (
    <div className="mgcp-brandgrid">
      <div className="mgcp-brandside">
        <div className="mgcp-mkick">Make it yours</div>
        <div className="mgcp-sidehead">Icons &amp; marks</div>
        <div className="mgcp-marklist">
          {marks.map((m) => (
            <button type="button" key={m.id}
              className={"mgcp-markrow" + (m.id === summary.branding.mark ? " on" : "")}
              onClick={() => pickMark(m.id)} disabled={busy} title={m.label || m.id}>
              <span className="mgcp-markglyph">
                {m.png
                  ? <img src={m.png} alt=""
                      style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: m.kind === "tile" ? 6 : 0 }}
                      onError={(e) => e.currentTarget.remove()} />
                  : (m.id === "logo" ? "🌙" : "◈")}
              </span>{m.label || m.id}
            </button>
          ))}
        </div>
        <div className="mgcp-mkick" style={{ marginTop: 16 }}>Animation</div>
        {anims.map((a) => (
          <button type="button" key={a} className={"mgcp-animrow" + (a === summary.branding.anim ? " on" : "")}
            onClick={() => pickAnim(a)} disabled={busy}>{a}</button>
        ))}
        {isLocal && (
          <button type="button" className="mgcp-chip mgcp-shortcutbtn" onClick={setShortcut} disabled={busy}>
            Set launcher icon (this machine)
          </button>
        )}
        {msg && <div className="mgcp-tilenote" style={{ marginTop: 10 }}>{msg}</div>}
      </div>
      <div className="mgcp-brandmain">
        <div className="mgcp-sidehead" style={{ margin: 0 }}>Skins</div>
        <div className="mgcp-tilesmall">Cosmetic palette swaps for the whole suite — unlock more by earning achievements.</div>
        {skins.length > 0 && <SkinsRow skins={skins} active={activeSkin} onPick={onPickSkin} />}

        <div className="mgcp-sidehead" style={{ margin: "18px 0 0" }}>Banners</div>
        <div className="mgcp-slotcards">
          <BannerSlotCard slot="banner_main" title="Banner — main"
            spec="1920 × 480 · 4:1 · subject-left" ph="your banner art — cropped live, subject-left honored"
            data={(summary.branding.slots || {}).banner_main || { assets: [], active: null }}
            onChanged={onSaved} />
          <BannerSlotCard slot="banner_login" title="Banner — login"
            spec="1920 × 480 · 4:1" ph="the login banner — same canvas, quieter mood"
            data={(summary.branding.slots || {}).banner_login || { assets: [], active: null }}
            onChanged={onSaved} />
        </div>

        <div style={{ fontSize: 11.5, color: "var(--overlay0)", lineHeight: 1.6, marginTop: 8 }}>
          Uploading and picking a crop here is real and saved. <b style={{ color: "var(--subtext)" }}>Still not
          wired:</b> the active banner doesn't display anywhere yet — the header and login page still
          read the older flat <code>branding/banner.png</code>/<code>login-banner.png</code> files
          directly, and this picker doesn't write to those yet. "From the gallery…" and a rotating
          source aren't built. Mascot and reward-art slots are permanently out of scope for this tab.
        </div>
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
      const r = await fetch("/api/panel/summary");
      const d = await r.json();
      setUsers(d.web_users || []);
    } catch { /* keep showing the last-known list */ }
  };

  const addUser = async () => {
    if (addBusy) return;
    setAddBusy(true); setAddErr("");
    const d = await postJSON("/api/users/add", {
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
    const d = await postJSON("/api/users/remove", { username, csrf: summary.csrf });
    setRemoveBusy(null);
    if (d.error) { setRemoveErr(d.error); return; }
    refresh(); onChanged();
  };

  const changePassword = async (username) => {
    if (pwBusy || !pwNew) return;
    setPwBusy(true); setPwMsg("");
    const body = { username, new_password: pwNew, csrf: summary.csrf };
    if (username === summary.current_username) body.current_password = pwCurrent;
    const d = await postJSON("/api/users/password", body);
    setPwBusy(false);
    setPwMsg(d.error ? "⚠ " + d.error : "✓ password changed");
    if (!d.error) { setPwNew(""); setPwCurrent(""); }
  };

  const resetOtherPassword = async (username) => {
    if (resetBusy || !resetNew) return;
    setResetBusy(true); setResetMsg("");
    const d = await postJSON("/api/users/password", {
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
            <input className="mgcp-userinput" placeholder="username" value={newUser} onChange={(e) => setNewUser(e.target.value)} />
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
      const r = await fetch("/api/trash/list?page=" + p + "&limit=" + TRASH_LIMIT);
      const d = await r.json();
      setItems(d.items || []); setTotal(d.total || 0); setPage(d.page || p);
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
      const d = await postJSON("/api/trash/restore", { media_ids: [...sel] });
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
      const d = await postJSON(all ? "/api/trash/empty" : "/api/trash/delete-forever", body);
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
