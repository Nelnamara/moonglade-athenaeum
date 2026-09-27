/* "OPEN THE CONTROL PANEL ON THIS TAB" -- one request, three shells, no prop chain.

   The asker (today: the key-turn moment's button) lives at body level and cannot reach any
   shell's state, and the Control Panel is several trees away from it. So it asks the page,
   in two steps:

     openPanelHere(tab) -> true when THIS shell has a Control Panel and opened it on that
       tab. It dispatches a cancelable `mg-open-control-panel` event carrying {tab}; a shell
       that has a panel claims it (preventDefault): App.jsx opens its overlay, AppMobile.jsx
       switches to its Control tab and opens the drill-in.
     carryPanelTab(tab) -> for a shell with no panel (the Loom): the request is written down
       as a ONE-SHOT and the page goes to the gallery, whose shell takes it on boot
       (takeCarriedPanelTab) and honours it there.

   requestPanelTab(tab) is the two in order, for a caller with nothing to do in between.

   sessionStorage for the crossing, as notify/bannerStore.js's update intent does and for
   the same reasons: it belongs to this tab's navigation and must not outlive it. A browser
   with storage blocked carries it as ?panel=<tab> instead, read once and stripped. */
export const OPEN_PANEL_EVENT = "mg-open-control-panel";
const CARRY_KEY = "mg_panel_tab_request";

function session() {
  try { return (typeof window !== "undefined" && window.sessionStorage) || null; }
  catch { return null; }
}

export function openPanelHere(tab) {
  if (typeof window === "undefined" || !tab) return false;
  try {
    const ev = new CustomEvent(OPEN_PANEL_EVENT, { detail: { tab }, cancelable: true });
    return !window.dispatchEvent(ev);
  } catch { return false; }
}

export function carryPanelTab(tab) {
  if (typeof window === "undefined" || !tab) return "none";
  let carried = false;
  const s = session();
  if (s) { try { s.setItem(CARRY_KEY, String(tab)); carried = true; } catch { /* blocked */ } }
  const here = (window.location && window.location.pathname) || "/";
  if (here === "/") return carried ? "stored" : "none";   // already the gallery: nowhere to go
  window.location.assign(carried ? "/" : "/?panel=" + encodeURIComponent(tab));
  return "navigating";
}

export function requestPanelTab(tab) {
  return openPanelHere(tab) ? "opened" : carryPanelTab(tab);
}

/* Read ONCE by the shell that can honour it, on boot. "" when there is nothing waiting. */
export function takeCarriedPanelTab() {
  let tab = "";
  const s = session();
  if (s) {
    try {
      const v = s.getItem(CARRY_KEY);
      if (v !== null) { s.removeItem(CARRY_KEY); tab = v; }
    } catch { /* blocked */ }
  }
  if (typeof window === "undefined" || !window.location) return tab;
  const search = String(window.location.search || "");
  if (search.indexOf("panel=") < 0) return tab;
  try {
    const params = new URLSearchParams(search);
    const v = params.get("panel");
    if (v === null) return tab;
    params.delete("panel");
    const rest = params.toString();
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "",
        (window.location.pathname || "/") + (rest ? "?" + rest : "") + (window.location.hash || ""));
    }
    return tab || v;
  } catch { return tab; }
}
