/* THE LOOM'S OWN ADDRESS (2026-09-06, the arena's plumbing half).

   `/loom` was one address with one hand-off parameter (`?cast=`, read once and wiped).
   Which storyboard was open lived only on the server, under `storyboard:v2:active` --
   so a board was something the app remembered for you, never somewhere you could go.
   `/loom?board=<id>` makes it a place: bookmark it, send it to yourself, come back.

   ONE BUILDER, the library's own discipline. gallery/src/gen/urlState.js exists because
   the shell's history writes used to throw each other's parameters away -- closeDetails()
   pushed a bare "/" and lost the page the grid was on. The Loom is one parameter away from
   the same class of bug: the cast hand-off's own cleanup wrote `location.pathname`, which
   would erase `?board=` the moment someone arrived with both. Every history write in the
   Loom goes through buildLoomUrl() now, patching only the keys it is handed.

   Pure functions over query strings -- no DOM, no React, no `location` -- so the tests
   drive them directly. master-storyboard.jsx owns the window.location/history calls, the
   same split loom-core.js and loom-mutations.js already keep. */

/* A storyboard id is what uid() makes: Math.random().toString(36).slice(2, 7-ish) --
   short, lowercase alphanumeric. This is deliberately a URL SANITISER with a generous
   grammar rather than a uid() shape check, for exactly the reason
   loom-mutations.js's parseCastIdsFromSearch documents at its own filter: ids arriving
   from the address must not be able to escape a query or a path (no slashes, quotes,
   angle brackets, spaces), and "is this a REAL board" is the store's question, not the
   parser's -- a well-formed id that names no board is a miss, not an attack, and the
   caller answers it with the corner note. */
export function isBoardId(s) {
  return /^[A-Za-z0-9_-]{1,64}$/.test(String(s == null ? "" : s));
}

/* ?board=<id>, or null when absent or unusable. Never throws on junk. */
export function readBoardId(search) {
  let raw = null;
  try { raw = new URLSearchParams(search || "").get("board"); }
  catch (e) { return null; }
  return isBoardId(raw) ? raw : null;
}

/* buildLoomUrl(patch, search, pathname) -> "path?query"

   Starts from the CURRENT query string and applies ONLY the keys the patch names:
     { board: id }   -> ?board=id; null/""/an unusable id drops the param
     { cast: null }  -> drops ?cast= (the hand-off's own cleanup, once it has been read)
   A key the patch doesn't mention is left exactly as it was. Built from URLSearchParams,
   never string-concatenated, so encoding and any other parameter present survive. */
export function buildLoomUrl(patch, search, pathname) {
  let p;
  try { p = new URLSearchParams(search || ""); }
  catch (e) { p = new URLSearchParams(""); }
  const patchObj = patch || {};
  if ("board" in patchObj) {
    if (isBoardId(patchObj.board)) p.set("board", String(patchObj.board));
    else p.delete("board");
  }
  if ("cast" in patchObj) {
    if (patchObj.cast) p.set("cast", String(patchObj.cast));
    else p.delete("cast");
  }
  const qs = p.toString();
  return (pathname || "/loom") + (qs ? "?" + qs : "");
}

/* THE PHONE'S AUTO-OPEN (owner call 5, 2026-09-06).

   "Yes, I want to be mindful of the tablet still being able to use desktop... I don't
   want a Tablet design pass anytime soon." So the Loom's phone layout opens by itself on
   a PHONE and nowhere else, keyed on the app's one existing phone rule
   (gallery/src/hooks/useIsMobile.js -- a 430px query plus the coarse-pointer + portrait +
   screen.width <= 430 fallback). A tablet's screen.width is above 430, so it stays on the
   desktop build BY CONSTRUCTION rather than by a second threshold nobody maintains.

   AUTO IS ONLY THE DEFAULT. Both manual switches stay exactly as they are -- the
   "Mobile view" checkbox in the Loom's top bar and the "Desktop" chip in the phone bar --
   and a switch the owner actually flips wins forever after, in either direction.

   Why a NEW key rather than reading the old one: the old toggle rode useLocalToggle, which
   writes its value in an effect on mount. Every browser that has ever opened the Loom
   therefore already holds "mg_loom_mobile_ui" = "0" -- a stored answer nobody ever gave.
   Auto-open gated on that key would silently never fire on exactly the phones it is for.
   "mg_loom_view" is only ever written by a real flip, so ABSENT honestly means "not asked
   yet, follow the phone rule". The legacy "1" is the one old value that could only have
   come from a deliberate tick, so it is honoured as a choice; a legacy "0" is discarded as
   the non-answer it was. */
export const LOOM_VIEW_KEY = "mg_loom_view";           // "mobile" | "desktop"; absent = auto
export const LEGACY_MOBILE_UI_KEY = "mg_loom_mobile_ui";

/* The stored answer, or null for "never asked". Pure over a plain {get} store. */
export function readStoredView(store) {
  if (!store) return null;
  let v = null;
  try { v = store.getItem(LOOM_VIEW_KEY); } catch (e) { return null; }
  if (v === "mobile" || v === "desktop") return v;
  let legacy = null;
  try { legacy = store.getItem(LEGACY_MOBILE_UI_KEY); } catch (e) { return null; }
  return legacy === "1" ? "mobile" : null;
}

/* The one decision: an explicit choice wins; otherwise follow the phone rule. */
export function resolveLoomView(stored, isPhone) {
  if (stored === "mobile") return true;
  if (stored === "desktop") return false;
  return !!isPhone;
}
