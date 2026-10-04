import React, { useCallback, useEffect, useRef, useState } from "react";
import NavSpine from "./NavSpine.jsx";
import CostBadge from "./CostBadge.jsx";
import CustomSlider from "./CustomSlider.jsx";
import ActivityChip from "../notify/ActivityChip.jsx";
import HelpButton from "../help/HelpButton.jsx";
import GoalChips from "./GoalChips.jsx";
import ActivityPanel from "../notify/ActivityPanel.jsx";
import useActivity from "../notify/useActivity.js";
import { expiringLines, expiryText } from "../inbox/inboxCore.js";
import GiftBox from "../inbox/GiftBox.jsx";
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

/* The gallery layout switcher moved out of this bar on 2026-09-09 (owner): the four-cell
   strip crowded the SIZE group here after Hero got its own cell, so it now lives in
   LayoutStrip.jsx, rendered by the LibraryBar beside Actions. Its glyph/#41/provisional-▣
   history moved with it. */

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
  /* EXPIRING FREE CARDS (Session Y, Y1c + Y2a; drift 130): any held card that lapses within
     72 h puts a 2 px peach underline on the CARDS half and leads the tooltip with one line per
     kind -- "5 Tsubaki.3 expire Oct 6 · in 3 days". Peach, never ruby (an expiry is not
     destructive) and never gold (free cards are not billing): the tooltip's border goes
     lavender while it carries them. Nothing expiring means no mark and the tooltip as
     shipped. Read off the same /api/account answer the chip already draws from. */
  const expiry = expiringLines(cardsBy, Date.now());
  const expiring = expiry.lines.length > 0;
  /* The gift box (Session R, R1a) is drawn only when a PixAI account is linked: the same
     /api/account read answered a balance. A contest row in it opens the Contests overlay. */
  const linked = !!(account && !account.error && account.credits != null);
  const openContests = useCallback(() => onOverlay && onOverlay("contests"), [onOverlay]);

  const claimCredits = account && Number(account.claim_credits) > 0 ? account.claim_credits : 0;

  /* Followers / following, off the same /api/account payload. Rendered only when PixAI
     actually answered with both numbers: an account read that failed, or one whose
     followerCount came back null, must show NOTHING rather than a confident pair of
     zeroes -- "nobody follows you" is a very different sentence from "we could not ask". */
  const social = account && account.followers != null && account.following != null
    ? { followers: Number(account.followers).toLocaleString(),
        following: Number(account.following).toLocaleString() }
    : null;

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

        {/* The pinned goal and the Vigil (Session O, O4/O5), beside the credits. Draws nothing
            unless the account pinned a goal or turned the Vigil switch on; the gallery and the
            Generate dock share this bar. */}
        <GoalChips />

        {/* FOLLOWERS / FOLLOWING (owner, 2026-09-06: "BOTH beside the credits chip and in
            the account popup"). Free -- both numbers already ride the same /api/account
            call the credits chip beside it makes, and have since the CLI's --account
            dashboard; no screen had ever read them.

            THE SAME CHIP, minus the affordance. It borrows .mgx-cred's own markup and
            classes verbatim -- val, label, divider -- and adds only .mgx-social, which
            takes the pointer cursor and the hover lift back off. This is a reading, not a
            control: there is nowhere for it to go and nothing for it to do (following
            somebody is a WRITE to PixAI, and the scope's out-of-scope list rules that out),
            so it is a <span>, not a button, and never enters the tab order. */}
        {social ? (
          <span className="mgx-cred mgx-social"
            title={social.followers + " followers · " + social.following + " following on PixAI"}>
            <span className="mgx-credval">{social.followers}</span>
            <span className="mgx-credlab">FOLLOWERS</span>
            <span className="mgx-creddiv" aria-hidden="true" />
            <span className="mgx-credval">{social.following}</span>
            <span className="mgx-credlab">FOLLOWING</span>
          </span>
        ) : null}

        {/* THE GIFT BOX (Sessions R + Y, Inbox and Event Handoff §1): the inbox's door, one
            8 px gap before the credits chip. Shown only with a linked account. */}
        {linked ? <GiftBox onOpenContests={openContests} /> : null}

        {/* account credits chip: gold billing tooltip drops below, right-anchored */}
        <button type="button" className={"mgx-cred" + (expiring ? " expiring" : "")}
          onClick={() => window.open("https://pixai.art/en/membership/credit-packs", "_blank", "noopener")}
          aria-label={"Credits " + credits + ", cards " + cards + "." +
            (expiring ? " " + expiry.lines.map(expiryText).join(". ") + "." : "") +
            " Buy credits or cards on PixAI."}>
          {warn ? <span className="mgx-warndot" aria-hidden="true">!</span> : null}
          <span className="mgx-credval">{credits}</span>
          <span className="mgx-credlab">CREDITS</span>
          <span className="mgx-creddiv" aria-hidden="true" />
          <span className="mgx-credcards">
            <span className="mgx-credval cards">{cards}</span>
            <span className="mgx-credlab cards">CARDS</span>
          </span>
          <span className="mgx-credtip" role="tooltip">
            {expiring ? (
              <span className="mgx-tipexpiry">
                <span className="mgx-tipexphead">{cards} cards</span>
                {expiry.lines.map((l) => (
                  <span className="mgx-tipexp" key={l.kind + l.at}>{expiryText(l)}</span>
                ))}
                {expiry.other ? (
                  <span className="mgx-tipdim">
                    {expiry.other.toLocaleString()} other card{expiry.other === 1 ? "" : "s"}, no expiry soon
                  </span>
                ) : null}
              </span>
            ) : null}
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
            <i className="mgx-claimribbon" aria-hidden="true" />
            {claiming ? "claiming…" : "+" + Number(claimCredits).toLocaleString() + " claim"}
          </button>
        ) : null}

        {/* The guide's "?" (Session I decision 2; the handoff's section A header draws it
            just before Generate). In the hero state it stands before the banner's own
            Generate button (Banner.jsx) -- this row has no room to spare at 1280 and would
            wrap onto a second line -- so here it shows only in the slim state, beside the
            slim launcher, and below 1200 px, where this row already wraps and the banner's
            row has no room either (help.css). */}
        <HelpButton surface="gallery" className={"mgx-sephelp" + (slim ? " slim" : "")} />

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
