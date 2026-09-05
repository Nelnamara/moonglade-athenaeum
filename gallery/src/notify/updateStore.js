/* notify/updateStore.js -- the two things this app SAYS about a release: that one is out
   (the announcement, below) and that one landed (the receipt, at the foot of this file).
   Both are words to a person. Neither can install anything -- see ANNOUNCE ONLY.

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

// The last version this BROWSER was told about. Remembered in localStorage so a reload
// cannot re-announce the same release: "one toast per new version" is a promise to the
// person, not to the page. Per-browser, like the popup-blur switch and the restart
// estimate -- there is nothing here worth putting in the account.
const SEEN_KEY = "mg_update_announced";

let current = null;         // the announcement payload, or null when nothing is out
const subs = new Set();

/* FAIL CLOSED, NOT OPEN. localStorage is the CROSS-RELOAD layer only; this variable is
   the one that actually holds the promise. A browser with storage blocked (private mode,
   "block third-party cookies" on an embedded view, a locked-down profile) throws on both
   getItem and setItem -- and the guarded reads used to swallow that and answer "", which
   read as "never announced". The poll behind this store runs every 2.5-7 seconds, so the
   same release announced a fresh sticky toast on EVERY tick, stacking forever. Checked
   and written FIRST, before storage is consulted at all: at most one announcement per
   version per tab, whatever storage does. */
let memSeen = "";

function emit() { subs.forEach((fn) => fn(current)); }

export function subscribe(fn) {
  subs.add(fn);
  fn(current);
  return () => subs.delete(fn);
}

export function getUpdate() { return current; }

/* Versions COMPARED, not string-matched. A rollback -- the owner pulling a bad release, so
   the hourly check answers v3.7.1 an hour after it answered v3.7.2 -- is not news, and
   under plain inequality it both fired a second toast and wrote the LOWER version into the
   seen key, which then made the real newer release look already-announced.

   Returns 1/0/-1, or null when either side is not a plain dotted number (with an optional
   leading v, which is how the tags are shaped). Null is answered CONSERVATIVELY by every
   caller: no announcement, and nothing overwritten. */
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

function readStored() {
  try { return localStorage.getItem(SEEN_KEY) || ""; } catch { return ""; }
}

/* The highest version known to have been announced: memory OR storage, whichever is
   higher. Memory is authoritative when storage is unreadable or holds something that does
   not parse; storage wins when it is genuinely ahead (another tab got there first). */
function highestSeen() {
  const stored = readStored();
  if (!memSeen) return stored;
  if (!stored) return memSeen;
  const c = cmpVersions(stored, memSeen);
  if (c === null) return memSeen;
  return c > 0 ? stored : memSeen;
}

/* Never downward. Memory first (it is the layer that cannot fail), storage after. */
function markSeen(v) {
  memSeen = v;
  const stored = readStored();
  if (stored) {
    const c = cmpVersions(v, stored);
    if (c === null || c <= 0) return;      // malformed, equal or older: leave storage alone
  }
  try { localStorage.setItem(SEEN_KEY, v); } catch { /* private mode: memory carries it */ }
}

/* CROSS-TAB. Two tabs both polling can each read "not announced" and each toast; the
   `storage` event is how a browser tells the other tabs what one of them just wrote, so
   the memory here follows it upward and the re-check immediately before toastShow (below)
   catches the sibling that got there first. A millisecond-wide race survives -- two tabs
   writing inside the same event-loop turn -- and is accepted: the cost is one duplicate
   toast in a window narrower than the 2.5s poll that opens it, and closing it properly
   would mean a lock this store has no business owning. */
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (e) => {
    if (!e || e.key !== SEEN_KEY) return;
    const v = String(e.newValue || "");
    if (!v) return;
    if (!memSeen) { memSeen = v; return; }
    const c = cmpVersions(v, memSeen);
    if (c !== null && c > 0) memSeen = v;
  });
}

/* Hand the store an update payload -- from the /api/jobs poll's `update` field, or from the
   Control Panel's own fresh check on open. Anything that is not a real "you are behind"
   answer (null, an offline check, an up-to-date one) CLEARS the announcement, so a stamp
   watching this store stops offering an update that has already been applied.

   The toast fires on the TRANSITION to a version this browser has not been told about, once
   -- and only ever FORWARD: a version equal to or lower than the highest already announced
   (the hourly tick repeating itself, or a pulled release) is not news, and never overwrites
   what has been announced.
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
  if (!version) return false;
  // ONLY EVER FORWARD, and memory first because memory is the layer that cannot fail.
  // Equal is the hourly tick finding what it found an hour ago; lower is a rollback;
  // unparseable is something nobody should be toasted about either way.
  if (memSeen) {
    const m = cmpVersions(version, memSeen);
    if (m === null || m <= 0) return false;
  }
  // Then the shared layer, read as late as possible -- immediately before the toast --
  // because a sibling tab may have announced this version since this one last looked.
  // (Nothing can interleave INSIDE this function, so "as late as possible" means since the
  // previous turn; the residual millisecond race, two tabs passing this line before either
  // writes, is accepted: one duplicate toast in a window far narrower than the poll that
  // opens it, against a lock this store has no business owning.)
  const c = cmpVersions(version, highestSeen() || "0");
  if (c === null || c <= 0) return false;
  markSeen(version);
  toastShow({
    sticky: true,
    title: "Moonglade " + version + " is ready",
    msg: "Open the Control Panel to update.",
  });
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
