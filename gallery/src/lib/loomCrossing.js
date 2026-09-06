/* THE CROSSING'S MEMORY (owner call 2, 2026-09-06: "YESSS").

   "← Gallery" went to a bare "/". You were on page 7 with a picture open; you came back to
   the top of the library with nothing open. That is the exact loss gen/urlState.js's own
   header records the shell fixing for itself -- closeDetails() pushing a bare "/" and
   throwing the page away -- and the crossing was still doing it.

   WHAT CROSSES, AND WHY IT IS A STORED SNAPSHOT RATHER THAN A PARAMETER.

   The address was the other candidate: hand the library's own address to the Loom as
   `/loom?from=...`. It was refused for three grounded reasons.

   1. It would poison the thing this same pass just built. `/loom?board=<id>` exists to be
      BOOKMARKED (owner call 1: "100% yes, its what I wanted originally"). A library
      address baked in beside it makes every such bookmark carry a stale return trip.
   2. The Loom's address already has a settled contract for hand-offs: `?cast=` is read
      once on arrival and wiped (master-storyboard.jsx). A return address is the opposite
      -- it has to survive the whole visit -- so it does not belong in the same channel.
   3. Four doors lead into the Loom (the hero's button, the command palette's `g s`, "Send
      to Loom cast", and the phone sheet's "Open The Loom"), and one of them is a plain
      anchor. A parameter needs every door to build a href; ONE `pagehide` listener in
      main.jsx covers all four, plus a typed address, without touching any of them.

   sessionStorage is the codebase's own idiom for exactly this shape of thing -- per tab,
   for the length of the visit, never in the address: components/Darkroom.jsx keeps its
   filter selection there for the same reason. It survives the sign-in bounce (same tab),
   and a fresh tab that opens `/loom` straight from a bookmark simply has no snapshot, so
   the link falls back to "/" and says nothing untrue.

   WHAT IT DOES NOT CARRY: the library's FILTERS. Not an oversight -- the library does not
   restore its filters on any reload today (useLibrary.js holds them as plain state, and
   its mount effect judges "mount" by load's identity, so applying filters after mount
   forces page 1 and would throw the restored page away). Making them survive means seeding
   useLibrary's filter state at boot, which is a change to the LIBRARY's own boot path, not
   to the crossing. Named here so it is a decision rather than a gap.

   Pure functions plus a thin store layer: the store is passed in, so the tests drive this
   with a plain object and no DOM. */

export const RETURN_KEY = "mg_loom_return";

/* Same-site PATH only, and never the Loom itself.

   The value is written by this app into this browser's own sessionStorage, so this is a
   belt-and-braces read guard rather than a defence against a hostile writer -- but it is
   the same shape moonglade_gallery.py's _safe_next() enforces on ?next=, and for the same
   reason: a stored string that becomes a `href` must not be able to turn into
   "//evil.example" or carry a control character. "/loom" is rejected on top of that for a
   plainer reason -- a back link that lands you back in the Loom is a loop, not a return. */
export function safeLibraryPath(url) {
  const s = String(url == null ? "" : url);
  if (!s.startsWith("/") || s.startsWith("//")) return null;
  if (/[\\\t\r\n]/.test(s)) return null;
  const path = s.split(/[?#]/)[0];
  if (path === "/loom" || path.startsWith("/loom/")) return null;
  return s;
}

/* {url, scrollY} -> the stored string. Pure. */
export function packReturn(snap) {
  const url = safeLibraryPath(snap && snap.url);
  if (!url) return null;
  const y = Math.max(0, Math.round(Number((snap && snap.scrollY) || 0)) || 0);
  return JSON.stringify({ url, scrollY: y });
}

/* The stored string -> {url, scrollY}. Junk, absence and a rejected path all answer the
   same honest default: the library's front door, at the top. */
export function unpackReturn(raw) {
  const fallback = { url: "/", scrollY: 0 };
  if (!raw) return fallback;
  let d = null;
  try { d = JSON.parse(raw); } catch (e) { return fallback; }
  if (!d || typeof d !== "object") return fallback;
  const url = safeLibraryPath(d.url);
  if (!url) return fallback;
  const y = Number(d.scrollY);
  return { url, scrollY: Number.isFinite(y) && y > 0 ? Math.round(y) : 0 };
}

/* Record where the library was. Called once, from main.jsx's pagehide handler, so it
   covers every way out of the library -- including doors this module does not own. */
export function rememberLibrary(url, scrollY, store) {
  const packed = packReturn({ url, scrollY });
  if (!packed || !store) return false;
  try { store.setItem(RETURN_KEY, packed); return true; }
  catch (e) { return false; }   // private mode / storage disabled: the link falls back to "/"
}

/* Read it back. Never throws; always answers a usable snapshot. */
export function readLibraryReturn(store) {
  if (!store) return { url: "/", scrollY: 0 };
  let raw = null;
  try { raw = store.getItem(RETURN_KEY); } catch (e) { return { url: "/", scrollY: 0 }; }
  return unpackReturn(raw);
}

/* Did THIS library load arrive from the Loom?

   The scroll offset is restored only on the return trip, never on an ordinary reload --
   the library standing still where you left it is the crossing's promise, not a new
   universal behaviour. document.referrer answers it for free on a same-origin link
   navigation, with no marker to arm, consume, or leak. Pure over the two strings so the
   test can drive it. */
export function cameFromLoom(referrer, origin) {
  if (!referrer || !origin) return false;
  let u = null;
  try { u = new URL(referrer); } catch (e) { return false; }
  if (u.origin !== origin) return false;
  return u.pathname === "/loom" || u.pathname.startsWith("/loom/");
}
