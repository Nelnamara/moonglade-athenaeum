import { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import { peek } from "../hooks/swrCache.js";
import { visiblePages } from "./helpCore.js";

/* The guide's reads, each fetched once per page load and shared: the page index (the
   overlay, the palette's Help group), the pages themselves as they are opened, and the
   About card's payload (About, the post-update toast, the what's-new sheet). The wiki on
   disk cannot change under a running server without a restart -- an update is a pull and a
   restart -- so a page read once is good for the life of the tab. A FAILED read is not
   kept: the next ask tries again. */

const memo = new Map();
function once(key, load) {
  if (!memo.has(key)) {
    const p = load().then((d) => {
      if (!d || d.error) memo.delete(key);
      return d;
    });
    memo.set(key, p);
  }
  return memo.get(key);
}

export function loadIndex() { return once("index", () => apiGet("/api/help/index")); }
export function loadPage(slug) {
  return once("page:" + slug, () => apiGet("/api/help/page/" + encodeURIComponent(slug)));
}
export function loadAbout() { return once("about", () => apiGet("/api/help/about")); }
/* Not memoized: whether a newer page is online is the server's cached answer to give. */
export function checkOnline(slug) { return apiGet("/api/help/online/" + encodeURIComponent(slug)); }

/* Is the Branding tab unlocked, as far as this page already knows? Read from the shared
   achievements cache the Folio and the Panel fill; nothing is fetched for it. Unknown is
   locked, which is the fail-safe direction for a hidden tab. */
export function brandingKnownUnlocked() {
  // The same test as hooks/useControlPanel.js's brandingUnlockedIn, restated rather than
  // imported so the Loom's bundle does not carry the whole Panel hook for one line.
  try {
    const d = peek("/api/achievements");
    return ((d && d.achievements) || []).some((a) => a && a.unlocks === "branding_tab" && a.earned);
  } catch { return false; }
}

/* The index as this person may see it (helpCore.visiblePages). */
export function visibleIndex(index) {
  if (!index || index.error) return index;
  return { ...index, pages: visiblePages(index.pages, brandingKnownUnlocked()) };
}

/* React: the index, or null until it lands. `enabled` false defers the read. */
export function useGuideIndex(enabled) {
  const [index, setIndex] = useState(null);
  useEffect(() => {
    if (enabled === false) return undefined;
    let live = true;
    loadIndex().then((d) => { if (live && d && !d.error) setIndex(visibleIndex(d)); });
    return () => { live = false; };
  }, [enabled]);
  return index;
}

export function useAbout(enabled) {
  const [about, setAbout] = useState(null);
  useEffect(() => {
    if (enabled === false) return undefined;
    let live = true;
    loadAbout().then((d) => { if (live && d && !d.error) setAbout(d); });
    return () => { live = false; };
  }, [enabled]);
  return about;
}
