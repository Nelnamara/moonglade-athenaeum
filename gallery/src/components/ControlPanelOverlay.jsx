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

export default function ControlPanelOverlay({ onClose, boot, account }) {
  const [tab, setTab] = useState("maint");
  const [subOverlay, setSubOverlay] = useState(null); // 'users' | 'trash'

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
    summary, summaryErr, skins, activeSkin, pickSkin,
    fetchSummary, actionSpec,
    running, progress, log, jobError, jobResult, setJobResult, confirmArm, runAction, stopJob,
    dedupDone, organizeRes,
    testPullN, setTestPullN,
    taskId, setTaskId, taskState, importTask,
    power, powerConfirm, powerPhase, powerErr, clickPower, closePower,
  } = useControlPanel();

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

              {isLocal && summary.out_dir && (
                <div className="mgcp-ver" title={summary.out_dir}>{summary.out_dir}</div>
              )}
            </div>

            <div className="mgcp-main">
              <div className="mgcp-tabs">
                <button type="button" className={"mgv-x-off"} style={tabStyle(tab === "maint")}
                  onClick={() => setTab("maint")}>Maintenance</button>
                <button type="button" style={tabStyle(tab === "brand")}
                  onClick={() => setTab("brand")}>✦ Branding</button>
              </div>

              {tab === "maint" && (
                <>
                  <div className="mgcp-console">
                    {!running ? (
                      <>
                        <div className="mgcp-consolehead">
                          <h3>The job console</h3>
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
                        <div className="mgcp-grid">
                          <div>
                            <div className="mgcp-grp">Sync — the daily pull</div>
                            <button type="button" className="mgcp-syncbtn" onClick={() => runAction("sync")}>
                              <b>↻ Sync now</b>
                              <span>pull new + fill metadata</span>
                            </button>
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
                      <div className="mgcp-tilebig">—</div>
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
                      </div>
                      {isLocal && <div className="mgcp-ver" style={{ marginTop: "auto" }}>{summary.out_dir}</div>}
                    </div>

                    <div className="mgcp-tile mgcp-tile5">
                      <div className="mgcp-mkick">Branding</div>
                      <div className="mgcp-marks">
                        {(summary.branding.marks || []).slice(0, 6).map((m) => (
                          <button type="button" key={m.id}
                            className={"mgcp-mark" + (m.id === summary.branding.mark ? " on" : "")}
                            title={m.id} onClick={() => setTab("brand")}>{m.id === "logo" ? "🌙" : "◈"}</button>
                        ))}
                      </div>
                      <div className="mgcp-tilenote">mark · animation — open the Branding tab</div>
                    </div>

                    {skins.length > 0 && (
                      <div className="mgcp-tile mgcp-tile7">
                        <div className="mgcp-mkick">Skins</div>
                        <div className="mgcp-tilesmall">Cosmetic palette swaps for the whole suite — unlock more by earning achievements.</div>
                        <SkinsRow skins={skins} active={activeSkin} onPick={pickSkin} />
                      </div>
                    )}
                  </div>
                </>
              )}

              {tab === "brand" && (
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
            </div>
          );
        })}
      </div>
      {err && <div className="mgcp-usererr" style={{ marginTop: 6 }}>⚠ {err}</div>}
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
              onClick={() => pickMark(m.id)} disabled={busy}>
              <span className="mgcp-markglyph">{m.id === "logo" ? "🌙" : "◈"}</span>{m.id}
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
        <div style={{ fontSize: 11.5, color: "var(--overlay0)", lineHeight: 1.6, marginTop: 8 }}>
          Banner, mascot, and reward-art slots aren't wired up yet — only the icon/mark and
          animation you're setting here, and the skin palette, are live.
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
      ? (done ? "Server stopped — safe to close this tab." : "The web interface goes offline until you relaunch it.")
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
              <button type="button" className="mgcp-pwr-primary" onClick={onClose}>Close</button>
            ) : (
              <div className="mgcp-pwr-hint">this tab can be closed — the archive sleeps until the server returns</div>
            )
          )}
        </div>
      </div>
    </>
  );
}
