/* The doors into Health's Broken files list (Session W, W1a / W4c / W6a).

   Three places open it without owning Health: the Control Panel's "Verify library integrity"
   row ("N broken · Review ▸", opens at All), the Activity row of a fix run (back to the
   section), and the phone's Control tab. Each calls openBrokenFiles(chip); the shell that is
   running (App.jsx on the desktop, AppMobile.jsx on the phone) registers how Health comes up,
   and the list reads the chip it was asked for -- on mount (takeBrokenFilesIntent) or, when
   Health is already open, live (subscribeBrokenFilesIntent). Same shape as notify/ach.js's
   registerFolioOpener: one registration per shell, no prop chain. Imports nothing. */

let opener = null;
let pending = null;            // the chip asked for and not yet taken
const subs = new Set();

export function registerBrokenFilesOpener(fn) {
  opener = typeof fn === "function" ? fn : null;
  return () => { if (opener === fn) opener = null; };
}

export function hasBrokenFilesOpener() { return !!opener; }

/* Bring Health up at the Broken files section with `chip` selected ("all" by default). */
export function openBrokenFiles(chip) {
  pending = chip || "all";
  subs.forEach((fn) => { try { fn(pending); } catch { /* a listener's own */ } });
  if (opener) opener(pending);
}

/* The chip a door asked for, once: the list takes it when it mounts. */
export function takeBrokenFilesIntent() {
  const c = pending;
  pending = null;
  return c;
}

export function subscribeBrokenFilesIntent(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}
