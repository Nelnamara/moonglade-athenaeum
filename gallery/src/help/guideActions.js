import { accountPrefs } from "../hooks/useAccountPrefs.js";
import { GUIDE_SURFACES, NOTES_HIDDEN_KEY, guideKey } from "./guideCore.js";

/* Help's three guide rows (Session I decision 1), as verbs on the account's own store --
   the same writes the welcome card and the notes make, from outside any one surface. */

let replay = 0;
const subs = new Set();
export function replayCount() { return replay; }
export function subscribeReplay(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}

/* "Replay this tour": the surface Help was opened from goes back to its tour, from step 1
   (the count bump restarts a tour whose key already said "tour"). */
export function replayTour(surface) {
  if (!GUIDE_SURFACES.includes(surface)) return Promise.resolve({ error: "no guide here" });
  replay += 1;
  subs.forEach((fn) => { try { fn(replay); } catch { /* ignore */ } });
  return accountPrefs().set(guideKey(surface), "tour");
}

/* "Hide Nel's notes" / "Show Nel's notes", everywhere at once. */
export function setNotesHidden(hidden) {
  const store = accountPrefs();
  return hidden ? store.set(NOTES_HIDDEN_KEY, true) : store.unset(NOTES_HIDDEN_KEY);
}

/* "Reset guides": every surface back to its first visit, notes back on. A surface whose
   key was never written (Branding before its tab exists) simply has nothing to clear. */
export async function resetGuides() {
  const store = accountPrefs();
  await store.ensureLoaded();
  const have = store.getSnapshot().prefs || {};
  const keys = GUIDE_SURFACES.map(guideKey).concat([NOTES_HIDDEN_KEY])
    .filter((k) => Object.prototype.hasOwnProperty.call(have, k));
  for (const k of keys) {
    // Sequential, through the store's own queue: each answer is the whole document.
    // eslint-disable-next-line no-await-in-loop
    const r = await store.unset(k);
    if (r && r.error) return r;
  }
  return { ok: true };
}
