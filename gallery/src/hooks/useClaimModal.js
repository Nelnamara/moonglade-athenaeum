import { useEffect, useRef, useState } from "react";
import { apiPost } from "../api.js";

/* Daily-claim popup's own state/handlers -- extracted so App.jsx (desktop) and
   AppMobile.jsx (mobile) can each mount <ClaimModal> off the SAME logic against
   their own independently-tracked `account` state (they already keep two separate
   copies -- see useControlPanel.js's header comment for why that split is correct
   rather than a smell), instead of two drifting copies of the open/dismiss/claim
   machinery.

   Classic's own #acct-claim pill (Acct.claim() in moonglade_gallery.py) is the
   only claim UI that ever shipped to the browser before this. Ported as an
   ADDITION, not a replacement: the small always-visible pill also shipped this
   same pass (SeparatorBar.jsx's .mgx-claim / AppMobile.jsx's .glm-hero-claim --
   both call this hook's own `claim`, so the pill and the modal share one action,
   not two), and this modal is the harder-to-miss nudge on top of it.

   CADENCE, revised 2026-08-24 (this REPLACES the 2026-08-05 "ask once per session"
   rule -- do not restore it):
     The modal opens WHENEVER there is an unclaimed reward and it isn't already
     open, and it KEEPS coming back -- on reload, on Ctrl-Shift-R, and whenever you
     return to the tab (the visibilitychange re-fetch below) -- until you actually
     CLAIM it. Dismissing only closes it for the moment; it does NOT remember the
     dismissal, so the reward is never stranded behind a toast you closed once.
     Claiming is the only thing that stops the nudge: `claim` refreshes the account,
     claim_credits drops to 0, and the open-effect below stops firing.

   Why the change: the old code set a sessionStorage flag on show/dismiss, so the
   modal fired at most ONCE per tab-lifetime -- once dismissed it never returned,
   not on reload, not on hard-reload, not on coming back to the tab. A real reward
   sat unclaimable behind a toast the owner had closed a single time ("shows once
   or not at all and never comes back", owner 2026-08-24). There is no persistent
   "seen" flag now, by design. (If it ever needs to be less insistent, throttle the
   re-opens on a minimum interval -- do NOT reintroduce a flag that survives a
   reload, which is the exact bug this removed.) */

const EXIT_MS = 480; // must match claim-modal.css's mgclaimCoinJump duration

export default function useClaimModal(account, refreshAccount) {
  const [open, setOpen] = useState(false);
  const [exiting, setExiting] = useState(false); // coin-jump playing, card fading
  const [claiming, setClaiming] = useState(false);
  const [error, setError] = useState("");

  // Open whenever there's an unclaimed reward and we're not mid-cycle. Re-runs on
  // every `account` change -- so a reload, a manual refresh, and the visibility
  // re-fetch below all re-open it while the reward is still unclaimed. Claiming
  // (claim_credits -> 0) is what finally quiets it. No "already seen" gate: a
  // dismissed toast is meant to come back, not to disappear for the tab's life.
  useEffect(() => {
    if (open || exiting) return; // never re-arm mid-cycle
    if (account && account.claim_credits) setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  // Re-read the account when you come back to the tab. `account` carries
  // claim_credits and nothing else re-reads it, so a tab left open across the daily
  // reset never learned the reward went claimable; and after a dismiss, this is
  // what brings the nudge back when you return. refreshAccount is held in a ref so
  // we subscribe once instead of re-subscribing every render (App.jsx passes a
  // fresh closure each render). The re-fetch installs a new `account` object, which
  // the open-effect above turns back into an open modal if it's still unclaimed.
  const refreshRef = useRef(refreshAccount);
  refreshRef.current = refreshAccount;
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && refreshRef.current) refreshRef.current();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // Shared exit path for both claim and dismiss: play the coin-jump, THEN actually
  // unmount -- same closing-transition shape ControlMobile.jsx's openBrand/closeBrand
  // pair established, just a longer window since the coin animation is the point.
  const _exit = () => {
    setExiting(true);
    setTimeout(() => {
      setOpen(false);
      setExiting(false);
      setClaiming(false);
      setError("");
    }, EXIT_MS);
  };

  // A missed free reward has nothing to protect against an accidental close, so
  // Escape dismisses like any other casually-dismissible overlay.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") dismiss(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Just close it for now. Deliberately does NOT remember the dismissal: a reload
  // or a return to the tab re-opens it while the reward is still unclaimed.
  const dismiss = () => {
    if (exiting) return;
    _exit();
  };

  const claim = async () => {
    if (claiming || exiting) return;
    setClaiming(true);
    setError("");
    try {
      const d = await apiPost("/api/claim");
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
      // Refresh so claim_credits drops to 0 -- THIS is what stops the nudge coming
      // back. (No "mark seen" needed: an unclaimed reward should keep nudging.)
      if (refreshAccount) refreshAccount();
      _exit();
    } catch {
      setError("Network error — try again.");
      setClaiming(false);
    }
  };

  return { open, exiting, claiming, error, credits: (account && account.claim_credits) || 0, claim, dismiss };
}
