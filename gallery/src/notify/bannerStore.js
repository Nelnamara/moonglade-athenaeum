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
   gallery, which does. Already there (the setup wizard) there is nowhere to send it, and the
   strip says so instead of drawing a button that cannot work (see updateAffordance below;
   2026-09-07, later the same day, correcting a silently dead Update on the wizard shell).
   ------------------------------------------------------------------------------------- */
let host = null;
let pendingOpen = false;
const openSubs = new Set();
const hostSubs = new Set();

/* THE INTENT ACROSS A DOCUMENT LOAD (2026-09-07, later the same day, refining the two-halves
   design above). `pendingOpen` is memory, and the Loom's press is window.location.assign("/")
   -- a full load that throws that memory away, so the gallery came back with nothing open and
   the press had to be made a second time. The intent is therefore written down for the
   crossing and read back once by whichever shell registers a host on the other side.

   sessionStorage rather than localStorage: this belongs to THIS tab's navigation and must not
   leak into a second window, and it must not outlive the crossing. A browser with storage
   blocked throws on the property access itself, so the fallback is a ?update=1 the boot reads
   once and strips out of the address bar -- the intent survives either way. */
const CARRY_KEY = "mg_update_open_intent";

function session() {
  try { return (typeof window !== "undefined" && window.sessionStorage) || null; }
  catch (e) { return null; }
}

function carryIntent() {
  const s = session();
  if (!s) return false;
  try { s.setItem(CARRY_KEY, "1"); return true; } catch (e) { return false; }
}

let carriedQueryRead = false;

function takeCarriedQuery() {
  /* Once per document, whatever the address bar still says: replaceState is what normally
     takes the marker back out, and a browser without it must not re-open the surface on
     every shell that registers. */
  if (carriedQueryRead) return false;
  if (typeof window === "undefined" || !window.location) return false;
  const search = String(window.location.search || "");
  if (search.indexOf("update=1") < 0) return false;
  try {
    const params = new URLSearchParams(search);
    if (params.get("update") !== "1") return false;
    carriedQueryRead = true;
    params.delete("update");
    const rest = params.toString();
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "",
        (window.location.pathname || "/") + (rest ? "?" + rest : "") + (window.location.hash || ""));
    }
    return true;
  } catch (e) { return false; }
}

function takeCarriedIntent() {
  let found = false;
  const s = session();
  if (s) {
    try { if (s.getItem(CARRY_KEY) !== null) { s.removeItem(CARRY_KEY); found = true; } } catch (e) { /* blocked */ }
  }
  if (takeCarriedQuery()) found = true;
  return found;
}

/* "/" when a press here can be answered by navigating to the gallery, "" when it cannot --
   either because this shell IS the gallery's front door (the setup wizard) or because there
   is no browser to navigate. */
function navigableTarget() {
  if (typeof window === "undefined" || !window.location) return "";
  return (window.location.pathname || "/") === "/" ? "" : "/";
}

/* WHAT THE STRIP MAY OFFER on the shell it is standing on. The Update button is drawn only
   when the press can actually reach the surface that owns the confirm: a registered host, or
   a gallery to cross to. On the setup wizard it is neither, so the strip states the reason
   instead -- a button that silently does nothing is worse than no button. */
export function updateAffordance() {
  if (host) return { canOpen: true, why: "" };
  if (navigableTarget()) return { canOpen: true, why: "open the gallery to update" };
  return { canOpen: false, why: "finish setup first" };
}

export function hasUpdateHost() { return !!host; }

/* The strip mounts before any shell registers, so it watches rather than asks once. */
export function subscribeUpdateHost(fn) {
  hostSubs.add(fn);
  fn(!!host);
  return () => hostSubs.delete(fn);
}

export function registerUpdateHost(fn) {
  host = fn;
  hostSubs.forEach((s) => s(true));
  /* The other side of a crossing: a press made on the Loom a moment ago, carried through the
     document load. Consumed here rather than by the surface itself, because the surface is
     not mounted on a fresh boot -- the host is what mounts it. */
  if (takeCarriedIntent()) { pendingOpen = true; fn(); }
  return () => { if (host === fn) { host = null; hostSubs.forEach((s) => s(false)); } };
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
  const target = navigableTarget();
  if (!target) return;
  window.location.assign(carryIntent() ? target : target + "?update=1");
}
