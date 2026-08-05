import { useEffect, useState } from "react";

/* Daily-claim popup's own state/handlers -- extracted so App.jsx (desktop) and
   AppMobile.jsx (mobile) can each mount <ClaimModal> off the SAME logic
   against their own independently-tracked `account` state (they already keep
   two separate copies -- see useControlPanel.js's header comment for why that
   split is correct rather than a smell), instead of two drifting copies of
   the open/dismiss/claim machinery.

   Classic's own #acct-claim pill (Acct.claim() in moonglade_gallery.py) is
   the only claim UI that ever shipped to the browser before this. Ported as
   an ADDITION, not a replacement: the small always-visible pill also shipped
   this same pass (SeparatorBar.jsx's .mgx-claim / AppMobile.jsx's
   .glm-hero-claim -- both call this hook's own `claim`, so the pill and the
   modal share one action, not two), and this modal is the once-a-session,
   harder-to-miss nudge on top of it. Never built for /next before now --
   there was no locked design surface for it (grepped every .dc.html; none
   exist), so it was missed rather than deliberately cut.

   CADENCE, owner-specified 2026-08-05: PixAI's own claim popup fires on
   every page load, which the owner explicitly called out as "annoying at
   times" -- deliberately NOT copying that. Fires at most ONCE per real
   session (a sessionStorage flag, not localStorage: a fresh tab/session
   gets asked again if still unclaimed, but nothing in the SPA -- switching
   Gallery/Health/Control Panel -- re-triggers it). Dismissing counts the
   same as claiming for this flag: the point is to ask once, not to punish a
   "not now" by asking again a minute later. The header pill is intentionally
   NOT gated by this flag -- it just reflects claim_credits > 0 directly, so
   dismissing the modal never makes the reward invisible, only de-escalates
   it from an interruption to a quiet, always-there reminder. */

const SEEN_KEY = "mg_claim_seen";
const EXIT_MS = 480; // must match claim-modal.css's mgclaimCoinJump duration

function markSeen() {
  try { sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* private browsing, etc. */ }
}
function alreadySeen() {
  try { return sessionStorage.getItem(SEEN_KEY) === "1"; } catch { return false; }
}

export default function useClaimModal(account, refreshAccount) {
  const [open, setOpen] = useState(false);
  const [exiting, setExiting] = useState(false); // coin-jump playing, card fading
  const [claiming, setClaiming] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open || exiting) return; // never re-arm mid-cycle
    if (account && account.claim_credits && !alreadySeen()) setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  // Shared exit path for both claim and dismiss: play the coin-jump, THEN
  // actually unmount -- same 220ms-style closing-transition shape
  // ControlMobile.jsx's openBrand/closeBrand pair already established, just
  // a longer window since the coin animation itself is the point here, not
  // an incidental slide.
  const _exit = () => {
    setExiting(true);
    setTimeout(() => {
      setOpen(false);
      setExiting(false);
      setClaiming(false);
      setError("");
    }, EXIT_MS);
  };

  // Unlike Power modal (deliberately NOT Escape-closable while a real restart
  // is mid-flight -- ControlPanelOverlay.jsx's own Escape handler explicitly
  // defers while `power` is set), a missed free reward has nothing to
  // protect against an accidental close, so Escape works here like every
  // other casually-dismissible overlay in the app.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") dismiss(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const dismiss = () => {
    if (exiting) return;
    markSeen();
    _exit();
  };

  const claim = async () => {
    if (claiming || exiting) return;
    setClaiming(true);
    setError("");
    try {
      const r = await fetch("/api/claim", { method: "POST" });
      const d = await r.json();
      if (d && d.error) {
        setError(d.error);
        setClaiming(false);
        return;
      }
      if (window.Toast) {
        window.Toast.show({
          kind: "ok",
          title: "Claimed +" + Number((d && d.credits) || 0).toLocaleString() + " credits",
        });
      }
      markSeen();
      if (refreshAccount) refreshAccount();
      _exit();
    } catch {
      setError("Network error — try again.");
      setClaiming(false);
    }
  };

  return { open, exiting, claiming, error, credits: (account && account.claim_credits) || 0, claim, dismiss };
}
