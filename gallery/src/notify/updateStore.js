/* notify/updateStore.js -- the release ANNOUNCEMENT, and nothing else.

   Why it exists at all: the server now re-checks GitHub roughly hourly and says what it
   finds (owner ruling 2026-09-04, reversing his own 2026-09-01 "no background tick
   anywhere" -- he was told the app would notice a release "never on its own" and answered
   "I dislike that"). That answer has to reach a person who is looking at the gallery, not
   only one who happens to open the Control Panel.

   ANNOUNCE ONLY. This module says a release exists. It cannot install one: applying is the
   Control Panel's Update button and its confirm, and there is no call from here into the
   apply route -- pinned by loom/test/mg-update-announce.test.js, which asserts this file
   never so much as names it. The owner rejected auto-apply in the same conversation that
   asked for the background check -- "I don't want that" -- so this has no business growing one.

   A MODULE SINGLETON, deliberately outside any React lifecycle, for the same reason
   jobsStore.js is one: the memory of "this version has already been announced" must survive
   every mount and unmount in the app, or opening and closing a screen would re-toast.

   No new surface. Three existing designed elements carry the news, and this feeds them:
     * the Control Panel's version stamp, which already turns gold and reads
       "vX.Y.Z available -- view" (owner ruling 2026-09-01, Variant A: no new chrome, the
       stamp that was always there becomes the notice);
     * the Panel's update modal, unchanged -- the Identity Chrome C2 handoff owns every
       pixel of the apply flow;
     * one corner toast, through the standard toastStore idiom.

   The server hands the announcement over on the /api/jobs poll -- the one server-truth
   channel every open tab already runs (jobsStore.js) -- rather than by opening a second
   loop for it. */

import { show as toastShow } from "./toastStore.js";

// The last version this BROWSER was told about. Remembered rather than held in memory so a
// reload cannot re-announce the same release: "one toast per new version" is a promise to
// the person, not to the page. Per-browser, like the popup-blur switch and the restart
// estimate -- there is nothing here worth putting in the account.
const SEEN_KEY = "mg_update_announced";

let current = null;         // the announcement payload, or null when nothing is out
const subs = new Set();

function emit() { subs.forEach((fn) => fn(current)); }

export function subscribe(fn) {
  subs.add(fn);
  fn(current);
  return () => subs.delete(fn);
}

export function getUpdate() { return current; }

function readSeen() {
  try { return localStorage.getItem(SEEN_KEY) || ""; } catch { return ""; }
}
function writeSeen(v) {
  try { localStorage.setItem(SEEN_KEY, v); } catch { /* private mode */ }
}

/* Hand the store an update payload -- from the /api/jobs poll's `update` field, or from the
   Control Panel's own fresh check on open. Anything that is not a real "you are behind"
   answer (null, an offline check, an up-to-date one) CLEARS the announcement, so a stamp
   watching this store stops offering an update that has already been applied.

   The toast fires on the TRANSITION to a version this browser has not been told about, once.
   It is sticky on purpose: the hourly check can land while nobody is at the keyboard, and it
   only ever fires once for a given release -- a notice that auto-dismissed into an empty room
   would leave the Panel as the only place to learn about it, which is exactly the behaviour
   the owner rejected. It carries an ×, like every other sticky toast in the app. */
export function note(payload) {
  const next = (payload && payload.behind && payload.latest) ? payload : null;
  const version = next ? String(next.latest) : "";
  const was = current ? String(current.latest) : "";
  current = next;
  if (version !== was) emit();
  if (!version || readSeen() === version) return false;
  writeSeen(version);
  toastShow({
    sticky: true,
    title: "Moonglade " + version + " is ready",
    msg: "Open the Control Panel to update.",
  });
  return true;
}
