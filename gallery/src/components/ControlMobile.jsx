import React, { useEffect, useState } from "react";
import useControlPanel, { DEDUP_STAGES } from "../hooks/useControlPanel.js";
import {
  ActionChip, SkinsRow, BrandingTab, UsersSubOverlay, TrashSubOverlay, PowerModal,
} from "./ControlPanelOverlay.jsx";
import MobileScreen from "./MobileScreen.jsx";
import "../styles/control-panel.css";
import "../styles/create-mobile.css";
import "../styles/control-mobile.css";

/* Mobile Control tab -- design spec: Moonglade Mobile.dc.html isControl block
   (lines 186-272, stat/mirror/console data at 600-611 & 1011-1086). THIRD real
   mobile tab (after Gallery, Create) -- replaces AppMobile.jsx's placeholder.

   CHROME CALL (the brief's own "your call, state which"): this is a sibling TAB
   BODY, not a drill-in -- the DC's own structure backs this up directly (Control
   is one of three values of the SAME `tab` state Gallery/Create use, switched by
   the persistent bottom bar, sitting in the identical scrollable body region --
   see the design-research brief's own "Full-page vs modal" section). So this
   file does NOT use MobileScreen.jsx's push-chrome for ITSELF -- that chrome is
   for drilling IN from a tab (a back chevron returning to where you came from),
   which is the wrong shape for a tab you arrive at by tapping the nav bar itself.
   MobileScreen.jsx IS used one level down, for Branding specifically (see
   openBrand/closeBrand below) -- exactly matching the DC's own documented
   behavior that drilling into Trash/Accounts/Branding from Control uses that
   third, full-viewport-push mechanism regardless of what container Control
   itself lives in.

   DATA LAYER: entirely useControlPanel() (../hooks/useControlPanel.js), the
   exact same hook ControlPanelOverlay.jsx now consumes for desktop -- summary/
   achievements fetch, job run/poll/cancel, recover-task-by-id, and the real
   Stop/Restart ping-poll. Nothing here reimplements any of that; ActionChip,
   SkinsRow, BrandingTab, UsersSubOverlay, TrashSubOverlay and PowerModal are
   the SAME components desktop renders, imported and used as-is -- Trash/
   Accounts management and the Branding tab's icon/anim/shortcut controls are
   therefore full-featured on mobile from this first pass, not placeholders.

   OUTER-TAB-SWITCH SAFETY (checked explicitly, per docs/DECISIONS.md's
   2026-08-03 entry naming this exact console as the next surface to verify --
   see VideoMode.jsx/AppMobile.jsx for the bug this pattern originally caught):
   unlike <mg-generate-drawer>, whose disconnectedCallback sweeps every poll
   timer on unmount with no way back, useControlPanel()'s job-status poll has a
   DIFFERENT but equally real fix already built in -- every fresh mount re-
   fetches /api/panel/status and rebuilds `running`/`progress`/`log` from
   server truth (see that hook's own header comment). These are local
   maintenance jobs, not billed PixAI generations: the header comment
   ControlPanelOverlay.jsx already carried ("designed to keep running with no
   browser tab involved") means switching Gallery/Create <-> Control just
   pauses this component's OWN polling, never the job itself, and resumes
   tracking correctly on return. So this file deliberately does NOT lift
   useControlPanel() up to AppMobile.jsx the way VideoMode was lifted --
   there is no credit-billing (or any other) risk being masked by that choice,
   only a component that is safely, cheaply remountable. The one real gap
   (pre-existing on desktop too, not introduced here, not fixed in this pass):
   the Stop/Restart ping-poll has no resume-on-mount check, so switching away
   mid-restart and back loses the "reconnecting..." UI (not the restart itself,
   which already fired once, irreversibly, before any unmount could happen).

   HONEST DEPARTURES (matching, not inventing new ones beyond, what
   ControlPanelOverlay.jsx already discloses for desktop):
   - Live Mirror's dot/text are GET /api/watch/status's own real fields
     (connected / last_event_at / mirrored / stale_reconnects / last_error --
     the exact ones classic's own loadWatchStatus() in moonglade_gallery.py
     already renders), fetched fresh each time this tab mounts. The DC's own
     copy ("watching 2,831 files on disk -- 0 pending") has no backing route
     anywhere in this app -- not rendered, rather than inventing a number.
   - The Ledger sub-tab is an honest disclosure note, not the DC's fabricated
     run-history rows -- nothing persists per-action run history (the exact
     gap ControlPanelOverlay.jsx's own header comment already discloses for
     the identical desktop console).
   - Sync's hint stays the real "pull new + fill metadata" desktop already
     shows -- no per-run last-run/rc/auto-schedule timestamp exists anywhere
     to report (the React port never wired /api/panel/schedule at all; see
     useControlPanel.js's header comment), so the DC's "last run today 14:02 ·
     57 new · rc 0 -- auto every 6h" line is not shown here either. */

function timeAgo(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h ago";
}

export default function ControlMobile({ account }) {
  const {
    summary, summaryErr, skins, activeSkin, pickSkin, brandingUnlocked,
    fetchSummary, actionSpec,
    running, progress, log, jobError, jobResult, setJobResult, confirmArm, runAction, stopJob,
    dedupDone, organizeRes,
    testPullN, setTestPullN,
    taskId, setTaskId, taskState, importTask,
    power, powerConfirm, powerPhase, powerErr, clickPower, closePower,
  } = useControlPanel();

  // Live Mirror -- new, mobile-only glue reusing the already-shipped, read-
  // only /api/watch/status route (see this file's header comment for why
  // this stays separate from useControlPanel.js rather than folding in).
  // Fetched once per mount; the Control tab's own mount/unmount cadence
  // (tapping the bottom nav) is the natural refresh trigger, so no extra
  // interval is added here.
  const [watch, setWatch] = useState(null);
  useEffect(() => {
    fetch("/api/watch/status").then((r) => r.json()).then(setWatch).catch(() => {});
  }, []);

  const [jobTab, setJobTab] = useState("pipelines"); // 'pipelines' | 'ledger' -- local UI only
  const [subOverlay, setSubOverlay] = useState(null); // 'users' | 'trash'

  // Branding drill-in -- MobileScreen.jsx's ownership contract, mirrored
  // exactly from CreateMobile.jsx's own Advanced screen (open/closing pair,
  // 220ms exit timeout matching glmScreenOut's own duration).
  const [brandOpen, setBrandOpen] = useState(false);
  const [brandClosing, setBrandClosing] = useState(false);
  const openBrand = () => setBrandOpen(true);
  const closeBrand = () => {
    setBrandClosing(true);
    setTimeout(() => { setBrandOpen(false); setBrandClosing(false); }, 220);
  };

  if (summaryErr) {
    return (
      <div className="glm-tab glm-placeholder">
        <div className="glm-placeholder-icon" aria-hidden="true">⚠</div>
        <div className="glm-placeholder-title">Control</div>
        <div className="glm-placeholder-note">{summaryErr}</div>
      </div>
    );
  }
  if (!summary) {
    return (
      <div className="glm-tab glm-placeholder">
        <div className="glm-placeholder-icon" aria-hidden="true">⚙</div>
        <div className="glm-placeholder-title">Control</div>
        <div className="glm-placeholder-note">Loading…</div>
      </div>
    );
  }

  const isLocal = summary.panel_is_local;
  const credits = account && account.credits != null ? Number(account.credits).toLocaleString() : "—";

  const mirrorLine = !watch
    ? "checking…"
    : watch.connected
      ? [
          "connected",
          (watch.mirrored || 0) + " mirrored this session",
          watch.last_event_at ? "last event " + timeAgo(watch.last_event_at) : null,
        ].filter(Boolean).join(" · ")
      : (watch.last_error ? "reconnecting… (" + watch.last_error + ")" : "connecting…");

  return (
    <div className="glm-tab">
      <div className="cm-pad">
      <div className="ctm-sec">
        <div className="mgcp-sidehead">At a glance</div>
        <div className="ctm-statgrid">
          {[
            ["images", summary.stats.images], ["videos", summary.stats.videos],
            ["collections", summary.stats.collections], ["credits", credits],
          ].map(([label, num]) => (
            <div className="ctm-statcard" key={label}>
              <div className="ctm-statnum">{typeof num === "number" ? num.toLocaleString() : num}</div>
              <div className="ctm-statlabel">{label}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="ctm-sec">
        <div className="ctm-mirror">
          <span className={"mgcp-mirrordot" + (watch?.connected ? "" : " off")} style={{ marginTop: 5 }} />
          <div className="ctm-mirrortext">
            <div className="ctm-mirrorline"><b>Live Mirror</b> {mirrorLine}</div>
            <div className="ctm-mirrorchips">
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
          </div>
        </div>
      </div>

      <div className="ctm-sec">
        <div className="mgcp-sidehead">Job console</div>
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
        {jobError && <div className="mgcp-runerr">{jobError}</div>}

        {running ? (
          <div className="mgcp-running">
            <div className="mgcp-runhead">
              <span className="mgcp-runspin" />
              <b className="mgcp-runname">{running.label}</b>
              <button type="button" className="mgcp-chip dgr" style={{ marginLeft: "auto" }}
                onClick={stopJob}>■ Stop</button>
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
        ) : (
          <>
            <div className="cm-seg3 ctm-jobseg">
              <button type="button" className={"cm-segbtn" + (jobTab === "pipelines" ? " on" : "")}
                onClick={() => setJobTab("pipelines")}>Pipelines</button>
              <button type="button" className={"cm-segbtn" + (jobTab === "ledger" ? " on" : "")}
                onClick={() => setJobTab("ledger")}>Ledger</button>
            </div>

            {jobTab === "pipelines" ? (
              <>
                <div className="mgcp-grp">Sync — the daily pull</div>
                <button type="button" className="mgcp-syncbtn" onClick={() => runAction("sync")}>
                  <b>↻ Sync now</b>
                  <span>pull new + fill metadata</span>
                </button>

                <div className="mgcp-grp" style={{ marginTop: 16 }}>Tend — care for the files</div>
                <div className="mgcp-tendrow">
                  <div className="mgcp-tendlbl">Organize into month folders</div>
                  <div className="mgcp-chips">
                    <ActionChip spec={actionSpec("organize-dry")} armed={confirmArm === "organize-dry"} onRun={() => runAction("organize-dry")} />
                    <span className="mgcp-arr">→</span>
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

                <div className="mgcp-grp" style={{ marginTop: 16 }}>Check — read-only</div>
                {[["stats", "Catalog stats"], ["inventory", "Inventory count"],
                  ["verify-dupes", "Verify _duplicates/"],
                  ["sync-artworks", "Sync published-artwork metadata"],
                  ["sync-videos", "Sync i2v videos"]].map(([key, label]) => (
                  actionSpec(key) ? (
                    <div className="mgcp-checkrow" key={key}>
                      <b>{label}</b>
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
                {!isLocal && (
                  <div className="mgcp-footnote" style={{ marginTop: 12 }}>
                    <span>🔒 destructive stages: serving machine only</span>
                  </div>
                )}
              </>
            ) : (
              <div className="ctm-ledgernote">
                Run history isn't kept between sessions yet — Pipelines above shows
                anything running live, and a job the scheduler fires with no tab
                open still runs; this tab just can't look back at what already
                finished.
              </div>
            )}
          </>
        )}
      </div>

      <div className="ctm-sec">
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
      </div>

      <div className="ctm-sec ctm-tiles">
        <div className="mgcp-tile click" onClick={() => setSubOverlay("trash")}>
          <div className="mgcp-mkick">Trash</div>
          <div className="mgcp-tilebig">{summary.trash_count.toLocaleString()}</div>
          <button type="button" className="mgcp-smallchip">Open…</button>
        </div>
        <div className="mgcp-tile click" onClick={() => setSubOverlay("users")}>
          <div className="mgcp-mkick">Accounts</div>
          <div className="mgcp-tilesmall">
            {(summary.web_users || []).map((u) => u.username).join(" · ") || "none yet"}
          </div>
          <button type="button" className="mgcp-smallchip">Manage…</button>
        </div>
      </div>

      <div className="ctm-sec">
        <a className="mgcp-smallchip" href="/export-csv" style={{ textDecoration: "none" }}>⬇ Download catalog (CSV)</a>
      </div>

      {brandingUnlocked && (
        <div className="ctm-sec">
          <div className="mgcp-tile click" onClick={openBrand}>
            <div className="mgcp-mkick">Branding</div>
            <div className="mgcp-marks">
              {(summary.branding.marks || []).slice(0, 6).map((m) => (
                <button type="button" key={m.id}
                  className={"mgcp-mark" + (m.id === summary.branding.mark ? " on" : "")}
                  title={m.id} onClick={(e) => { e.stopPropagation(); openBrand(); }}>
                  {m.id === "logo" ? "🌙" : "◈"}
                </button>
              ))}
            </div>
            <div className="mgcp-tilenote">mark · animation — open Branding</div>
          </div>
        </div>
      )}

      {skins.length > 0 && (
        <div className="ctm-sec">
          <div className="cm-subhead">Skins</div>
          <div className="mgcp-tilesmall">Cosmetic palette swaps for the whole suite — unlock more by earning achievements.</div>
          <SkinsRow skins={skins} active={activeSkin} onPick={pickSkin} />
        </div>
      )}
      </div>

      {/* Sub-overlays/screen are siblings of .cm-pad within this unpositioned
          .glm-tab, matching CreateMobile.jsx's own Advanced-screen placement
          exactly -- so .glm-screen's position:absolute;inset:0 resolves
          against .glm-body (position:relative), not against this div. */}
      {subOverlay === "users" && (
        <UsersSubOverlay summary={summary} isLocal={isLocal} onClose={() => setSubOverlay(null)} onChanged={fetchSummary} />
      )}
      {subOverlay === "trash" && (
        <TrashSubOverlay isLocal={isLocal} onClose={() => setSubOverlay(null)} />
      )}
      {power && (
        <PowerModal mode={power} phase={powerPhase} error={powerErr} onClose={closePower} />
      )}

      <MobileScreen open={brandOpen} closing={brandClosing} onClose={closeBrand} title="BRANDING">
        <BrandingTab summary={summary} onSaved={fetchSummary} isLocal={isLocal}
          skins={skins} activeSkin={activeSkin} onPickSkin={pickSkin} />
      </MobileScreen>
    </div>
  );
}
