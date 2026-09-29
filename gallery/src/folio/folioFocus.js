/* THE FOLIO'S DEEP-LINK. The earn moment's "See it in the Folio" (notify/ach.js) opens the
   Folio from outside its component tree, so it leaves the feat to scroll to here and the
   Folio takes it on mount. One slot, consumed on read: a stale request can never steer a
   later, unrelated open. The id is one the server already listed as EARNED. */
let _focus = null;
export function setFolioFocus(id) { _focus = typeof id === "string" && id ? id : null; }
export function takeFolioFocus() { const f = _focus; _focus = null; return f; }

/* THE FOLIO'S ROW LINK (Session O, O4). The header's pinned-goal chip opens the Folio with that
   honor's row ringed. Same one-slot, consumed-on-read shape as the feat link above, but for an
   honor with a count: the Folio scrolls the row into view, rings it, and (on the phone) picks
   its ladder. The id is only ever a request -- the Folio ignores one it cannot find, and a
   feat or an earned honor has no row to ring. */
let _row = null;
export function setFolioRow(id) { _row = typeof id === "string" && id ? id : null; }
export function takeFolioRow() { const r = _row; _row = null; return r; }

/* The Loom has no Folio, so its chip crosses to the gallery with the request in the address:
   "#folio" or "#folio=<id>". The gallery reads it once on mount, opens the Folio and strips it. */
export function folioHref(id) {
  return "/#folio" + (id ? "=" + encodeURIComponent(id) : "");
}
export function readFolioHash(hash) {
  const m = /^#?folio(?:=([^&]*))?$/.exec(String(hash || ""));
  if (!m) return null;
  let row = "";
  try { row = m[1] ? decodeURIComponent(m[1]) : ""; } catch { row = ""; }
  return { row: row.length <= 96 ? row : "" };
}
