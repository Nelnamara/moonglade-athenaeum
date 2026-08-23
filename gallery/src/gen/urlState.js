/* The gallery's URL state (#31, "Where the Refit Broke" #7): ?page=N and ?image=<mid>
   on the SPA's own address. ONE builder for every history write in the shell, so no
   caller can throw another caller's param away -- closeDetails() used to push a bare
   "/" and lose the page the grid was on the moment the owner closed a picture, and
   nothing read ?page= at all (the refit dropped the classic's page addressing).

   Pure functions over query strings: the tests drive them without a DOM. App.jsx
   owns the window.location / history calls. */

/* ?page= as an integer >= 1; anything else (absent, junk, 0, negative) is page 1. */
export function readPage(search) {
  const raw = new URLSearchParams(search || "").get("page");
  const n = parseInt(raw || "", 10);
  return Number.isFinite(n) && n >= 1 ? n : 1;
}

/* ?image= (a media_id) or null. */
export function readImage(search) {
  return new URLSearchParams(search || "").get("image") || null;
}

/* buildUrl(patch, search, pathname) -> "path?query"

   Starts from the CURRENT query string and applies ONLY the keys the patch names:
     { page: N }      -> ?page=N; page 1 is the address's default and is OMITTED
     { image: mid }   -> ?image=mid; null/"" drops the param
   A key the patch doesn't mention is left exactly as it was -- that is the whole
   point: opening/closing Details keeps ?page=, flipping pages keeps ?image=.
   Built from URLSearchParams, never string-concatenated, so encoding and any
   other param present survive untouched. */
export function buildUrl(patch, search, pathname) {
  const p = new URLSearchParams(search || "");
  const patchObj = patch || {};
  if ("page" in patchObj) {
    const n = parseInt(patchObj.page, 10);
    if (Number.isFinite(n) && n > 1) p.set("page", String(n));
    else p.delete("page");
  }
  if ("image" in patchObj) {
    if (patchObj.image) p.set("image", String(patchObj.image));
    else p.delete("image");
  }
  const qs = p.toString();
  return (pathname || "/") + (qs ? "?" + qs : "");
}
