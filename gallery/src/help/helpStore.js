import { sendAchEvent } from "../notify/achNonce.js";
import { pageForSurface } from "./helpCore.js";

/* THE GUIDE'S STATE, outside React (Session I decision 2).

   A module singleton for the same reason notify/toastStore.js is one: Help opens from a
   dozen places that share no component tree -- the "?" in every surface header, the ? key,
   the command palette's Help group, About's "Guide" button, the Loom's shell button -- and
   the one overlay that answers them is mounted once per page (HelpRoot.jsx). So the verb
   lives here and every door calls it.

   Three things ride along because the overlay cannot own them:

   1. THE SURFACE STACK. Each first-run guide host registers the surface it guides while it
      is mounted (GuideHost.jsx). The top of that stack is "where the person is", which is
      what the ? key opens Help on and what Help's "Replay this tour" replays.

   2. THE ESCAPE AND ? KEYS, on one window listener in the CAPTURE phase, installed when this
      module is first imported -- before any shell has mounted a listener of its own -- so
      it runs FIRST. While Help is up, Escape closes Help and stops there
      (stopImmediatePropagation): the shell's own ladders underneath (App.jsx's overlay
      closer, the Control Panel's, the palette's) never see it, so Escape closes one layer,
      the top one, exactly as everywhere else. The ? key opens Help outside text fields, the
      same "global keys fire only outside text fields" rule the palette states. A running
      tour claims Escape the same way (claimEscape), under Help.

   3. THE DOCS BEACON. Opening Help sends the "docs" feat event -- the same event the Loom's
      old hand-written guide sent -- through notify/achNonce.js's sendAchEvent, which owns
      the nonce, the adopt-next_nonce rotation and the one conditional stale-page retry; the
      server owns the 150ms debounce and the rate limit. One beacon per OPEN, never per page
      turned inside Help, and fail-soft: a refused beacon is silent. */

const EXIT_MS = 350;   // the handoff's exit (.35 s); the deferred unmount waits for it

let state = { open: false, closing: false, slug: "Home", anchor: "", from: "", nonce: 0 };
const subs = new Set();
let exitTimer = null;

function emit() { subs.forEach((fn) => { try { fn(state); } catch { /* a subscriber's own */ } }); }

export function subscribe(fn) {
  subs.add(fn);
  fn(state);
  return () => subs.delete(fn);
}
/* Up or on its way out -- what an Escape ladder underneath asks before it acts. */
export function isHelpUp() { return state.open || state.closing; }

/* ---- the surface stack ---- */
const surfaces = [];
const surfSubs = new Set();
function emitSurfaces() { surfSubs.forEach((fn) => { try { fn(); } catch { /* ignore */ } }); }
export function pushSurface(name) {
  const tok = { name };
  surfaces.push(tok);
  emitSurfaces();
  return () => {
    const i = surfaces.indexOf(tok);
    if (i >= 0) surfaces.splice(i, 1);
    emitSurfaces();
  };
}
export function currentSurface() {
  return surfaces.length ? surfaces[surfaces.length - 1].name : "";
}
export function isTopSurface(name) { return currentSurface() === name; }
export function subscribeSurfaces(fn) {
  surfSubs.add(fn);
  return () => surfSubs.delete(fn);
}

/* ---- open / close ---- */
function beacon() {
  try {
    Promise.resolve(sendAchEvent("docs")).catch(() => {});
  } catch { /* the feat announces; it never gates the guide */ }
}

/* How many HelpRoots are mounted on this page. The keys and the verbs are installed with
   this module, which the setup wizard's bundle also carries -- but the wizard mounts no
   guide, and a ? there must not open an overlay nobody draws (and then swallow the Escape
   meant for the wizard). So nothing opens without a host. */
let hosts = 0;
export function registerHelpHost() {
  hosts += 1;
  return () => { hosts = Math.max(0, hosts - 1); };
}

/* openHelp({slug, anchor, surface}) -- no slug opens the page for the surface (the one
   named, else the one on top of the stack, else the gallery's). */
export function openHelp(opts) {
  if (!hosts) return;
  const o = opts || {};
  const from = o.surface || currentSurface() || "gallery";
  clearTimeout(exitTimer);
  const wasOpen = state.open;
  state = {
    open: true, closing: false,
    slug: o.slug || pageForSurface(from), anchor: o.anchor || "",
    from, nonce: state.nonce + 1,
  };
  emit();
  if (!wasOpen) beacon();
}

export function closeHelp() {
  if (!state.open) return;
  state = { ...state, open: false, closing: true };
  emit();
  clearTimeout(exitTimer);
  exitTimer = setTimeout(() => { state = { ...state, closing: false }; emit(); }, EXIT_MS);
}

/* ---- About and what's new: their own two small layers ---- */
let about = { open: false, closing: false, lead: "", nonce: 0 };
let sheet = { open: false, closing: false, about: null };
const aboutSubs = new Set();
function emitAbout() { aboutSubs.forEach((fn) => { try { fn(about, sheet); } catch { /* ignore */ } }); }
export function subscribeAbout(fn) {
  aboutSubs.add(fn);
  fn(about, sheet);
  return () => aboutSubs.delete(fn);
}
let aboutTimer = null;
let sheetTimer = null;
/* lead: "" | "update" (the Control Panel stamp while a release is out -- the modal then
   leads with the update card) */
export function openAbout(lead) {
  if (!hosts) return;
  clearTimeout(aboutTimer);
  about = { open: true, closing: false, lead: lead || "", nonce: about.nonce + 1 };
  emitAbout();
}
export function closeAbout() {
  if (!about.open) return;
  about = { ...about, open: false, closing: true };
  emitAbout();
  clearTimeout(aboutTimer);
  aboutTimer = setTimeout(() => { about = { ...about, closing: false }; emitAbout(); }, EXIT_MS);
}
export function isAboutUp() { return about.open || about.closing; }
export function openWhatsNew(payload) {
  if (!hosts) return;
  clearTimeout(sheetTimer);
  sheet = { open: true, closing: false, about: payload || sheet.about };
  emitAbout();
}
export function closeWhatsNew() {
  if (!sheet.open) return;
  sheet = { ...sheet, open: false, closing: true };
  emitAbout();
  clearTimeout(sheetTimer);
  sheetTimer = setTimeout(() => { sheet = { ...sheet, closing: false }; emitAbout(); }, EXIT_MS);
}
export function isWhatsNewUp() { return sheet.open || sheet.closing; }

/* ---- "Show me ›": a shell opens a surface ---- */
/* Each shell listens for this and opens the surface its own way (App.jsx: the dock, an
   overlay; AppMobile.jsx: a tab). A shell that has no such surface (the Loom's, for the
   gallery ones) navigates to the gallery with the request carried in the address. */
export const OPEN_SURFACE_EVENT = "mg-open-surface";
export function requestSurface(surface) {
  let claimed = false;
  try {
    const ev = new CustomEvent(OPEN_SURFACE_EVENT, { detail: { surface }, cancelable: true });
    claimed = !window.dispatchEvent(ev);
  } catch { claimed = false; }
  if (!claimed) {
    try { window.location.href = surface === "loom" ? "/loom" : "/"; } catch { /* no window */ }
  }
}

/* ---- Escape claims, and the keys ---- */
const escClaims = [];
/* A layer that wants Escape while it is up (a running tour) claims it; the top claim wins,
   below Help and About. Returns the release. */
export function claimEscape(fn) {
  const tok = { fn };
  escClaims.push(tok);
  return () => {
    const i = escClaims.indexOf(tok);
    if (i >= 0) escClaims.splice(i, 1);
  };
}

const isTyping = (el) =>
  !!(el && el.closest && el.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));

function onKey(e) {
  if (e.key === "Escape") {
    let handled = false;
    if (sheet.open) { closeWhatsNew(); handled = true; }
    else if (about.open) { closeAbout(); handled = true; }
    else if (state.open) { closeHelp(); handled = true; }
    else if (state.closing || about.closing || sheet.closing) handled = true;
    else if (escClaims.length) {
      try { escClaims[escClaims.length - 1].fn(); } catch { /* the claimant's own */ }
      handled = true;
    }
    if (handled) { e.preventDefault(); e.stopImmediatePropagation(); }
    return;
  }
  if (e.key !== "?" || e.ctrlKey || e.metaKey || e.altKey || !hosts) return;
  if (e.defaultPrevented || isTyping(e.target)) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (state.open) closeHelp();
  else openHelp();
}

/* The Loom's shell button (moonglade_gallery.py's /loom page) sits outside every bundle, so
   it reaches the verb through this one global. */
let installed = false;
export function installHelpKeys() {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("keydown", onKey, true);
  window.mgHelp = { open: (slug) => openHelp(slug ? { slug } : undefined), close: closeHelp };
}
installHelpKeys();
