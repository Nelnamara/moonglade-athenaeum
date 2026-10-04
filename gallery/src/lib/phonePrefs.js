/* The phone's three per-device values (Session Q): the Grid | Feed layout, the Data saver mode and the
   "last seen" marker behind "N new since". Browser storage, per device, the way blurPref.js keeps the
   popup blur -- a property of THIS phone, not of the account: the same owner reads a feed on the phone
   and a grid at the desk, wants the saver on the train and not at home. No API call, no round trip.

   NOTHING HERE WRITES ON OPEN. Every write function below is called from exactly one kind of place: a
   tap (the layout toggle, a Data saver mode), a completed pull (the marker is left alone by one on
   purpose -- the rule stays where it was until you leave), or the moment the gallery is left (a tab
   tap, or the page being hidden). Reads never write; a missing key is the default, and no default is
   ever stored back. loom/test/phone-prefs.test.js holds all of that, and the render harness watches
   localStorage on a real page.

   Storage can throw outright (private mode, site data blocked): every read answers the default and
   every write is a no-op then, so the phone renders exactly as it did before this file existed.

   `storage` is a parameter (default: the real localStorage) only so the tests can hand in a recording
   stand-in. A change made here is announced on `window` (PREFS_EVENT) so every mounted reader -- the
   Control row, the gallery's toggle, the header chip -- moves together without any of them holding a
   copy. */

/* SESSION U adds two more, written the same way (a tap, never an open): the paging choice (Pages |
   Continuous, set from the long-press sheet on the layout keys or Control's Library paging row) and
   whether the long-press hint dot under those keys has done its job (written by the first long-press).
   And one more: the Home Screen nudge's ✕ on this device. */

import { DEFAULT_LAYOUT, parseLayout, parseMarker, parsePaging, parseSaverMode } from "./phoneCore.js";

export const LAYOUT_KEY = "mg_phone_layout";
export const SAVER_KEY = "mg_phone_saver";
export const SEEN_KEY = "mg_phone_seen";
export const PAGING_KEY = "mg_phone_paging";
export const PAGING_HINT_KEY = "mg_phone_paging_hint";
export const NUDGE_OFF_KEY = "mg_phone_nudge_off";
export const PREFS_EVENT = "mg-phone-prefs";

function store(storage) {
  if (storage) return storage;
  try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; }
}

function read(key, storage) {
  try { const s = store(storage); return s ? s.getItem(key) : null; } catch { return null; }
}

function write(key, value, storage) {
  try {
    const s = store(storage);
    if (!s) return false;
    s.setItem(key, value);
  } catch { return false; }
  try {
    if (typeof window !== "undefined" && window.dispatchEvent && typeof CustomEvent === "function") {
      window.dispatchEvent(new CustomEvent(PREFS_EVENT, { detail: { key } }));
    }
  } catch { /* a listener threw; the value is stored */ }
  return true;
}

export function readLayout(storage) {
  return parseLayout(read(LAYOUT_KEY, storage) || DEFAULT_LAYOUT);
}
export function writeLayout(layout, storage) {
  return write(LAYOUT_KEY, parseLayout(layout), storage);
}

export function readSaverMode(storage) {
  return parseSaverMode(read(SAVER_KEY, storage));
}
export function writeSaverMode(mode, storage) {
  return write(SAVER_KEY, parseSaverMode(mode), storage);
}

export function readPaging(storage) {
  return parsePaging(read(PAGING_KEY, storage));
}
export function writePaging(paging, storage) {
  return write(PAGING_KEY, parsePaging(paging), storage);
}

export function readPagingHintSeen(storage) {
  return read(PAGING_HINT_KEY, storage) === "1";
}
export function writePagingHintSeen(storage) {
  return write(PAGING_HINT_KEY, "1", storage);
}

/* The Home Screen nudge's ✕ (Session U, U6c): waved off on this device for good. Written by the ✕
   only. */
export function readNudgeOff(storage) {
  return read(NUDGE_OFF_KEY, storage) === "1";
}
export function writeNudgeOff(storage) {
  return write(NUDGE_OFF_KEY, "1", storage);
}

export function readMarker(storage) {
  return parseMarker(read(SEEN_KEY, storage));
}
export function writeMarker(marker, storage) {
  if (!marker || !marker.id) return false;
  return write(SEEN_KEY, JSON.stringify({ id: marker.id, ts: marker.ts || 0, at: marker.at || 0 }), storage);
}
