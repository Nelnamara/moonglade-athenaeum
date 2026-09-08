/* notify/updateStore.js -- the two things this app SAYS about a release: that one is out
   (the announcement, below) and that one landed (the receipt, at the foot of this file).
   Both are words to a person. Neither can install anything -- see ANNOUNCE ONLY.

   Why it exists at all: the server now re-checks GitHub roughly hourly and says what it
   finds (owner ruling 2026-09-04, reversing his own 2026-09-01 "no background tick
   anywhere" -- he was told the app would notice a release "never on its own" and answered
   "I dislike that"). That answer has to reach a person who is looking at the gallery, not
   only one who happens to open the Control Panel.

   A BANNER, NOT A TOAST (owner ruling 2026-09-07, refining the 2026-09-04 one above:
   "update should be noticed anywhere", "just a reworked banner on the toast"). Until this
   date the announcement was ONE sticky corner toast per version, deduped per browser
   through a localStorage key -- so it could be dismissed, or missed while nobody was at the
   keyboard, and then the Control Panel was the only place left to learn a release existed.
   It now sets notify/bannerStore.js instead: a strip that STANDS until the update is
   actually applied, on every surface the notify root mounts on. The whole per-browser
   "already announced" ledger (SEEN_KEY, its memory-first mirror, its cross-tab `storage`
   listener) went with the toast -- a standing strip has nothing to dedupe: two tabs showing
   the same banner is the correct answer, not a duplicate.

   ANNOUNCE ONLY. This module says a release exists. It cannot install one: applying is the
   Control Panel's Update button and its confirm, and there is no call from here into the
   apply route -- pinned by loom/test/mg-update-announce.test.js, which asserts this file
   never so much as names it. The owner rejected auto-apply in the same conversation that
   asked for the background check -- "I don't want that" -- so this has no business growing one.

   A MODULE SINGLETON, deliberately outside any React lifecycle, for the same reason
   jobsStore.js is one: the announcement must survive every mount and unmount in the app.

   No new surface beyond the strip. The other two designed elements carry the news as
   before, and this feeds them:
     * the Control Panel's version stamp, which already turns gold and reads
       "vX.Y.Z available -- view" (owner ruling 2026-09-01, Variant A);
     * the Panel's update modal, unchanged -- the Identity Chrome C2 handoff owns every
       pixel of the apply flow.

   The server hands the announcement over on the /api/jobs poll -- the one server-truth
   channel every open tab already runs (jobsStore.js) -- rather than by opening a second
   loop for it. */

import { show as toastShow } from "./toastStore.js";
import { setBanner } from "./bannerStore.js";

let current = null;         // the announcement payload, or null when nothing is out
const subs = new Set();

function emit() { subs.forEach((fn) => fn(current)); }

export function subscribe(fn) {
  subs.add(fn);
  fn(current);
  return () => subs.delete(fn);
}

export function getUpdate() { return current; }

/* Versions COMPARED, not string-matched. A rollback -- the owner pulling a bad release, so
   the hourly check answers v3.7.1 an hour after it answered v3.7.2 -- must not raise a
   banner against a build that is already newer than it.

   Returns 1/0/-1, or null when either side is not a plain dotted number (with an optional
   leading v, which is how the tags are shaped). Null is answered CONSERVATIVELY by every
   caller: no banner. */
function parseVersion(v) {
  const s = String(v == null ? "" : v).trim().replace(/^v/i, "");
  if (!/^\d+(\.\d+)*$/.test(s)) return null;
  return s.split(".").map(Number);
}
export function cmpVersions(a, b) {
  const pa = parseVersion(a), pb = parseVersion(b);
  if (!pa || !pb) return null;
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0;
    if (x !== y) return x > y ? 1 : -1;
  }
  return 0;
}

/* WHAT THIS PROCESS IS REALLY RUNNING, which is the only honest thing to compare a release
   against now that the notice stands instead of firing once. window.MG_BOOT.build_stamp is
   the version this bundle was served by (the same value the receipt is judged against, and
   the same one the Panel's version stamp prints); the server's own `current` in the payload
   is the fallback for a shell that has no boot stamp at all. */
function runningVersion(payload) {
  let stamp = "";
  try { stamp = (typeof window !== "undefined" && window.MG_BOOT && window.MG_BOOT.build_stamp) || ""; }
  catch { stamp = ""; }
  const v = versionFromStamp(stamp);
  if (v && parseVersion(v) !== null) return v;
  return (payload && payload.current) || "";
}

/* Hand the store an update payload -- from the /api/jobs poll's `update` field, or from the
   Control Panel's own fresh check on open. Anything that is not a real "you are behind"
   answer (null, an offline check, an up-to-date one) CLEARS both the announcement and the
   banner, so a stamp or a strip watching this store stops offering an update that has
   already been applied.

   The banner is set on EVERY tick that finds a release newer than the running build, and
   the store behind it treats a repeat as a no-op -- that is what makes the notice
   persistent rather than once-per-version. Equal or lower is not news and takes the strip
   down: an up-to-date answer, or a rollback the running build is already past.

   AND NOT WHILE AN APPLY IS IN FLIGHT. armReceipt() has written down the version this
   browser is on its way to; the poll behind this store keeps running for the second or two
   before the reload, and a strip saying "3.10 is ready" over a modal installing 3.10 is
   just noise. The reload is what really clears the banner; this keeps it from flickering
   back in the meantime. */
export function note(payload) {
  const next = (payload && payload.behind && payload.latest) ? payload : null;
  const version = next ? String(next.latest) : "";
  const was = current ? String(current.latest) : "";
  current = next;
  if (version !== was) emit();
  if (!version || receiptArmed()) { setBanner(null); return false; }
  const c = cmpVersions(version, runningVersion(next));
  if (c === null || c <= 0) { setBanner(null); return false; }
  setBanner({ version, notes: next.notes_url || "" });
  return true;
}

/* ---------------------------------------------------------------------------
   THE RECEIPT -- what tells you the update actually landed.

   The apply ends in a page reload (hooks/useControlPanel.js): the bundle still running is
   the code that was just replaced, so loading the new build is the only honest way to show
   the new version. But the reload is ALSO the whole problem -- the modal, its three ticks
   and its meter go with it, and what comes back is the gallery, looking exactly as it did
   before. Owner, 2026-09-05: "just a restart with no endpoint tells the user that nothing
   happened unless they go BACK to the panel."

   So the apply writes down the version it is going for, and the next boot pays it out:

     armReceipt(target)   -- immediately before the reload. localStorage only; memory
                             cannot survive the thing it is here to survive.
     claimReceipt(stamp)  -- on boot, handed the version this process is REALLY running
                             (window.MG_BOOT.build_stamp, "v3.8.0 · a1b2c3d").

   HONEST OR SILENT, never optimistic. The note is shown only when the running version IS
   the version that was promised. An update that failed, was rolled back, or left the
   machine on the old build says nothing at all -- and its record is torn up all the same,
   so it cannot pay out later against some future release that happens to match. One boot,
   one answer, either way; the second reload shows nothing. A boot that cannot tell what it
   is running (no stamp) leaves the record alone rather than eating it. --------------- */
const RECEIPT_KEY = "mg_update_receipt";

/* The build stamp is "vX.Y.Z" or "vX.Y.Z · <sha>" -- the version is the first token. */
export function versionFromStamp(stamp) {
  return String(stamp == null ? "" : stamp).trim().split(/[·\s]/)[0] || "";
}

function clearReceipt() {
  try { localStorage.removeItem(RECEIPT_KEY); } catch { /* private mode: nothing to clear */ }
}

/* Is an apply already on its way to a reload in this browser? Read by note() above, which
   must not put a "3.10 is ready" strip back over the modal that is installing 3.10. A
   browser with storage blocked answers false and simply keeps the strip up for the second
   or two until the reload takes it -- the same fail-quiet the receipt itself takes. */
export function receiptArmed() {
  try { return !!localStorage.getItem(RECEIPT_KEY); } catch { return false; }
}

/* Write down what this apply is going for. A version nobody can parse is not written at
   all: an unpayable record is just litter in the next boot's way. */
export function armReceipt(version) {
  const v = String(version == null ? "" : version).trim();
  if (!v || parseVersion(v) === null) return false;
  try { localStorage.setItem(RECEIPT_KEY, v); } catch { return false; }
  return true;
}

export function claimReceipt(stamp) {
  let want = "";
  try { want = localStorage.getItem(RECEIPT_KEY) || ""; } catch { return false; }
  if (!want) return false;
  const have = versionFromStamp(stamp);
  // Nothing to compare against: this boot cannot honestly say either way, so it says
  // nothing and leaves the record for a boot that can.
  if (!have || parseVersion(have) === null) return false;
  clearReceipt();                       // ONCE, whichever answer comes back
  if (cmpVersions(have, want) !== 0) return false;   // it did not land: silence
  const label = /^v/i.test(want) ? want : "v" + want;
  toastShow({
    kind: "ok",
    sticky: true,
    title: "Updated to " + label,
    msg: "The restart finished — this is the new build.",
  });
  return true;
}
