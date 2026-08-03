import React, { useEffect, useState } from "react";
import "../styles/overlays.css";
import "../styles/duplicate-review-overlay.css";

/* Duplicate Review overlay — the sixth designed nav overlay to port, opened
   from Collection Health's Duplicates/Reclaimable tiles (HealthOverlay.jsx).

   STAGE 3 (this file, 2026-08-02): wires the real Resolve / Undo /
   Auto-resolve-all actions on top of the read-only stage below, against the
   backend stage's POST /api/duplicates/resolve and POST /api/duplicates/undo
   (moonglade_gallery.py, LOGIN tier, explicit-CSRF class -- _check_csrf(),
   same helper /api/users/add etc. use). `boot.csrf` (threaded down from
   App.jsx, same token every other CSRF'd POST in this app rides) is the
   token; `onResolved` (accepted unused by the prior stage) now actually
   fires App's afterMutation() so the gallery grid reloads once a duplicate
   copy leaves the visible library.

   Keeper selection: exactly one member per group is "the keeper" (radio
   semantics, not an independent per-tile checkbox) -- this matches the real
   POST /api/duplicates/resolve contract exactly, which takes ONE `keep`
   object and an array `remove`, never a list of keeps. Every non-keeper
   member is implicitly the remove set. Default keeper on load: the
   highest-RATED member in the group, ties going to the first one found --
   ported faithfully from the DC handoff's own rule (see bestKeeperPath()
   below, from design_handoff/design_handoff_moonglade_suite/Duplicate
   Review.dc.html's componentDidMount + _bestIdx: `if (n > bestScore)`, a
   strict `>` so a tie never overwrites the earlier index). Clicking the
   current keeper's pill deselects it (keep-count -> 0 for that group,
   disabling Resolve) rather than forcing exactly one keeper at all times --
   that's the real, server-enforced "keep-count 0 is refused" case the
   backend stage's tests already cover, not a frontend invention.

   Confirm-gate weights (the harder-to-misclick problem, ActionsMenu.jsx's
   askCloud/CloudDeleteModal + ControlPanelOverlay's Trash typed-DELETE gate
   were the two established precedents surveyed here):
     - per-group Resolve: NO extra confirm dialog. The keep/remove choice is
       already fully visible and deliberately toggled right there in the
       card (not hidden behind a menu, unlike ActionsMenu's bulk items), it
       only ever touches ONE group, and Undo sits one click away in the same
       card the instant it lands -- the same "purely reversible, undo is
       right there" shape Trash's own non-destructive Restore button gets
       (no confirm), not the shape its permanent-delete gets (typed DELETE).
     - Auto-resolve-all: its OWN, more explicit gate -- an inline confirm
       panel (matching the Trash/Maintenance inline-confirm precedent, not a
       bare window.confirm) naming the real blast radius ("N files across M
       groups"), computed live from the CURRENT keeper selections, not a
       fabricated estimate. No typed-word gate: unlike Trash's "delete
       forever" or ActionsMenu's "Delete from PixAI", this is reversible
       quarantine (_duplicates/, Undo per item) not permanent deletion, so a
       typed-DELETE gate would overstate the stakes relative to the real
       precedent set by this codebase's own typed-vs-simple split. It is
       still strictly MORE friction than the zero-dialog per-group Resolve:
       a second explicit click on a dialog that names real numbers.

   No locked DC mockup exists for this overlay specifically (unlike Health's
   ovHealth / Import's ovImport slabs) -- built off the classic /duplicates
   page's real information architecture (one card per group, keeper vs.
   reclaimable) instead of invented, the same "port the real behavior, not a
   guess" approach Import took from classic's ImportUI. The keep/remove
   toggle pill placement and the resolved-card treatment DO follow the DC
   handoff file's own real interaction design (per-tile pill, top-left;
   resolved cards dim) even though the overall shell doesn't.

   Backend: GET /api/duplicates (moonglade_gallery.py, LOGIN tier). Four real
   tiers -- matchType drives the label, never a fabricated "reason" string:
     same_media      classic's Class A: same media_id, saved in >1 folder.
     identical_file  classic's Class B: byte-identical file content.
     same_seed       catalog rows sharing (seed, prompt_full) -- new.
     near_duplicate  dHash Hamming-distance clustering (compute_dhash()) --
                      the ONE tier that carries a real percentage
                      (closeness_pct); the other three stay percentage-free.
   Every member across all four tiers shares one key set (media_id, thumb,
   width, height, rating, created_at, is_video, path, bucket, size,
   is_keeper), so it renders identically here regardless of matchType. `path`
   -- not media_id -- is each member's real unique key within a group (a
   same_media group's members all share ONE media_id), and is what the
   resolve/undo calls key off, per the backend stage's own contract.
   Groups arrive pre-sorted by reclaimable_bytes descending. */

const MATCH_LABEL = (g) => {
  switch (g.matchType) {
    case "same_media": return "Same generation, saved twice";
    case "identical_file": return "Identical file";
    case "same_seed": return "Same seed";
    case "near_duplicate":
      return "Near-duplicate (" + Math.round(g.closeness_pct) + "% match)";
    default: return g.matchType;
  }
};

const COUNT_LABEL = {
  same_media: "same generation",
  identical_file: "identical file",
  same_seed: "same seed",
  near_duplicate: "near-duplicate",
};

function fmtBytes(b) {
  if (b == null) return "—";
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(0) + " KB";
  if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB";
  return (b / 1073741824).toFixed(2) + " GB";
}

function MemberStars({ rating }) {
  const val = Number(rating) || 0;
  if (!val) return <span className="mgdr-unrated">unrated</span>;
  return (
    <span className="mgdr-stars" aria-label={"rating " + val}>
      {[1, 2, 3, 4, 5].map((k) => (
        <span key={k} className={"mgdr-star" + (k <= val ? " lit" : "")}>★</span>
      ))}
    </span>
  );
}

// Ported faithfully from the DC handoff's own default-keeper rule (see the
// header comment above): highest rating wins, ties go to the FIRST member
// found -- a strict `>`, never `>=`.
function bestKeeperPath(g) {
  let bestIdx = 0, bestScore = -1;
  (g.members || []).forEach((m, i) => {
    const n = Number(m.rating) || 0;
    if (n > bestScore) { bestScore = n; bestIdx = i; }
  });
  const best = g.members && g.members[bestIdx];
  return best ? best.path : null;
}

async function postJSON(url, body) {
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || (d && d.error)) return { error: (d && d.error) || (url + " failed: " + r.status) };
    return d || {};
  } catch (e) {
    return { error: "network error: " + (e && e.message ? e.message : "unreachable") };
  }
}

export default function DuplicateReviewOverlay({ onClose, onResolved, boot }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [keeperByGroup, setKeeperByGroup] = useState({});   // group.id -> path | null
  const [resolvedByGroup, setResolvedByGroup] = useState({}); // group.id -> { quarantined: [...] }
  const [busyGroups, setBusyGroups] = useState(() => new Set()); // group.ids mid-resolve/undo
  const [groupErrors, setGroupErrors] = useState({});        // group.id -> message
  const [autoConfirmOpen, setAutoConfirmOpen] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoError, setAutoError] = useState("");

  const csrf = (boot && boot.csrf) || "";

  useEffect(() => {
    let dead = false;
    fetch("/api/duplicates")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => {
        if (dead) return;
        setData(d);
        const initKeepers = {};
        (d.groups || []).forEach((g) => { initKeepers[g.id] = bestKeeperPath(g); });
        setKeeperByGroup(initKeepers);
      })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    return () => { dead = true; };
  }, []);

  const groups = (data && data.groups) || [];
  const counts = (data && data.counts) || {};
  const countChips = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => n + " " + (COUNT_LABEL[k] || k) + (n !== 1 ? "s" : ""));

  const resolvedCount = Object.keys(resolvedByGroup).length;
  const pendingCount = groups.length - resolvedCount;
  const pendingReclaimable = groups.reduce(
    (sum, g) => (resolvedByGroup[g.id] ? sum : sum + g.reclaimable_bytes), 0);

  const isBusy = (gid) => busyGroups.has(gid);
  const setGroupBusy = (gid, on) => setBusyGroups((prev) => {
    const next = new Set(prev);
    if (on) next.add(gid); else next.delete(gid);
    return next;
  });
  const setGroupErrorMsg = (gid, msg) => setGroupErrors((prev) => ({ ...prev, [gid]: msg }));
  const clearGroupError = (gid) => setGroupErrors((prev) => {
    if (!(gid in prev)) return prev;
    const next = { ...prev };
    delete next[gid];
    return next;
  });

  const toggleKeeper = (groupId, path) => {
    setKeeperByGroup((prev) => {
      const cur = prev[groupId];
      return { ...prev, [groupId]: cur === path ? null : path };
    });
  };

  // Builds the exact {group_id, keep, remove} shape /api/duplicates/resolve
  // expects. Returns null when there's no keeper selected (keep-count 0) --
  // the real refusal is server-side (backend stage's own tests confirm it),
  // this is just what keeps a 0-keep group out of the request entirely.
  const buildResolution = (g) => {
    const keeperPath = keeperByGroup[g.id];
    const keepMember = (g.members || []).find((m) => m.path === keeperPath);
    if (!keepMember) return null;
    const remove = (g.members || [])
      .filter((m) => m.path !== keeperPath)
      .map((m) => ({ media_id: m.media_id, path: m.path }));
    if (!remove.length) return null;
    return { group_id: g.id, keep: { media_id: keepMember.media_id, path: keepMember.path }, remove };
  };

  const resolveGroup = async (g) => {
    // Explicit early-return guard -- do NOT rely on the button's disabled
    // attribute alone. docs/DECISIONS.md's "Calibration" section documents
    // the real-world precedent for this class of bug on this exact React
    // conversion: /api/generate's prompt_helper flag shipped a
    // boolean-coercion bug where an explicitly-DISABLED control was
    // submitted as enabled (`str(False) == "False"` never matched the
    // falsy tuple). The server refuses a 0-keep request for real regardless
    // (backend stage's own tests cover it); this guard just keeps the
    // click itself a true no-op, not a trust boundary.
    if (isBusy(g.id) || autoBusy) return;
    const resolution = buildResolution(g);
    if (!resolution) return;
    setGroupBusy(g.id, true);
    clearGroupError(g.id);
    const d = await postJSON("/api/duplicates/resolve", { csrf, resolutions: [resolution] });
    setGroupBusy(g.id, false);
    if (d.error) { setGroupErrorMsg(g.id, d.error); return; }
    const quarantined = d.quarantined || [];
    const errors = d.errors || [];
    if (quarantined.length) {
      setResolvedByGroup((prev) => ({ ...prev, [g.id]: { quarantined } }));
      onResolved && onResolved();
    }
    if (errors.length) {
      setGroupErrorMsg(g.id, errors[0].error || "some files could not be quarantined");
    } else {
      clearGroupError(g.id);
    }
  };

  const undoGroup = async (g) => {
    const info = resolvedByGroup[g.id];
    if (!info || isBusy(g.id) || autoBusy) return; // same explicit-guard rule as resolve
    setGroupBusy(g.id, true);
    const items = info.quarantined || [];
    const results = await Promise.all(
      items.map((q) => postJSON("/api/duplicates/undo", { csrf, quarantine_path: q.quarantine_path })));
    setGroupBusy(g.id, false);

    // Partition by real outcome instead of bailing whole-group on ANY
    // failure -- caught in adversarial review: a mixed result used to leave
    // successfully-restored files still rendering "QUARANTINED" forever
    // (the card never re-read which items actually came back), and made a
    // retry impossible, since the backend correctly refuses re-undoing a
    // file that already restored. Only the items that genuinely failed stay
    // tracked as quarantined, so a second Undo click retries just those.
    const stillQuarantined = [];
    let firstError = null;
    items.forEach((q, i) => {
      const r = results[i];
      if (!r || r.error || r.ok === false) {
        stillQuarantined.push(q);
        if (!firstError) firstError = r && r.error;
      }
    });
    const restoredCount = items.length - stillQuarantined.length;

    if (stillQuarantined.length) {
      setResolvedByGroup((prev) => ({ ...prev, [g.id]: { quarantined: stillQuarantined } }));
      setGroupErrorMsg(g.id, "undo failed for " + stillQuarantined.length + " of " + items.length +
        " file(s)" + (firstError ? " — " + firstError : "") +
        (restoredCount ? " (" + restoredCount + " other file(s) restored)" : ""));
    } else {
      setResolvedByGroup((prev) => {
        const next = { ...prev };
        delete next[g.id];
        return next;
      });
      clearGroupError(g.id);
    }
    // Fire on ANY real restore, not only a fully-clean undo -- a partial
    // success still changed the catalog and the grid should reflect it.
    if (restoredCount) onResolved && onResolved();
  };

  // ---- Auto-resolve all: its OWN, separate, harder-to-misclick gate ----
  const pendingGroups = groups.filter((g) => !resolvedByGroup[g.id]);
  const autoResolutions = pendingGroups.map((g) => buildResolution(g)).filter(Boolean);
  const autoGroupCount = autoResolutions.length;
  const autoFileCount = autoResolutions.reduce((n, r) => n + r.remove.length, 0);
  const autoSkippedCount = pendingGroups.length - autoGroupCount;

  const runAutoResolve = async () => {
    // Same explicit-guard rule: the confirm button's disabled state is UX
    // polish, this early return is the actual gate against a double-fire.
    if (autoBusy || !autoResolutions.length) return;
    setAutoBusy(true);
    setAutoError("");
    const d = await postJSON("/api/duplicates/resolve", { csrf, resolutions: autoResolutions });
    setAutoBusy(false);
    if (d.error) { setAutoError(d.error); return; }
    const byGroup = {};
    (d.quarantined || []).forEach((q) => {
      if (!q.group_id) return;
      (byGroup[q.group_id] || (byGroup[q.group_id] = [])).push(q);
    });
    if (Object.keys(byGroup).length) {
      setResolvedByGroup((prev) => {
        const next = { ...prev };
        Object.keys(byGroup).forEach((gid) => { next[gid] = { quarantined: byGroup[gid] }; });
        return next;
      });
      onResolved && onResolved();
    }
    const errors = d.errors || [];
    if (errors.length) {
      setGroupErrors((prev) => {
        const next = { ...prev };
        errors.forEach((e) => { if (e.group_id) next[e.group_id] = e.error || "resolve failed"; });
        return next;
      });
      setAutoError(errors.length + " of " + autoResolutions.length +
        " group(s) could not be resolved — see the group card(s) below");
    }
    setAutoConfirmOpen(false);
  };

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgdr-slab" role="dialog" aria-label="Duplicate Review">
          <div className="mgv-titlerow">
            <div className="mgv-title">Duplicate Review</div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {!data && !err && <div className="mgh-loading">scanning for duplicates…</div>}
          {err && <div className="mgh-loading">couldn't load duplicate data — {err}</div>}

          {data && groups.length === 0 && (
            <div className="mgdr-clear">
              <div className="mgdr-clear-icon">✓</div>
              <div>All clear — no duplicate copies found.</div>
            </div>
          )}

          {data && groups.length > 0 && (
            <>
              <div className="mgdr-toolbar">
                <div className="mgdr-summary">
                  <b>{pendingCount}</b> group{pendingCount !== 1 ? "s" : ""} pending ·{" "}
                  <b>{fmtBytes(pendingReclaimable)}</b> reclaimable
                  {resolvedCount > 0 ? " · " + resolvedCount + " resolved this session" : ""}
                  {countChips.length ? " · " + countChips.join(" · ") : ""}
                </div>
                <button type="button" className="mgdr-autobtn"
                  disabled={!autoGroupCount || autoBusy}
                  title={autoGroupCount
                    ? "Quarantine every pending group's current keep/remove selection in one go"
                    : "No pending group has a keeper selected"}
                  onClick={() => setAutoConfirmOpen(true)}>
                  ⚡ Auto-resolve all{autoGroupCount ? " (" + autoGroupCount + ")" : ""}
                </button>
              </div>

              {pendingCount === 0 && (
                <div className="mgdr-allresolved">
                  ✓ Every pending group has been resolved this session — quarantined files stay
                  listed below in case you want to Undo one.
                </div>
              )}

              {autoConfirmOpen && (
                <div className="mgdr-autoconfirm" role="alertdialog" aria-label="Confirm auto-resolve all">
                  <div className="mgdr-autoconfirm-head">⚠ Auto-resolve all pending groups?</div>
                  <p className="mgdr-autoconfirm-body">
                    This will quarantine <b>{autoFileCount}</b> file{autoFileCount !== 1 ? "s" : ""} across{" "}
                    <b>{autoGroupCount}</b> group{autoGroupCount !== 1 ? "s" : ""} — moved to{" "}
                    <code>_duplicates/</code>, not deleted; each one can still be undone
                    individually afterward.
                    {autoSkippedCount > 0 && (
                      <> {autoSkippedCount} group{autoSkippedCount !== 1 ? "s" : ""} with no keeper
                      selected will be skipped, untouched.</>
                    )}
                  </p>
                  {autoError && <div className="mgdr-grouperr">⚠ {autoError}</div>}
                  <div className="mgdr-autoconfirm-actions">
                    <button type="button" className="mgdr-autocancel" disabled={autoBusy}
                      onClick={() => { setAutoConfirmOpen(false); setAutoError(""); }}>
                      Cancel
                    </button>
                    <button type="button" className="mgdr-autogo"
                      disabled={autoBusy || !autoResolutions.length}
                      onClick={runAutoResolve}>
                      {autoBusy ? "Quarantining…" : "Quarantine " + autoFileCount + " file" + (autoFileCount !== 1 ? "s" : "")}
                    </button>
                  </div>
                </div>
              )}

              <div className="mgdr-groups">
                {groups.map((g) => {
                  const keeperPath = keeperByGroup[g.id];
                  const resolved = resolvedByGroup[g.id];
                  const keepCount = keeperPath ? 1 : 0;
                  const busy = isBusy(g.id);
                  const groupErr = groupErrors[g.id];
                  return (
                    <div className={"mgdr-group" + (resolved ? " resolved" : "")} key={g.id}>
                      <div className="mgdr-group-head">
                        <span className="mgdr-group-label">{MATCH_LABEL(g)}</span>
                        <span className="mgdr-group-meta">
                          {g.members.length} file{g.members.length !== 1 ? "s" : ""} ·{" "}
                          {fmtBytes(g.reclaimable_bytes)} reclaimable
                        </span>
                      </div>
                      <div className="mgdr-members">
                        {g.members.map((m) => {
                          const isKeeper = m.path === keeperPath;
                          return (
                            <div className={"mgdr-tile" + (isKeeper ? " keep" : " remove")} key={m.path}>
                              <div className="mgdr-thumb">
                                <img src={m.thumb} alt="" loading="lazy" draggable={false} />
                                {m.is_video ? <span className="mgdr-vglyph">▶</span> : null}
                                {resolved ? (
                                  isKeeper
                                    ? <span className="mgdr-keeper">KEPT</span>
                                    // Per-tile, not per-group: a partial Undo can restore
                                    // some members of a resolved group while others stay
                                    // quarantined (a failed backend restore, e.g. the
                                    // original path got reoccupied). original_path is the
                                    // quarantine record's pre-move path, i.e. this tile's
                                    // own m.path -- checking membership here instead of
                                    // trusting the group-level `resolved` flag alone is
                                    // what keeps this label honest after a mixed result.
                                    : resolved.quarantined.some((q) => q.original_path === m.path)
                                      ? <span className="mgdr-quarantined">QUARANTINED</span>
                                      : <span className="mgdr-restored">RESTORED</span>
                                ) : (
                                  <button type="button"
                                    className={"mgdr-toggle" + (isKeeper ? " on" : "")}
                                    disabled={busy || autoBusy}
                                    title={isKeeper
                                      ? "Click to deselect this as the keeper"
                                      : "Keep this copy instead"}
                                    onClick={() => toggleKeeper(g.id, m.path)}>
                                    {isKeeper ? "✓ keep" : "✕ remove"}
                                  </button>
                                )}
                              </div>
                              <div className="mgdr-tile-meta">
                                <MemberStars rating={m.rating} />
                                <span className="mgdr-dims">
                                  {m.width && m.height ? m.width + "×" + m.height : "—"}
                                </span>
                                <span className="mgdr-date">{(m.created_at || "").slice(0, 10) || "—"}</span>
                                <span className="mgdr-size">{fmtBytes(m.size)}</span>
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      {groupErr && <div className="mgdr-grouperr">⚠ {groupErr}</div>}

                      <div className="mgdr-groupfoot">
                        {resolved ? (
                          <>
                            <span className="mgdr-resolvednote">
                              ✓ Quarantined {resolved.quarantined.length} file{resolved.quarantined.length !== 1 ? "s" : ""}
                            </span>
                            <button type="button" className="mgdr-undo"
                              disabled={busy || autoBusy}
                              onClick={() => undoGroup(g)}>
                              {busy ? "Undoing…" : "↺ Undo"}
                            </button>
                          </>
                        ) : (
                          <button type="button" className="mgdr-resolve"
                            disabled={keepCount === 0 || busy || autoBusy}
                            title={keepCount === 0 ? "Select a keeper first" : undefined}
                            onClick={() => resolveGroup(g)}>
                            {busy ? "Resolving…" : (keepCount
                              ? "Resolve — quarantine " + (g.members.length - 1)
                              : "Resolve")}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
