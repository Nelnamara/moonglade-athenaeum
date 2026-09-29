/* THE UNLEASH SWITCH, ACCOUNT-WIDE (Session L, decision 1).

   "Do you want the spicier line?" used to be a per-browser setting (localStorage["unleash"]).
   It is the account's now -- the key `unleash` in the per-account preferences store -- so the
   same person sees the same narrator on the phone and at the desk. The switch itself is
   unchanged and stays a secret: it is the ruby "Unleash the AI" pill in the Folio's header,
   there only once the feat behind it is earned, and never in the Control Panel.

   ONE GATE, NOT TWO. The server still decides whether the spicier line is RELEASED (it is
   withheld until the feat is earned); this only says whether the person WANTS it. Both read
   the same boolean the glitch reveal always read.

   THE OLD VALUE MOVES ONCE. A browser that held unleash = "1" carries it to the account the
   first time it loads after the change -- but only when the account has no stored value of
   its own -- and then drops the key. A key that is not "1" has nothing to carry and is just
   dropped; an account that already answered is never overwritten by an old browser.

   Pure where it can be (the plan), with the one impure runner taking its store and its
   storage as parameters so a test can hand it fakes. */

export const UNLEASH_KEY = "unleash";
export const LEGACY_KEY = "unleash";     // the old localStorage key -- the same word, another home

/* Is the switch on, given the account's preference document. Only a real `true` counts. */
export function isUnleashed(prefs) {
  return !!prefs && prefs[UNLEASH_KEY] === true;
}

/* What the one-time migration should do. `status` is the store's ("ready" once the account's
   document has arrived), `stored` the account's value (undefined when it has none), `legacy`
   this browser's old value (null when there is none).
     wait   the account has not answered yet -- decide nothing
     write  carry the browser's "1" to the account
     clear  drop the old key (after a successful write, or straight away when there is none
            to carry)  */
export function migrationPlan({ status, stored, legacy }) {
  if (status === "error") return { wait: false, write: false, clear: false };   // no account to move to
  if (status !== "ready") return { wait: true, write: false, clear: false };
  if (legacy === null || legacy === undefined) return { wait: false, write: false, clear: false };
  if (stored !== undefined) return { wait: false, write: false, clear: true };
  if (legacy === "1") return { wait: false, write: true, clear: true };
  return { wait: false, write: false, clear: true };
}

/* The runner. `store` is the account preferences store (ensureLoaded/get/set), `storage`
   a Storage-like (getItem/removeItem) or null. Never throws; resolves to the plan it
   followed. The old key is dropped only once the account really holds the value. */
export async function syncLegacyUnleash(store, storage) {
  let legacy = null;
  try { legacy = storage ? storage.getItem(LEGACY_KEY) : null; } catch { legacy = null; }
  if (legacy === null) return migrationPlan({ status: "ready", stored: undefined, legacy: null });
  let ok = false;
  try { ok = await store.ensureLoaded(); } catch { ok = false; }
  const plan = migrationPlan({
    status: ok ? "ready" : "error",
    stored: ok ? store.get(UNLEASH_KEY, undefined) : undefined,
    legacy,
  });
  const drop = () => { try { storage.removeItem(LEGACY_KEY); } catch { /* blocked storage */ } };
  if (plan.write) {
    let res = null;
    try { res = await store.set(UNLEASH_KEY, true); } catch { res = { error: "failed" }; }
    if (res && !res.error) drop();
    return plan;
  }
  if (plan.clear) drop();
  return plan;
}
