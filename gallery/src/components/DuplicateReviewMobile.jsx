import React, { useState } from "react";
import useDuplicateReview, { MATCH_LABEL, fmtBytes } from "../hooks/useDuplicateReview.js";
import { MemberStars } from "./DuplicateReviewOverlay.jsx";
import MobileSheet from "./MobileSheet.jsx";
import "../styles/overlays.css";
import "../styles/control-mobile.css";
import "../styles/duplicate-review-overlay.css";
import "../styles/duplicate-review-mobile.css";

/* Duplicate Review -- mobile screen (design spec: "Duplicate Review Mobile.dc.html",
   design_handoff/design_handoff_moonglade_suite/, read in full 2026-08-03). Nested
   inside HealthMobile.jsx's own pushed Health screen via a SECOND, locally-owned
   MobileScreen instance -- matching ControlMobile.jsx's own Branding drill-in
   precedent exactly (a push-within-a-push, the caller owns its own open/closing
   pair, see HealthMobile.jsx). Entry point: Health's Duplicates/Reclaimable stat
   tiles, previously non-clickable (a disclosed gap from an earlier increment) --
   now real.

   DATA/MUTATION LAYER: useDuplicateReview.js, the EXACT hook DuplicateReviewOverlay.jsx
   (desktop) now consumes too -- the same live GET /api/duplicates, the same real
   POST /api/duplicates/resolve and POST /api/duplicates/undo (moonglade_gallery.py,
   LOGIN tier, explicit-CSRF class, READ_ONLY-gated, quarantine-only -- see that
   hook's own header comment and the backend routes' own docstrings). No new
   endpoint, no forked mutation logic -- every real safety property already
   reviewed on desktop (path-not-media_id disambiguation, server-side keep-count-0
   refusal, per-item not all-or-nothing resolve, per-item partitioned undo outcome)
   applies here unchanged, because it's the same code.

   REAL, DISCLOSED DEVIATIONS FROM THE DC MOCK (per this project's own "designs
   win, but disclose real-app-truth conflicts" precedent used on every prior
   mobile surface this session):

   1. NO PER-GROUP "TITLE" EXISTS. The mock's own demo data invents flavor names
      per group ("Void at treeline", "Hands over water (re-roll)") -- GET
      /api/duplicates carries no such field (matchType + members only). This
      screen shows the REAL matchType label (MATCH_LABEL(), the exact string
      desktop's own card header shows) wherever the mock shows its invented title,
      never a fabricated name.

   2. TAP-TO-TOGGLE IS THE REAL KEEPER-RADIO MODEL, not the mock's literal
      per-tile independent toggle. The mock's own comment self-labels this
      "simplified... for demo," and its raw per-tile toggle (mark ANY subset of
      tiles "removed" independently) cannot represent a valid resolution for the
      real backend contract, which takes exactly ONE `keep` object and an array
      `remove` (moonglade_gallery.py's POST /api/duplicates/resolve; see
      _validate_duplicate_pair()). So tapping a tile here reuses the EXACT real,
      already-tested keeper-radio model desktop's own toggleKeeper already
      implements: tapping a non-keeper tile makes IT the keeper (every other tile
      in the group becomes "marked for removal" automatically); tapping the
      current keeper deselects it to keep-count 0 (Resolve disables, matching
      the server's own real refusal for that case) rather than forcing a keeper
      at all times. This is dressed in the mock's own visual language -- a red
      wash + X mark every non-keeper tile, exactly the "a red border marks a file
      for removal" behavior the brief calls for -- just driven by one real,
      contract-valid selection instead of an unconstrained per-tile toggle.
   3. PER-GROUP "CLEAR": the mock's own demo code resets EVERY group's tap state
      globally from a single group's Clear button (`imageStates: {}}` on
      `this.setState`) -- read closely, that looks like a bug in the demo, not a
      real per-group affordance. Here, Clear resets ONLY the tapped group's own
      keeper selection back to the computed default (the highest-rated member,
      ties to the first found -- resetKeeper() in the shared hook), scoped
      correctly to the card whose button was pressed.
   4. AN "AUTO-RESOLVE ALL" TRIGGER BUTTON WAS ADDED. The mock's own script
      defines `showAutoModal`/confirmAuto/cancelAuto state and handlers, but no
      control in the visible mock crop ever sets `showAutoModal: true` -- nothing
      opens it. Since the task explicitly calls for this real, gated flow to
      exist and be reachable, a toolbar button was added (mirroring desktop's own
      real "⚡ Auto-resolve all (N)" affordance) to open it.
   5. SWIPE GESTURES ARE OUT OF SCOPE THIS PASS (explicit instruction) -- tap-to-
      toggle only; no swipe-to-resolve, no swipe-to-undo.
   6. PARTIAL-UNDO HONESTY: a resolved group's per-tile KEPT/QUARANTINED/RESTORED
      tri-state is ported verbatim from desktop (checking each tile's own
      membership in the undo record's real per-file outcome, not trusting the
      group-level "resolved" flag alone) -- a partial Undo (some files restore,
      others don't -- a known real scenario, e.g. the original location got
      reoccupied) is never silently hidden here either; the group's own error
      banner (groupErrors[g.id]) names exactly how many files stayed quarantined
      and why, same as desktop.

   CONFIRM-GATE WEIGHTS (the one deliberate, REAL difference from desktop, named
   explicitly per this build's own brief -- not an oversight of
   DuplicateReviewOverlay.jsx's own "no extra confirm" call, which stays correct
   for desktop's reasons):
     - per-group Resolve: A bottom-sheet confirm (MobileSheet.jsx, the SAME shared
       bottom-sheet chrome every other mobile confirm/sheet in this app already
       uses) naming the real file count about to be quarantined. Desktop's own
       "no extra confirm" call rests on the keep/remove choice being fully
       visible and already deliberately toggled right in the card; a touch
       surface's tap targets are smaller and a mis-tap easier, so the design
       calls for -- and this build adds -- one explicit confirm tap here.
     - Auto-resolve-all: a CENTERED modal (the design's own shape, distinct from
       the bottom sheet above) naming the real blast radius -- "N files across M
       groups" -- computed live from the CURRENT keeper selections via the shared
       hook's own autoFileCount/autoGroupCount, never a placeholder number. */

export default function DuplicateReviewMobile({ csrf, onResolved }) {
  const {
    data, err, groups, countChips,
    resolvedCount, pendingCount, pendingReclaimable,
    isBusy, keeperByGroup, resolvedByGroup, groupErrors,
    toggleKeeper, resetKeeper, buildResolution, resolveGroup, undoGroup,
    autoConfirmOpen, setAutoConfirmOpen, autoBusy, autoError, setAutoError,
    autoResolutions, autoGroupCount, autoFileCount, autoSkippedCount,
    runAutoResolve,
  } = useDuplicateReview({ csrf, onResolved });

  // Per-group Resolve confirm -- a bottom sheet, MobileSheet.jsx's own
  // open/closing ownership contract (280ms exit, matching every other mobile
  // sheet's own timing). See header comment's "confirm-gate weights" section
  // for why this exists on mobile when desktop's own per-group Resolve has no
  // equivalent dialog at all.
  const [confirmGroupId, setConfirmGroupId] = useState(null);
  const [confirmClosing, setConfirmClosing] = useState(false);
  const askResolve = (g) => setConfirmGroupId(g.id);
  const closeConfirm = () => {
    setConfirmClosing(true);
    setTimeout(() => { setConfirmGroupId(null); setConfirmClosing(false); }, 280);
  };
  const confirmGroup = groups.find((g) => g.id === confirmGroupId) || null;
  const confirmResolution = confirmGroup ? buildResolution(confirmGroup) : null;
  const confirmRemoveCount = confirmResolution ? confirmResolution.remove.length : 0;
  const doConfirmedResolve = () => {
    if (!confirmGroup) return;
    closeConfirm();
    resolveGroup(confirmGroup);
  };

  if (!data && !err) return <div className="mgh-loading">scanning for duplicates…</div>;
  if (err) return <div className="mgh-loading">couldn't load duplicate data — {err}</div>;

  if (groups.length === 0) {
    return (
      <div className="mgdr-clear">
        <div className="mgdr-clear-icon">✓</div>
        <div>All clear — no duplicate copies found.</div>
      </div>
    );
  }

  return (
    <>
      <div className="ctm-statgrid" style={{ marginBottom: 14 }}>
        <div className="ctm-statcard">
          <div className="ctm-statnum">{pendingCount}</div>
          <div className="ctm-statlabel">Groups pending</div>
        </div>
        <div className="ctm-statcard">
          <div className="ctm-statnum gold">{fmtBytes(pendingReclaimable)}</div>
          <div className="ctm-statlabel">Reclaimable</div>
        </div>
      </div>

      <div className="mgdrm-toolbar">
        <div className="mgdr-summary">
          {resolvedCount > 0 ? resolvedCount + " resolved this session" : "Tap a copy to keep it instead"}
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

      <div className="mgdr-groups mgdrm-groups">
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
                    <div className={"mgdr-tile mgdrm-tile" + (isKeeper ? "" : " removed") + (busy || autoBusy ? " busy" : "")}
                      key={m.path}>
                      <div className="mgdr-thumb"
                        onClick={() => { if (!busy && !autoBusy && !resolved) toggleKeeper(g.id, m.path); }}
                        style={{ cursor: resolved ? "default" : "pointer" }}>
                        <img src={m.thumb} alt="" loading="lazy" draggable={false} />
                        {m.is_video ? <span className="mgdr-vglyph">▶</span> : null}
                        {resolved ? (
                          isKeeper
                            ? <span className="mgdr-keeper">KEPT</span>
                            // Per-tile, not per-group -- see header comment
                            // point 6: a partial Undo can restore some members
                            // of a resolved group while others stay quarantined.
                            : resolved.quarantined.some((q) => q.original_path === m.path)
                              ? <span className="mgdr-quarantined">QUARANTINED</span>
                              : <span className="mgdr-restored">RESTORED</span>
                        ) : isKeeper ? (
                          <span className="mgdr-keeper">KEEP</span>
                        ) : (
                          <span className="mgdrm-removed-x" aria-hidden="true">✕</span>
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
                  <>
                    <button type="button" className="mgdrm-clearbtn"
                      disabled={busy || autoBusy}
                      onClick={() => resetKeeper(g)}>
                      Clear
                    </button>
                    <button type="button" className="mgdr-resolve"
                      disabled={keepCount === 0 || busy || autoBusy}
                      title={keepCount === 0 ? "Select a keeper first" : undefined}
                      onClick={() => askResolve(g)}>
                      {keepCount ? "Resolve — quarantine " + (g.members.length - 1) : "Resolve"}
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Per-group Resolve confirm -- bottom sheet, see header comment. */}
      <MobileSheet open={!!confirmGroupId} closing={confirmClosing} onClose={closeConfirm}>
        <div className="mgdrm-confirm-title">
          Quarantine {confirmGroup ? MATCH_LABEL(confirmGroup) : ""}?
        </div>
        <div className="mgdrm-confirm-body">
          {confirmRemoveCount} file{confirmRemoveCount !== 1 ? "s" : ""} will be quarantined
          (moved to <code>_duplicates/</code>) and can be restored later with Undo.
        </div>
        <div className="mgdrm-confirm-actions">
          <button type="button" className="mgdr-autocancel mgdrm-wide" onClick={closeConfirm}>
            Cancel
          </button>
          <button type="button" className="mgdr-autogo mgdrm-wide" onClick={doConfirmedResolve}>
            Quarantine
          </button>
        </div>
      </MobileSheet>

      {/* Auto-resolve-all -- CENTERED modal, the design's own shape, see header
          comment's "confirm-gate weights" section. */}
      {autoConfirmOpen && (
        <div className="mgdrm-automodal-scrim">
          <div className="mgdrm-automodal-card" role="alertdialog" aria-label="Confirm auto-resolve all">
            <div className="mgdr-autoconfirm-head">Auto-resolve all?</div>
            <p className="mgdr-autoconfirm-body">
              This will quarantine <b>{autoFileCount}</b> file{autoFileCount !== 1 ? "s" : ""} across{" "}
              <b>{autoGroupCount}</b> group{autoGroupCount !== 1 ? "s" : ""} — moved to{" "}
              <code>_duplicates/</code>, not deleted; each one can still be undone individually
              afterward.
              {autoSkippedCount > 0 && (
                <> {autoSkippedCount} group{autoSkippedCount !== 1 ? "s" : ""} with no keeper
                selected will be skipped, untouched.</>
              )}
            </p>
            {autoError && <div className="mgdr-grouperr">⚠ {autoError}</div>}
            <div className="mgdr-autoconfirm-actions">
              <button type="button" className="mgdr-autocancel mgdrm-wide" disabled={autoBusy}
                onClick={() => { setAutoConfirmOpen(false); setAutoError(""); }}>
                Cancel
              </button>
              <button type="button" className="mgdr-autogo mgdrm-wide"
                disabled={autoBusy || !autoResolutions.length}
                onClick={runAutoResolve}>
                {autoBusy ? "Quarantining…" : "Proceed"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
