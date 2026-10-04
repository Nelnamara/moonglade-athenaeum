import { useCallback, useMemo, useSyncExternalStore } from "react";
import { connectionInfo, saverActive, saverSub } from "../lib/phoneCore.js";
import {
  PREFS_EVENT, readLayout, readPaging, readPagingHintSeen, readSaverMode, writeLayout, writePaging,
  writePagingHintSeen, writeSaverMode,
} from "../lib/phonePrefs.js";

/* React readers for the phone's per-device values (lib/phonePrefs.js says what they are and that
   nothing writes on open). useSyncExternalStore over the change event phonePrefs announces, plus the
   cross-tab `storage` event, so the Control row, the gallery's Grid | Feed toggle and the header's
   Saver chip are always looking at the same value and none of them keeps a copy. */

function subscribePrefs(cb) {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(PREFS_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(PREFS_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

/* [layout, setLayout] -- "grid" | "feed". */
export function useFeedLayout() {
  const layout = useSyncExternalStore(subscribePrefs, () => readLayout(), () => "grid");
  const setLayout = useCallback((v) => { writeLayout(v); }, []);
  return [layout, setLayout];
}

/* [paging, setPaging] -- "pages" | "continuous" (Session U). The long-press sheet on the layout keys and
   Control's Library paging row both read and set this one value. */
export function usePaging() {
  const paging = useSyncExternalStore(subscribePrefs, () => readPaging(), () => "pages");
  const setPaging = useCallback((v) => { writePaging(v); }, []);
  return [paging, setPaging];
}

/* [seen, markSeen] -- whether the one-time dot under the layout keys has done its job. The first
   long-press marks it; nothing else does. */
export function usePagingHint() {
  const seen = useSyncExternalStore(subscribePrefs, () => readPagingHintSeen(), () => true);
  const markSeen = useCallback(() => { writePagingHintSeen(); }, []);
  return [seen, markSeen];
}

/* The Network Information API where the browser has it (Chrome on Android does; iPhone browsers
   do not, and neither do desktop Safari or Firefox). The snapshot is a string so React can compare
   it by value. */
function connection() {
  try { return typeof navigator !== "undefined" ? navigator.connection || null : null; } catch { return null; }
}
function connSnapshot() {
  const c = connection();
  return c ? "api|" + (typeof c.type === "string" ? c.type : "") + "|" + (c.saveData === true ? "1" : "0") : "none";
}
function subscribeConn(cb) {
  const c = connection();
  if (!c || typeof c.addEventListener !== "function") return () => {};
  c.addEventListener("change", cb);
  return () => c.removeEventListener("change", cb);
}

/* The saver as the whole phone reads it: {mode, setMode, active, sub, info}. `active` is what every
   consumer asks -- the grid's thumbnail size, the Lightbox's tap-to-load, the header chip, the
   background refresh -- and it already folds in the connection for Auto. */
export default function useDataSaver() {
  const mode = useSyncExternalStore(subscribePrefs, () => readSaverMode(), () => "auto");
  const snap = useSyncExternalStore(subscribeConn, connSnapshot, () => "none");
  const info = useMemo(() => {
    if (snap === "none") return connectionInfo(null);
    const [, type, sd] = snap.split("|");
    return connectionInfo({ type, saveData: sd === "1" });
  }, [snap]);
  const setMode = useCallback((m) => { writeSaverMode(m); }, []);
  return {
    mode, setMode, info,
    active: saverActive(mode, info),
    sub: saverSub(mode, info),
  };
}
