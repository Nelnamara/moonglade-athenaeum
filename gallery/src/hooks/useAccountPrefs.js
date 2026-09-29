import { useCallback, useEffect, useSyncExternalStore } from "react";
import { apiGet, apiPost } from "../api.js";
import { createPrefsStore, readPref } from "./accountPrefsStore.js";

/* useAccountPrefs -- the signed-in account's own preferences, shared by every component
   on the page (2026-09-28, wave 1 foundation; no consumer yet).

   One store per page, created on first use: ONE GET of /api/account/prefs no matter how
   many components call the hook, and every one of them re-renders from the same snapshot
   when anything changes. The logic -- the shared load, the optimistic write, the rollback
   -- lives in accountPrefsStore.js, importless, where loom/test/account-prefs-store.test.js
   pins it; this file only wires that store to api.js and to React.

     const { ready, get, set, unset } = useAccountPrefs();
     const seen = get("seen.whatsnew", "");        // fallback while loading or absent
     set("seen.whatsnew", build);                  // shows at once; rolls back on failure

   set/unset resolve to {ok: true} or {error} (never throw), the same answer shape as
   api.js. Keys are lowercase dotted names; the server refuses anything else with a plain
   message, and so does set() before it sends.

   CSRF: explicit-token class, as api.js's header says every caller does it. The token
   rides on this route's own GET answer (the same way /api/myart/items hands its out) and
   is sent as a body field on every POST; window.MG_BOOT.csrf -- the same session token --
   is the fallback if the GET never answered. */

const PATH = "/api/account/prefs";
let _csrf = "";
let _store = null;

function _bootCsrf() {
  try {
    return (typeof window !== "undefined" && window.MG_BOOT && window.MG_BOOT.csrf) || "";
  } catch {
    return "";
  }
}

/** The page's one preferences store, for code outside a component. */
export function accountPrefs() {
  if (!_store) {
    _store = createPrefsStore({
      load: async () => {
        const d = await apiGet(PATH);
        if (d && d.csrf) _csrf = d.csrf;
        return d;
      },
      save: (patch) => apiPost(PATH, { ...patch, csrf: _csrf || _bootCsrf() }),
    });
  }
  return _store;
}

export default function useAccountPrefs() {
  const store = accountPrefs();
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  useEffect(() => { store.ensureLoaded(); }, [store]);
  const get = useCallback((key, fallback) => readPref(snap.prefs, key, fallback), [snap]);
  return {
    prefs: snap.prefs,
    status: snap.status,
    ready: snap.status === "ready",
    error: snap.error,
    get,
    set: store.set,
    unset: store.unset,
  };
}
