import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../api.js";

/* useDuplicateReview -- DuplicateReviewOverlay.jsx's fetch/state/keeper-
   selection/resolve/undo/auto-resolve logic, mechanically lifted out
   (2026-08-03) into its own hook so a new mobile surface
   (DuplicateReviewMobile.jsx) can consume the EXACT same GET /api/duplicates
   data, keeper-radio selection model, and real POST /api/duplicates/resolve
   + POST /api/duplicates/undo mutations -- never a second, drifting copy of
   any of it, and never a new or parallel write path. Matches the
   useHealth.js/useFolio.js/useImageDetails.js/useControlPanel.js precedent
   this session already set (see those files' own header comments): Duplicate
   ReviewOverlay.jsx -- the ONE place this state has ever lived -- is
   refactored to CONSUME this hook rather than left holding a second copy.

   A byte-for-byte lift of DuplicateReviewOverlay.jsx's own state/effects/
   handlers, NOT a rewrite -- see that file's own (preserved) header comment
   for the full rationale behind the keeper-radio model, the confirm-gate
   weights, and the backend contract this mirrors exactly (path, not
   media_id, disambiguates a member; keep is ONE object, remove is an array;
   resolve is per-item not all-or-nothing; undo is per-item and partitions a
   batch's real per-file outcome rather than bailing whole-group on any one
   failure).

   `csrf` is the one primitive input (not a whole `boot` object) -- matching
   useControlPanel.js's own documented call that `boot` (mark_url/build_stamp)
   is never a hook input because no fetch/poll/action logic reads it; here,
   csrf IS read (every mutating POST rides it), so it -- and only it -- is
   threaded in. `onResolved` fires on any REAL restore/resolve (a partial
   undo included, matching the original's "fire on any real restore, not only
   a fully-clean undo" rule) -- WHAT that does next (reload a grid, close an
   overlay) stays each consumer's own call, exactly like useHealth.js's
   documented split for its own onModelFilter/onTagFilter/onLoraFilter/
   onOpenDuplicates props. */

export const MATCH_LABEL = (g) => {
  switch (g.matchType) {
    case "same_media": return "Same generation, saved twice";
    case "identical_file": return "Identical file";
    case "same_seed": return "Same seed";
    case "near_duplicate":
      return "Near-duplicate (" + Math.round(g.closeness_pct) + "% match)";
    default: return g.matchType;
  }
};

export const COUNT_LABEL = {
  same_media: "same generation",
  identical_file: "identical file",
  same_seed: "same seed",
  near_duplicate: "near-duplicate",
};

export function fmtBytes(b) {
  if (b == null) return "—";
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(0) + " KB";
  if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB";
  return (b / 1073741824).toFixed(2) + " GB";
}

// Ported faithfully from the DC handoff's own default-keeper rule (see
// DuplicateReviewOverlay.jsx's original header comment): highest rating
// wins, ties go to the FIRST member found -- a strict `>`, never `>=`.
export function bestKeeperPath(g) {
  let bestIdx = 0, bestScore = -1;
  (g.members || []).forEach((m, i) => {
    const n = Number(m.rating) || 0;
    if (n > bestScore) { bestScore = n; bestIdx = i; }
  });
  const best = g.members && g.members[bestIdx];
  return best ? best.path : null;
}

export default function useDuplicateReview({ csrf, onResolved } = {}) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [keeperByGroup, setKeeperByGroup] = useState({});   // group.id -> path | null
  const [resolvedByGroup, setResolvedByGroup] = useState({}); // group.id -> { quarantined: [...] }
  const [busyGroups, setBusyGroups] = useState(() => new Set()); // group.ids mid-resolve/undo
  const [groupErrors, setGroupErrors] = useState({});        // group.id -> message
  const [autoConfirmOpen, setAutoConfirmOpen] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);
  const [autoError, setAutoError] = useState("");

  // Mount-time fetch, dead-flag guarded -- the SAME pattern
  // useHealth.js/useFolio.js/useImageDetails.js already use. Both real
  // consumers (the desktop overlay, the mobile screen nested inside
  // HealthMobile's own pushed screen) mount fresh on every open, so this
  // needs no lazy/ensureLoaded indirection -- a plain effect covers both.
  useEffect(() => {
    let dead = false;
    apiGet("/api/duplicates")
      .then((d) => {
        if (dead) return;
        if (d.error) { setErr(d.error); return; }
        setData(d);
        const initKeepers = {};
        (d.groups || []).forEach((g) => { initKeepers[g.id] = bestKeeperPath(g); });
        setKeeperByGroup(initKeepers);
      });
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

  // Resets ONE group's keeper back to the auto-computed default (the real
  // fix for what the DC mock's own per-group "Clear" button demo'd as a
  // global imageStates wipe -- see DuplicateReviewMobile.jsx's own header
  // comment) -- undoes a manual re-pick for THIS group only.
  const resetKeeper = (g) => {
    setKeeperByGroup((prev) => ({ ...prev, [g.id]: bestKeeperPath(g) }));
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
    // attribute alone (see docs/DECISIONS.md's "Calibration" section / the
    // original overlay's own header comment for the real precedent this
    // guards against). The server refuses a 0-keep request for real
    // regardless; this guard just keeps the click itself a true no-op.
    if (isBusy(g.id) || autoBusy) return;
    const resolution = buildResolution(g);
    if (!resolution) return;
    setGroupBusy(g.id, true);
    clearGroupError(g.id);
    const d = await apiPost("/api/duplicates/resolve", { csrf, resolutions: [resolution] });
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
      items.map((q) => apiPost("/api/duplicates/undo", { csrf, quarantine_path: q.quarantine_path })));
    setGroupBusy(g.id, false);

    // Partition by real outcome instead of bailing whole-group on ANY
    // failure -- a mixed result must not leave successfully-restored files
    // still rendering "QUARANTINED" forever, and must not block a retry on
    // the ones that genuinely failed (the backend correctly refuses
    // re-undoing a file that already restored). Only the items that
    // genuinely failed stay tracked as quarantined, so a second Undo click
    // retries just those.
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
    const d = await apiPost("/api/duplicates/resolve", { csrf, resolutions: autoResolutions });
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

  return {
    data, err,
    groups, counts, countChips,
    resolvedCount, pendingCount, pendingReclaimable,
    isBusy, keeperByGroup, resolvedByGroup, groupErrors,
    toggleKeeper, resetKeeper, buildResolution, resolveGroup, undoGroup,
    autoConfirmOpen, setAutoConfirmOpen, autoBusy, autoError, setAutoError,
    pendingGroups, autoResolutions, autoGroupCount, autoFileCount, autoSkippedCount,
    runAutoResolve,
  };
}
