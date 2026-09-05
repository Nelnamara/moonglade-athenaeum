import React from "react";
import * as toastStore from "./toastStore.js";
import * as jobs from "./jobs.js";
import * as jobsStore from "./jobsStore.js";
import * as ach from "./ach.js";
import { claimReceipt } from "./updateStore.js";
import ToastHost from "./ToastHost.jsx";
import "../styles/notify.css";

/* notify/index.jsx -- the one installer for the notify system (no-vanilla campaign, component
   6, replacing static/mg-notify.js). Two things:

   1. installNotify() -- publishes the window.* compat surface and starts the background
      singletons. The window globals are the SAME four contracts the vanilla published
      (Toast.show / Jobs.track+register / JobsCard.open+close+refresh+dismiss+clearFinished /
      Ach.check+replay), now backed by the React-owned stores -- kept so the ~30 existing
      guarded `if (window.Toast) ...` call sites across gallery/src and the Loom keep working
      unchanged. (Rewiring those callers to direct imports is a follow-up cleanup, not part of
      this port -- see docs/DECISIONS.md.) Dead vanilla API deliberately NOT re-published:
      Ach.open/close/tab/search/setUnleash/poke served only the #ach-modal Trophy Hall, which
      no served page carries (the React Folio replaced it).

      Also the old DOMContentLoaded work: jobsStore.start() (the tray's first refresh + the
      adaptive poll) and ach.check() (mark-and-toast newly earned achievements + reconcile the
      active skin) -- by the time a bundle evaluates, the DOM is ready.

   2. <NotifyRoot/> -- the React UI, portaled to document.body from whichever app tree
      renders it (the gallery's authenticated root, the Loom's root component). The engines
      run either way; the root only paints. Corner toasts only as of 2026-08-09 -- the
      Activity control moved OUT of this shared body-level portal into each host's own header
      (Claude Design handoff, drift item 39: the old floating #jobs-fab/#jobs-tray had to
      out-rank every overlay in z-index just to stay visible). See
      gallery/src/components/SeparatorBar.jsx for the gallery's own mount. */

let installed = false;

export function installNotify() {
  if (installed) return;
  installed = true;

  window.Toast = { show: toastStore.show };
  window.Jobs = { track: jobs.track, register: jobs.register };
  window.JobsCard = {
    open: jobsStore.openTray,
    close: jobsStore.closeTray,
    refresh: jobsStore.refresh,
    dismiss: jobsStore.dismiss,
    clearFinished: jobsStore.clearFinished,
  };
  window.Ach = { check: ach.check, replay: ach.replay };

  jobsStore.start();
  ach.check();
  /* THE UPDATE'S RECEIPT (2026-09-05). An apply ends in a reload, and what comes back
     looks exactly like what went away -- so the boot that follows one pays out the note
     the vanished modal could not. Here rather than in a component because this is where
     the update's OTHER piece of news already lives (jobsStore's poll feeds the
     announcement), and because it must fire once per boot, not once per mount.
     build_stamp is the version this process is really running; without it the receipt
     waits rather than guessing. See notify/updateStore.js. */
  const boot = (typeof window !== "undefined" && window.MG_BOOT) || {};
  claimReceipt(boot.build_stamp || "");
}

export function NotifyRoot() {
  return <ToastHost />;
}
