/* THE MOMENT ON SCREEN -- one at a time, shared by every shell.

   notify/index.jsx registers playMoment() as ach.js's MOMENT HOST (registerMomentHost), and
   <MomentHost/> -- rendered inside <NotifyRoot/>, which the desktop gallery, the phone, the
   Loom and the setup wizard all render -- is what puts the moment on screen. So whichever
   shell sees an earn carrying a `moment` first is the one that plays it, and none of them
   has to know the others exist.

   playMoment(a) -> Promise that settles when the moment has ENDED -- played out, skipped,
   or fallen back and finished -- which is what ach.js's hold waits on before the feat's
   standard toast may play. It never rejects.

   ONE AT A TIME. A second request for the moment already on screen JOINS it: the key
   sequence starts the starfall itself (its gesture is the trigger), and the marking check()
   it fires then hands the same newly-earned feat to the host a moment later -- that must not
   become a second starfall. A request for a different moment waits for this one to end.

   Pure module state, no React: the component reads it through subscribe()/currentMoment(). */
import { MOMENT_KINDS } from "./momentCore.js";

/* A requested moment that no mounted host ever picks up -- a shell that never renders
   <NotifyRoot/> -- would hold every later achievement toast for the rest of the session.
   This ceiling ends it instead. A real host attaches in the same render the request lands
   in, so this only ever fires where nothing could have shown the moment at all. */
export const ATTACH_CEILING_MS = 20000;

let cur = null;
let seq = 0;
const subs = new Set();

function emit() { subs.forEach((fn) => { try { fn(); } catch { /* a subscriber's own problem */ } }); }

export function subscribe(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}

/* The moment requested right now, or null: {id, kind, a, promise, visible}. */
export function currentMoment() { return cur; }

export function isMomentKind(kind) { return MOMENT_KINDS.indexOf(kind) >= 0; }

export function playMoment(a) {
  const kind = a && a.moment;
  if (!isMomentKind(kind)) return Promise.resolve("none");
  if (cur) {
    if (cur.kind === kind) return cur.promise;            // already up: join it
    return cur.promise.then(() => playMoment(a));          // one at a time
  }
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  const id = ++seq;
  cur = { id, kind, a, promise, resolve, visible: false, attached: false, skip: null, attachT: 0 };
  cur.attachT = setTimeout(() => {
    if (cur && cur.id === id && !cur.attached) finishMoment(id, "no-host");
  }, ATTACH_CEILING_MS);
  emit();
  return promise;
}

/* The host component, once it has mounted this moment: stops the ceiling above and hands
   over the moment's own skip (a fading exit, not a cut). */
export function attachMoment(id, skip) {
  if (!cur || cur.id !== id) return false;
  cur.attached = true;
  cur.skip = typeof skip === "function" ? skip : null;
  clearTimeout(cur.attachT);
  return true;
}

/* On screen, or not yet: a moment still loading its clip is invisible and takes neither the
   keyboard nor the mouse (see the guard below). */
export function setMomentVisible(id, on) {
  if (!cur || cur.id !== id || cur.visible === !!on) return;
  cur.visible = !!on;
  emit();
}

export function finishMoment(id, reason) {
  if (!cur || cur.id !== id) return;
  const done = cur;
  cur = null;
  clearTimeout(done.attachT);
  emit();
  done.resolve(reason || "done");
}

/* THE MOMENT-UP GUARD (review amendment 8). True while a moment is ON SCREEN. App.jsx's
   capture-phase Escape and mousedown handlers read it the way they read paletteUpRef, so a
   key or a click that ends a moment never also closes the overlay under it. */
export function isMomentUp() { return !!(cur && cur.visible); }

/* Ask the moment on screen to end (Escape, the key-sequence trigger's teardown). Its own
   skip fades it out; without one (not yet mounted) it simply finishes. */
export function skipMoment() {
  if (!cur) return false;
  if (cur.skip) cur.skip();
  else finishMoment(cur.id, "skipped");
  return true;
}

/* ESCAPE BELONGS TO THE MOMENT while one is on screen. Registered at module load, in capture
   on window, so it runs ahead of every Escape handler a React tree mounts afterwards (App's
   overlay closer, the palette, the Control Panel's ladder, the Loom's own) -- the same
   ordering notify/ach.js's parade exit relies on -- and it stops the key there. With no
   moment up it returns without touching the event. The mousedown half keeps a click on the
   moment (which ends it, see ClipMoment) from reaching an outside-click closer under it. */
function onKey(e) {
  if (e.key !== "Escape" || !isMomentUp()) return;
  e.preventDefault();
  e.stopPropagation();
  if (e.stopImmediatePropagation) e.stopImmediatePropagation();
  skipMoment();
}
function onDown(e) {
  if (!isMomentUp()) return;
  const t = e.target;
  if (t && t.closest && t.closest("[data-moment]")) {
    e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
  }
}
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("keydown", onKey, true);
  window.addEventListener("mousedown", onDown, true);
  window.addEventListener("pointerdown", onDown, true);
}
