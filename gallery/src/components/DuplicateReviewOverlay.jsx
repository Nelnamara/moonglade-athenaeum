import React, { useState } from "react";
import useDuplicateReview, { MATCH_LABEL, fmtBytes, bestKeeperPath } from "../hooks/useDuplicateReview.js";
import "../styles/overlays.css";
import "../styles/duplicate-review-overlay.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* Duplicate Review overlay — the sixth designed nav overlay to port, opened
   from Collection Health's Duplicates/Reclaimable tiles (HealthOverlay.jsx).

   STAGE 3 (2026-08-02): wired the real Resolve / Undo / Auto-resolve-all
   actions on top of the read-only stage below, against the backend stage's
   POST /api/duplicates/resolve and POST /api/duplicates/undo
   (moonglade_gallery.py, LOGIN tier, explicit-CSRF class -- _check_csrf(),
   same helper /api/users/add etc. use). `boot.csrf` (threaded down from
   App.jsx, same token every other CSRF'd POST in this app rides) is the
   token; `onResolved` (accepted unused by the prior stage) now actually
   fires App's afterMutation() so the gallery grid reloads once a duplicate
   copy leaves the visible library.

   DATA LAYER (2026-08-03): the fetch/keeper-selection/resolve/undo/auto-
   resolve state that used to live inline here was mechanically lifted into
   ../hooks/useDuplicateReview.js, the SAME pattern useHealth.js/useFolio.js/
   useImageDetails.js/useControlPanel.js already set this session (see that
   hook's own header comment) -- so the new mobile screen
   (DuplicateReviewMobile.jsx, nested inside HealthMobile.jsx's own pushed
   Health screen) consumes the identical fetch and the identical real
   mutations, never a second copy of any of it. This file's own JSX/render
   is UNCHANGED by that move -- only the state/effects/handlers moved.

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

   CORRECTION (2026-08-04): a prior version of this comment claimed no locked
   DC mockup exists for this overlay. That was wrong -- design_handoff/
   design_handoff_moonglade_suite/Duplicate Review.dc.html is a real, complete
   244-line mockup that was never opened when this file was first built. The
   header below (← Library / divider / ⧉ label / filter-by-title search),
   the hero stat block, the "sorted by similarity" caption, the color-coded
   similarity badge, the "★ suggested keep" ribbon, and the "Skip for now"
   button are ported from that real file per the docs/DECISIONS.md audit
   entry "Design-fidelity audit... punch list" -- not invented, and not from
   the classic /duplicates page. The keep/remove toggle pill placement and
   resolved-card dim treatment already matched the DC's own interaction
   design even before this correction.

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

export function MemberStars({ rating }) {
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

// filename portion of a member's path -- the closest real field this backend
// has to the DC's "title" search (no prompt/title is carried on a duplicate
// group's member records; filename is what a user actually recognizes a
// specific file by, and is the same value MemberStars' sibling meta row
// already shows nowhere else -- so this doesn't duplicate existing UI).
function baseName(p) {
  if (!p) return "";
  const parts = String(p).replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || "";
}

// Duplicate Review.dc.html's color-coded similarity badge (red>=100, gold>=90,
// purple>=80, blue below). Only the near_duplicate tier carries a real
// closeness_pct (useDuplicateReview.js's own contract); same_media/
// identical_file ARE exact matches by definition (same media_id or
// byte-identical content), so they get the design's red/100% treatment
// honestly rather than a fabricated number. same_seed has no percentage
// concept at all -- it gets the design's lowest (blue) tier as a plain tag.
function similarityTier(g) {
  if (g.matchType === "same_media" || g.matchType === "identical_file") return "tier-red";
  if (g.matchType === "near_duplicate") {
    const pct = Number(g.closeness_pct) || 0;
    if (pct >= 100) return "tier-red";
    if (pct >= 90) return "tier-gold";
    if (pct >= 80) return "tier-purple";
    return "tier-blue";
  }
  return "tier-blue";
}

export default function DuplicateReviewOverlay({ onClose, onResolved, boot }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const csrf = (boot && boot.csrf) || "";
  const {
    data, err, groups, countChips,
    resolvedCount, pendingCount, pendingReclaimable,
    isBusy, keeperByGroup, resolvedByGroup, groupErrors,
    toggleKeeper, resolveGroup, undoGroup,
    autoConfirmOpen, setAutoConfirmOpen, autoBusy, autoError, setAutoError,
    autoResolutions, autoGroupCount, autoFileCount, autoSkippedCount,
    runAutoResolve,
  } = useDuplicateReview({ csrf, onResolved });

  // Design_handoff's {{ q }}/onSearch (Duplicate Review.dc.html:35) -- a
  // client-side filter over the already-fetched groups, same as the design's
  // own binding implies (no server round-trip). Matches against filename
  // (see baseName() above), case-insensitive.
  const [q, setQ] = useState("");
  const qNorm = q.trim().toLowerCase();

  // Duplicate Review.dc.html:111's "Skip for now" -- a session-local dismiss,
  // not a mutation (nothing is quarantined/touched server-side). Reappears on
  // reopen, same as the design's own un-persisted demo state implies. Skipped
  // groups still count toward the real pending/reclaimable totals above --
  // skipping hides a card from view, it doesn't change what's actually true
  // about the library.
  const [skipped, setSkipped] = useState({});

  const visibleGroups = groups.filter((g) => {
    if (skipped[g.id] && !resolvedByGroup[g.id]) return false;
    if (!qNorm) return true;
    return (g.members || []).some((m) => baseName(m.path).toLowerCase().includes(qNorm));
  });

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgdr-slab" role="dialog" aria-label="Duplicate Review">
          <div className="mgdr-headrow">
            <div className="mgdr-back" onClick={onClose} title="Back to the library">← Library</div>
            <div className="mgdr-headdiv" aria-hidden="true" />
            <div className="mgdr-headlabel">⧉ Duplicate Review</div>
            <div className="mgdr-headspacer" />
            <div className="mgdr-search">
              <span className="mgdr-search-icon" aria-hidden="true">⌕</span>
              <input type="text" placeholder="filter by filename…" value={q}
                onChange={(e) => setQ(e.target.value)} />
            </div>
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
              <div className="mgdr-hero">
                <div className="mgdr-hero-eyebrow">The Moonglade Athenaeum · housekeeping</div>
                <h1 className="mgdr-hero-title">Duplicate Review</h1>
                <div className="mgdr-hero-stats">
                  <div className="mgdr-hero-stat">
                    <b>{pendingCount}</b>
                    <span>group{pendingCount !== 1 ? "s" : ""}{groups.length !== pendingCount ? " of " + groups.length : ""}</span>
                  </div>
                  <div className="mgdr-hero-stat">
                    <b>{groups.reduce((n, g) => n + (g.members || []).length, 0)}</b>
                    <span>images involved</span>
                  </div>
                  <div className="mgdr-hero-stat">
                    <b>{fmtBytes(pendingReclaimable)}</b>
                    <span>reclaimable</span>
                  </div>
                </div>
              </div>
              <div className="mgdr-caption">Sorted by highest reclaimable size first · the starred frame is the suggested keeper</div>

              {qNorm && visibleGroups.length === 0 && (
                <div className="mgdr-nomatch">No filenames in any pending group match "{q}".</div>
              )}

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
                {visibleGroups.map((g) => {
                  const keeperPath = keeperByGroup[g.id];
                  const resolved = resolvedByGroup[g.id];
                  const keepCount = keeperPath ? 1 : 0;
                  const busy = isBusy(g.id);
                  const groupErr = groupErrors[g.id];
                  return (
                    <div className={"mgdr-group" + (resolved ? " resolved" : "")} key={g.id}>
                      <div className="mgdr-group-head">
                        <span className={"mgdr-group-label " + similarityTier(g)}>{MATCH_LABEL(g)}</span>
                        <span className="mgdr-group-meta">
                          {g.members.length} file{g.members.length !== 1 ? "s" : ""} ·{" "}
                          {fmtBytes(g.reclaimable_bytes)} reclaimable
                        </span>
                      </div>
                      <div className="mgdr-members">
                        {(() => { const suggestedPath = bestKeeperPath(g); return g.members.map((m) => {
                          const isKeeper = m.path === keeperPath;
                          const isSuggested = m.path === suggestedPath;
                          return (
                            <div className={"mgdr-tile" + (isKeeper ? " keep" : " remove")} key={m.path}>
                              <div className="mgdr-thumb">
                                <img src={m.thumb} alt="" loading="lazy" draggable={false} />
                                {m.is_video ? <span className="mgdr-vglyph">▶</span> : null}
                                {!resolved && isSuggested ? <span className="mgdr-ribbon">★ suggested keep</span> : null}
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
                        }); })()}
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
                          // Duplicate Review.dc.html:109-111 -- Resolve + Skip as a
                          // gap:8px pair (design's own row), pushed right via the
                          // wrapper (not Resolve itself) to match this app's other
                          // footer-action convention (e.g. Undo above).
                          <div className="mgdr-footactions">
                            <button type="button" className="mgdr-resolve"
                              disabled={keepCount === 0 || busy || autoBusy}
                              title={keepCount === 0 ? "Select a keeper first" : undefined}
                              onClick={() => resolveGroup(g)}>
                              {busy ? "Resolving…" : (keepCount
                                ? "Resolve — keep 1, remove " + (g.members.length - 1)
                                : "Resolve")}
                            </button>
                            {/* Skip leaves the group untouched, same as just not
                                clicking Resolve -- an explicit "I looked, not now"
                                distinct from silently scrolling past. */}
                            <button type="button" className="mgdr-skip"
                              disabled={busy || autoBusy}
                              title="Leave this group as-is for now"
                              onClick={() => setSkipped((prev) => ({ ...prev, [g.id]: true }))}>
                              Skip for now
                            </button>
                          </div>
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
