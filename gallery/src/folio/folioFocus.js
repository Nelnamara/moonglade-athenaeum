/* THE FOLIO'S DEEP-LINK. The earn moment's "See it in the Folio" (notify/ach.js) opens the
   Folio from outside its component tree, so it leaves the feat to scroll to here and the
   Folio takes it on mount. One slot, consumed on read: a stale request can never steer a
   later, unrelated open. The id is one the server already listed as EARNED. */
let _focus = null;
export function setFolioFocus(id) { _focus = typeof id === "string" && id ? id : null; }
export function takeFolioFocus() { const f = _focus; _focus = null; return f; }
