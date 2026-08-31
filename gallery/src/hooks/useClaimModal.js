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

   CADENCE, settled 2026-08-24 (REPLACES the 2026-08-05 "sessionStorage, once per
   tab-lifetime" rule -- do NOT restore that; it stranded rewards):
     The modal re-arms on a FRESH PAGE LOAD (initial load, reload, Ctrl-Shift-R,
     and moving between the separate Gallery / Loom / login shells -- each is its
     own document) and on RETURNING TO THE TAB (the visibilitychange handler
     below). It deliberately does NOT re-arm on in-app modal/panel navigation
     within one page load -- the app is almost all modal, and re-popping on every
     panel open would be exactly the PixAI-popup-on-every-click annoyance we are
     avoiding (owner, 2026-08-24).

     The gate is the in-memory `_armed` flag: true at load, flipped false the
     moment the modal opens, flipped back true ONLY by a fresh load (module
     re-init) or a tab return. Dismissing neither re-arms nor persists -- so a
     reward is never stranded behind a toast closed once, but you also aren't
     nagged mid-visit. Claiming (claim_credits -> 0) is what ends it for good.

     Why in-memory and not sessionStorage: a reload CLEARS an in-memory flag (the
     toast returns), whereas the old sessionStorage flag SURVIVED reloads (so it
     never did -- "shows once or not at all and never comes back", owner). Only one
     of App.jsx / AppMobile.jsx is mounted at a time, so the single shared flag has
     exactly one owner. */

const EXIT_MS = 480; // must match claim-modal.css's mgclaimCoinJump duration

// See the cadence note: true at page load, false once the modal opens, true again
// only on a fresh load or a tab return. This is what keeps in-app panel opens from
// re-popping the toast, without persisting across reloads the way the old flag did.
let _armed = true;

export default function useClaimModal(account, refreshAccount) {
  const [open, setOpen] = useState(false);
  const [exiting, setExiting] = useState(false); // coin-jump playing, card fading
  const [claiming, setClaiming] = useState(false);
  const [error, setError] = useState("");

  // Open when armed and there's an unclaimed reward. `_armed` is what keeps this
  // from re-popping on every in-app account refetch: it's true only just after a
  // fresh load or a tab-return, and we flip it false the instant we open. So a
  // reload / shell-nav / tab-return shows the toast, but opening Health or Control
  // Panel mid-visit does not. Claiming (claim_credits -> 0) finally quiets it.
  useEffect(() => {
    if (open || exiting) return; // never re-arm mid-cycle
    // Number(): claim_credits must be a real positive amount -- a stringy "0" is
    // truthy and would pop a modal for nothing (belt for the vanished-reward close below).
    if (_armed && account && Number(account.claim_credits) > 0) {
      setOpen(true);
      _armed = false; // shown once for this arming; a reload or tab-return re-arms it
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  // The reward can vanish OUT FROM UNDER an open modal: claimed in another window /
  // device, then this tab's return-refetch installs claim_credits=0 -- and the modal
  // sat there reading "+0, Ready to claim", inviting a claim of nothing (owner-found,
  // 2026-08-29; reproduced live). Close QUIETLY -- no coin-jump: the coin celebrates a
  // claim, and nothing was claimed here.
  useEffect(() => {
    if (!open || exiting) return;
    if (account && !(Number(account.claim_credits) > 0)) {
      setOpen(false);
      setClaiming(false);
      setError("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account]);

  // Coming back to the tab is the one re-arm that happens within a live page (a
  // reload / shell-nav re-arm for free by re-initialising the module). Re-arm, then
  // re-read the account -- `account` carries claim_credits and nothing else re-reads
  // it, so a tab left open across the daily reset otherwise never learns the reward
  // went claimable. refreshAccount is held in a ref so we subscribe once instead of
  // re-subscribing every render (App.jsx passes a fresh closure each render); the
  // re-fetch installs a new `account` object, which the open-effect above turns into
  // an open modal if it's still unclaimed.
  const refreshRef = useRef(refreshAccount);
  refreshRef.current = refreshAccount;
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      _armed = true;                                 // returning re-arms the nudge...
      if (refreshRef.current) refreshRef.current();  // ...and re-reads so a reward that landed while away shows
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

  // Just close it for now. Deliberately does NOT re-arm and does NOT persist: a
  // reload or a return to the tab re-opens it while the reward is still unclaimed,
  // but an in-app panel open mid-visit will not.
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
      // back on the next load/return. (No "mark seen" needed.)
      if (refreshAccount) refreshAccount();
      _exit();
    } catch {
      setError("Network error — try again.");
      setClaiming(false);
    }
  };

  return { open, exiting, claiming, error, credits: (account && account.claim_credits) || 0, claim, dismiss };
}
