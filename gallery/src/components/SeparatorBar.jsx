import React, { useEffect, useRef, useState } from "react";
import NavSpine from "./NavSpine.jsx";
import CostBadge from "./CostBadge.jsx";
import CustomSlider from "./CustomSlider.jsx";
import ActivityChip from "../notify/ActivityChip.jsx";
import ActivityPanel from "../notify/ActivityPanel.jsx";
import useActivity from "../notify/useActivity.js";
import "../styles/shell.css";

/* The separator bar (DC "Frontend Gallery", §3 of the build map): nav pills ·
   slim-banner toggle · blur toggle · SIZE pill · activity cluster · credits
   chip · slim-state ✦ Generate launcher.

   MEASUREMENT CONTRACT: App wraps this bar's DOM in a ref — its bottom edge
   (sepBottom) is what the advanced-panel and dock workstreams anchor to
   (advanced panel top = sepBottom + 10; dock max-height caps at sepBottom).

   COST-CHIP CONTRACT: this bar mounts the shared <CostBadge compact>, hidden
   until its first onCost push (its idle hint would otherwise be permanent
   noise). It is dormant today — nothing drives it, so it stays hidden; a future
   GenerateDock refit can forward a ref to it to show the desktop price here. The
   ACCOUNT balance chip beside it is this component's own
   markup, fed live from /api/account (credits/cards are real, not the DC's
   hardcoded 46,200/13). */

function lapse(account) {
  // Membership-lapse warning: /api/account ships sub {end, cancel}. Warn ONLY
  // when the subscription will actually stop (cancelAtPeriodEnd) — `end` with
  // cancel:false is a renewal date, and warning on it would be a lie.
  const sub = account && account.sub;
  if (!sub || !sub.end || !sub.cancel) return null;
  const days = Math.ceil((new Date(sub.end + "T23:59:59") - Date.now()) / 86400000);
  if (!isFinite(days)) return null;
  if (days < 0) return "Membership has lapsed — Turbo priority and free cards have stopped.";
  return "Membership lapses in " + days + " day" + (days === 1 ? "" : "s") +
    " — Turbo priority and free cards stop then.";
}

export default function SeparatorBar({
  boot, account,
  slim, onToggleSlim,
  blur, onToggleBlur,
  thumb, thumbMax, onThumb,
  running, dockOpen, onToggleDock,
  onOverlay,
  onClaim, claiming,
}) {
  /* The shared compact price chip. Hidden until its first onCost push reveals it
     (its idle hint would be permanent noise); mounted always, never unmounted. */
  const [hasCost, setHasCost] = useState(false);

  const credits = account && account.credits != null
    ? Number(account.credits).toLocaleString() : "—";
  const cards = account && account.cards != null
    ? Number(account.cards).toLocaleString() : "—";
  const warn = lapse(account);
  // Rich hover tooltip: real paid/free split + per-type card breakdown, all already on
  // /api/account. The paid/free split is the one sensitive number (real spendable balance),
  // so it's GATED behind the privacy blur -- shown only when the grid is unblurred, hidden
  // (with a hint, not silently) when blur is on. Card TYPE counts aren't sensitive, always
  // shown. `blur` true = grid blurred = privacy guard on.
  const paid = account && account.credits_paid;
  const freeCr = account && account.credits_free;
  const hasSplit = typeof paid === "number" && typeof freeCr === "number";
  const cardsBy = (account && account.cards_by ? account.cards_by : []).filter((c) => c.count > 0);
  const cardExpiry = account && account.card_expiry;

  const claimCredits = account && account.claim_credits;

  // Header-docked Activity control (Claude Design handoff 2026-08-09, drift item 39):
  // replaces the old floating #jobs-fab/#jobs-tray with this bar's own ambient activity
  // cluster upgraded into the real trigger+dropdown. Reads jobsStore -- real /api/jobs
  // truth across every job type (generate/panel/import/delete), not the `running` prop
  // above (that same-tab submit/result counter is a separate, narrower signal the
  // Generate composer owns; App.jsx's own comment already flags it as a stopgap for a
  // richer workstream to replace later -- left untouched here, just no longer what
  // drives this control).
  const act = useActivity();
  const actRef = useRef(null);
  useEffect(() => {
    if (!act.open) return undefined;
    const onDoc = (e) => { if (actRef.current && !actRef.current.contains(e.target)) act.close(); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [act.open, act.close]);

  // Trigger chip + anchored dropdown, see the useActivity() comment above for why this
  // reads jobsStore, not the `running` prop. Docks at whichever edge is preferred
  // (act.edge, persisted, default "right") -- a utility/notification control belongs at
  // the row's true OUTER edge on either side, never wedged between other chrome (found
  // live 2026-08-09: it used to sit first in .mgx-sepright, so its right:0-anchored panel
  // fell short of the header's real right edge by however wide credits/claim/generate
  // were). Left/right toggle itself lives inside the panel's own header.
  const activityControl = (
    <div className="mgx-act-wrap" ref={actRef}>
      <ActivityChip jobs={act.jobs} open={act.open} onToggle={act.toggle} title="Activity — recent jobs" />
      {act.open ? (
        <ActivityPanel
          jobs={act.jobs} expandedId={act.expandedId} closing={act.closing}
          onToggleRow={act.toggleRow} onDismiss={act.dismiss}
          onClearFinished={act.clearFinished} onClose={act.close}
          edge={act.edge} onSetEdge={act.setEdge}
          className="mgx-act-panel"
        />
      ) : null}
    </div>
  );

  return (
    <div className="mgx-sep">
      <div className="mgx-sepleft">
        <NavSpine boot={boot} onOverlay={onOverlay} />
        {act.edge === "left" ? activityControl : null}

        {/* slim-banner toggle: chevron flips 180° between states */}
        <button type="button" className={"mgx-sqbtn" + (slim ? " flip" : "")}
          onClick={onToggleSlim}
          title={slim ? "Expand the banner to its hero height" : "Collapse the banner to its slim bar"}
          aria-label={slim ? "Expand the banner" : "Collapse the banner"}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
            strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3.4 9.6L8 5l4.6 4.6M3.4 13h9.2" />
          </svg>
        </button>

        {/* privacy blur: blurred = guarded, wears the metal; unblurred = ruby */}
        <button type="button"
          className={"mgx-sqbtn mgx-blur " + (blur ? "guard mgx-metal" : "off")}
          onClick={onToggleBlur}
          title={blur ? "Unblur the grid" : "Blur the grid again"}
          aria-label={blur ? "Unblur the grid" : "Blur the grid"}
          aria-pressed={blur}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
            strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M1.4 8S3.8 3.6 8 3.6 14.6 8 14.6 8 12.2 12.4 8 12.4 1.4 8 1.4 8z" />
            <circle cx="8" cy="8" r="2" />
            {blur ? <path d="M2.6 13.4L13.4 2.6" /> : null}
          </svg>
        </button>

        {/* SIZE pill — drives the grid's --thumb var (152 … 4-across max). The
            native <input type=range> was swapped for the shared Custom Slider
            (drift §48) in its `compact` skin; onChange hands back the numeric
            value, persisted as mg_gallery_density up in App. */}
        <div className="mgx-size" title="Thumbnail size">
          <span className="mgx-size-lab">SIZE</span>
          <div className="mgx-size-slot">
            <CustomSlider
              compact
              min={152} max={thumbMax} step={4} value={thumb}
              onChange={(v) => onThumb(Math.round(v))}
              ariaLabel="Thumbnail size"
            />
          </div>
        </div>
      </div>

      <div className="mgx-sepright">
        {/* Activity control -- back to its original spot, FIRST in this row (2026-08-10:
            the "move it last so its dropdown reaches the true edge" fix from earlier today
            was never actually shown to/approved -- only "the dropdown is cut off" was. The
            cutoff and the trigger's own position are separable: .mgx-sepright itself now
            owns the positioning context (see shell.css), so the dropdown anchors to the
            row's real right edge regardless of where the trigger sits inside it. */}
        {act.edge === "left" ? null : activityControl}

        {/* shared price chip (hidden until the dock pushes a price) */}
        <span className={"mgx-costslot" + (hasCost ? " has" : "")}>
          <CostBadge compact onCost={() => setHasCost(true)} />
        </span>

        {/* account credits chip: gold billing tooltip drops below, right-anchored */}
        <button type="button" className="mgx-cred"
          onClick={() => window.open("https://pixai.art/en/membership/credit-packs", "_blank", "noopener")}
          aria-label={"Credits " + credits + ", cards " + cards + ". Buy credits or cards on PixAI."}>
          {warn ? <span className="mgx-warndot" aria-hidden="true">!</span> : null}
          <span className="mgx-credval">{credits}</span>
          <span className="mgx-credlab">CREDITS</span>
          <span className="mgx-creddiv" aria-hidden="true" />
          <span className="mgx-credval cards">{cards}</span>
          <span className="mgx-credlab cards">CARDS</span>
          <span className="mgx-credtip" role="tooltip">
            {warn ? <span className="mgx-tipwarn">{warn}</span> : null}
            <span className="mgx-tiprow">
              <span className="mgx-tipk">Credits</span><b className="mgx-tipv">{credits}</b>
            </span>
            {hasSplit ? (
              blur ? (
                <span className="mgx-tipdim">paid / free — hidden while blurred</span>
              ) : (
                <span className="mgx-tipdim">
                  {Number(paid).toLocaleString()} paid · {Number(freeCr).toLocaleString()} free
                </span>
              )
            ) : null}
            <span className="mgx-tiprow head">
              <span className="mgx-tipk">Free cards</span><b className="mgx-tipv">{cards}</b>
            </span>
            {cardsBy.slice(0, 8).map((c) => (
              <span className="mgx-tipcard" key={c.name}>
                <b>{c.count}</b>
                <span className="nm">{c.name}</span>
                {c.category ? <i>{c.category}</i> : null}
              </span>
            ))}
            {cardsBy.length > 8 ? (
              <span className="mgx-tipdim">+{cardsBy.length - 8} more types</span>
            ) : null}
            {cardExpiry ? <span className="mgx-tipdim">soonest expiry: {cardExpiry}</span> : null}
            <span className="mgx-tipfoot">Click to buy credits or cards on PixAI</span>
          </span>
        </button>

        {claimCredits ? (
          <button type="button" className="mgx-claim" onClick={onClaim} disabled={claiming}
            title="Claim your free daily credits">
            <span className="coin">◈</span>
            {claiming ? "claiming…" : "+" + Number(claimCredits).toLocaleString() + " claim"}
          </button>
        ) : null}

        {/* slim-state Generate launcher — the banner's big button is hidden then */}
        {slim ? (
          <button type="button" data-dock-toggle="1"
            className={"mgx-metal mgx-launcher" + (dockOpen ? " mgx-dockdim" : "")}
            onClick={onToggleDock}
            title="Open or close the Generate dock">
            ✦ Generate
          </button>
        ) : null}
      </div>
    </div>
  );
}
