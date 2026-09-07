/* notify/bannerStore.js -- the standing "a release is out" strip, and the one intent that
   carries a press on its Update button to whichever shell can actually open the apply flow.

   WHY A BANNER AND NOT A TOAST (owner ruling 2026-09-07, refining his own 2026-09-04
   "announce it wherever the person is"): the announcement used to be one sticky corner
   toast, fired once per version and carrying an × -- so a person who dismissed it, or who
   was simply not at the keyboard when the hourly check landed and later closed the stack,
   had no way left to learn a release existed except opening the Control Panel. "Update
   should be noticed anywhere." This strip is the reworked toast: it stands until the update
   is actually applied (the reload after an apply is what clears it), on every surface the
   notify root mounts on -- desktop, phone and the setup wizard alike.

   NOT DISMISSIBLE, COLLAPSIBLE. "Not now" folds the strip into a small pill, for THIS TAB
   only and never written down: a per-browser memory of "hide the news" is the thing the
   ruling above exists to remove. The pill re-expands on tap, and a reload brings the strip
   back.

   ANNOUNCE ONLY, exactly like notify/updateStore.js which feeds it: nothing in this file
   names the apply route or touches the network. requestUpdateOpen() asks a SHELL to open
   the surface that owns the confirm -- the Control Panel's update modal on desktop, the
   Control tab's update screen on the phone -- and that surface's own explicit button is
   still the only thing that can apply anything. */

let banner = null;          // {version, notes} or null when nothing is out
let collapsed = false;      // this TAB's pill; deliberately not persisted anywhere
const subs = new Set();

function emit() { subs.forEach((fn) => fn(banner, collapsed)); }

export function subscribe(fn) {
  subs.add(fn);
  fn(banner, collapsed);
  return () => subs.delete(fn);
}

export function getBanner() { return banner; }
export function isCollapsed() { return collapsed; }

/* Hand the strip a release, or null to take it down. Called on EVERY jobs poll (every
   2.5-7 seconds) with the same answer, so re-setting the version already showing is a
   deliberate no-op: an emit per tick would re-render every host, and resetting `collapsed`
   per tick would pop a folded pill back open a few seconds after it was folded. */
export function setBanner(next) {
  const version = next && next.version ? String(next.version) : "";
  const was = banner ? banner.version : "";
  if (version === was) return;
  banner = version ? { version, notes: (next && next.notes) || "" } : null;
  collapsed = false;              // a DIFFERENT release is news again, pill or no pill
  emit();
}

export function collapse() { if (!collapsed) { collapsed = true; emit(); } }
export function expand() { if (collapsed) { collapsed = false; emit(); } }

/* ---------------------------------------------------------------------------
   THE INTENT -- one press, three shells, no prop chain.

   The strip is portaled to document.body from the notify root; the surface that owns the
   confirm is several trees away (App.jsx's overlay state, AppMobile's tab state). Rather
   than thread a callback down through either shell, the shell REGISTERS what "open the
   update" means for it and the strip asks. Two halves, because the surface is usually not
   mounted yet when the button is pressed:

     registerUpdateHost(fn)  -- the shell's own "bring that surface up" (open the Control
                                Panel overlay / switch to the Control tab).
     takeOpenIntent()        -- read ONCE, by the surface, on mount: "you were opened for
                                the update".
     subscribeOpenIntent(fn) -- for a surface that is ALREADY mounted, which would never
                                run its mount effect again.

   With no host registered -- the Loom, which has no Control Panel -- the press goes to the
   gallery, which does. Already there (the setup wizard) it does nothing rather than
   reloading a page that cannot help. --------------------------------------------------- */
let host = null;
let pendingOpen = false;
const openSubs = new Set();

export function registerUpdateHost(fn) {
  host = fn;
  return () => { if (host === fn) host = null; };
}

export function subscribeOpenIntent(fn) {
  openSubs.add(fn);
  return () => openSubs.delete(fn);
}

export function takeOpenIntent() {
  const p = pendingOpen;
  pendingOpen = false;
  return p;
}

export function requestUpdateOpen() {
  pendingOpen = true;
  openSubs.forEach((fn) => fn());
  if (host) { host(); return; }
  if (typeof window === "undefined" || !window.location) return;
  if (window.location.pathname !== "/") window.location.assign("/");
}
