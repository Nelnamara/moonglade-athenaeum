/* Session Q, "The phone" (Phone Handoff.dc.html, Q1 / Q3 / Q5 / Q6 / Q7): the pure rules behind the
   placard, the reading feed, "new since", pull to refresh and Data saver. Everything here is a plain
   function of its arguments -- no DOM, no storage, no network -- so loom/test/phone-core.test.js holds
   the rules as written and the components only draw them.

   THE FIVE THINGS THAT ARE PER DEVICE and where their values live is gallery/src/lib/phonePrefs.js:
   the layout (Grid | Feed), the Data saver mode, and the "last seen" marker. Nothing in this file reads
   or writes any of them. */

/* ---------------------------------------------------------------------------------------------
   Layout (Q3)
   --------------------------------------------------------------------------------------------- */

export const LAYOUTS = Object.freeze(["grid", "feed"]);
export const DEFAULT_LAYOUT = "grid";

/* Anything that is not exactly a known layout is the grid: the phone as built. */
export function parseLayout(v) {
  return v === "feed" ? "feed" : "grid";
}

/* ---------------------------------------------------------------------------------------------
   Paging (Session U, Phone Paging and Nudge Handoff.dc.html U1b)
   --------------------------------------------------------------------------------------------- */

/* Pages is the phone as shipped (‹ Prev · Next ›); Continuous loads as you scroll. Per device, beside
   the layout; a long-press on either layout key opens the sheet that holds both. */
export const PAGINGS = Object.freeze(["pages", "continuous"]);
export const DEFAULT_PAGING = "pages";
export const PAGING_LABELS = Object.freeze({ pages: "Pages", continuous: "Continuous" });
export const KEY_LONG_PRESS_MS = 500;

/* Anything that is not exactly "continuous" is Pages: the phone as built. */
export function parsePaging(v) {
  return v === "continuous" ? "continuous" : "pages";
}

/* Continuous loading (U2a). The next 100 are asked for when the last row comes within 1.5 screens of
   view, one request at a time; while Data saver acts on a metered connection a page is 50 instead. */
export const CONTINUOUS_PAGE = 100;
export const CONTINUOUS_PAGE_METERED = 50;
export const PREFETCH_SCREENS = 1.5;

export function continuousPageSize(saverIsActive, info) {
  const i = info || connectionInfo(null);
  return saverIsActive && i.known && i.metered ? CONTINUOUS_PAGE_METERED : CONTINUOUS_PAGE;
}

/* The stacked list is always a run from the top of the filtered walk, so the next page is the one that
   starts at or just before its end -- whatever size cut the pages before it. After a pull has prepended
   K new pictures, or the size changed from 100 to 50, the page asked for overlaps what is loaded by
   fewer than one page; appendUnique drops the overlap. It can never leave a gap. */
export function nextContinuousPage(loaded, size) {
  const s = Math.min(MAX_PAGE_SIZE, Math.max(1, Math.floor(Number(size)) || CONTINUOUS_PAGE));
  return Math.floor(Math.max(0, Number(loaded) || 0) / s) + 1;
}

/* Append the pictures not already loaded, in order. Nothing new answers the SAME list (no re-render). */
export function appendUnique(old, fresh) {
  const list = old || [];
  const have = new Set(list.map((it) => it.media_id));
  const add = (fresh || []).filter((it) => it && !have.has(it.media_id) && (have.add(it.media_id), true));
  return add.length ? list.concat(add) : list;
}

/* The end: everything the filter matches is loaded. No total yet is not the end. */
export function continuousDone(loaded, total) {
  if (total == null || total === "") return false;
  const t = Number(total);
  return Number.isFinite(t) && Number(loaded) >= t;
}

/* Is the last row within 1.5 screens of the bottom of the view? `footTop` is the footer's top (the
   last row's foot), `viewBottom` the scroller's visible bottom, `viewHeight` its height. */
export function nearEnd(footTop, viewBottom, viewHeight) {
  const vh = Number(viewHeight) > 0 ? Number(viewHeight) : 560;
  return Number(footTop) - Number(viewBottom) <= PREFETCH_SCREENS * vh;
}

/* "300 of 3,240" -- loaded of the filtered total, in the header (mono). Nothing until a total is known. */
export function countLabel(loaded, total) {
  if (total == null || total === "" || !Number.isFinite(Number(total))) return "";
  return Number(loaded || 0).toLocaleString() + " of " + Number(total).toLocaleString();
}

export function endLabel(total) {
  return "That's all " + Number(total || 0).toLocaleString() + ".";
}

/* The mounted window (U4a). A stacked list keeps every picture's data in memory but puts at most five
   pages of 100 in the DOM; a page scrolled out of the window leaves a spacer of its exact measured
   height, and scrolling back mounts it again from memory (each tile paints its tint, then its picture --
   its box is its aspect ratio, so nothing shifts). A window page is 100 pictures by its place in the
   list, whatever size the requests were cut at. */
export const WINDOW_PAGE = 100;
export const WINDOW_PAGES = 5;

export function windowPageCount(n) {
  return Math.ceil(Math.max(0, Number(n) || 0) / WINDOW_PAGE);
}

export function windowPageOf(index) {
  return Math.floor(Math.max(0, Number(index) || 0) / WINDOW_PAGE);
}

/* The pages to mount: centred on the page in view, held inside the list, at most `max`. `end` is
   inclusive; an empty list mounts nothing. */
export function mountWindow(center, count, max = WINDOW_PAGES) {
  const n = Math.max(0, Math.floor(Number(count)) || 0);
  if (!n) return { start: 0, end: -1 };
  const m = Math.max(1, Math.floor(Number(max)) || WINDOW_PAGES);
  const c = Math.min(n - 1, Math.max(0, Math.floor(Number(center)) || 0));
  const start = Math.max(0, Math.min(c - Math.floor(m / 2), n - m));
  return { start, end: Math.min(n - 1, start + m - 1) };
}

/* The window page the "N new since" rule closes: the page of the last new picture (none at zero). */
export function rulePage(newCount) {
  const k = Math.floor(Number(newCount) || 0);
  return k > 0 ? Math.floor((k - 1) / WINDOW_PAGE) : -1;
}

/* A page whose height changed between two frames -- mounted again over a spacer that was an estimate
   (after a turn of the phone, say), or an estimate refined: when the WHOLE page was above the top of the
   view (its bottom, before the change, at or above it) the view follows it by the difference, so nothing
   in view moves. A page the view is in, or one below it, is never corrected: a page that grows at its
   foot (the next pictures appended into it) moves nothing in view. */
export function remountShift(spacerHeight, realHeight, bottomBefore, viewTop) {
  if (!(Number(bottomBefore) <= Number(viewTop))) return 0;
  const d = Number(realHeight) - Number(spacerHeight);
  return Number.isFinite(d) ? d : 0;
}

/* The viewer's film strip in Continuous: the window page the picture is on ([start, end) of the list). */
export function stripRange(index, count) {
  const start = windowPageOf(index) * WINDOW_PAGE;
  return { start, end: Math.min(Math.max(0, Number(count) || 0), start + WINDOW_PAGE) };
}

/* Selection across pages (U5a + U5c). Ticks are kept by id. In select mode a second long-press selects
   every place between the last ticked tile and the pressed one, by absolute index in the filtered walk,
   loaded or not; when some are not loaded, a card says so for 4 s and their ids are read (ids only,
   at the route's largest page) before Actions opens, so every confirm states the full count. */
export const RANGE_CARD_MS = 4000;
export const RANGE_READ_SIZE = 200;      // the library route's own ceiling (MAX_PAGE_SIZE below)

export function rangeOf(a, b) {
  const x = Math.floor(Number(a)) || 0;
  const y = Math.floor(Number(b)) || 0;
  return { lo: Math.min(x, y), hi: Math.max(x, y) };
}

/* Which places of [lo, hi] the loaded list covers. `offset` is the place of the list's first picture in
   the walk (0 for a stacked list), `count` how many are loaded. Returns {n, k, from, to}: n places, k of
   them not loaded, and the loaded run from..to (inclusive; to < from when none of it is loaded). */
export function splitRange(lo, hi, offset, count) {
  const n = Math.max(0, hi - lo + 1);
  const from = Math.max(lo, Number(offset) || 0);
  const to = Math.min(hi, (Number(offset) || 0) + Math.max(0, Number(count) || 0) - 1);
  if (to < from) return { n, k: n, from: -1, to: -2 };
  return { n, k: n - (to - from + 1), from, to };
}

export function rangeCardText(n, k) {
  return "Selected " + Number(n).toLocaleString() + ", including " + Number(k).toLocaleString() + " not loaded yet.";
}

export function allLoadedLabel(n) {
  return "All loaded (" + Number(n || 0).toLocaleString() + ")";
}

/* The pages, at `size` a page, that hold the places lo..hi. */
export function readPagesFor(lo, hi, size) {
  const s = Math.max(1, Math.floor(Number(size)) || 1);
  const out = [];
  for (let p = Math.floor(Math.max(0, lo) / s) + 1; p <= Math.floor(Math.max(0, hi) / s) + 1; p += 1) out.push(p);
  return out;
}

/* The footer says one thing at a time: the spinner line while a page is in flight, the peach retry
   after a failed one (until Retry is tapped -- there is no automatic retry), the end line, or nothing. */
export function footerState({ busy, failed, done }) {
  if (busy) return "loading";
  if (failed) return "failed";
  if (done) return "end";
  return "idle";
}

/* ---------------------------------------------------------------------------------------------
   Data saver (Q7)
   --------------------------------------------------------------------------------------------- */

export const SAVER_MODES = Object.freeze(["off", "auto", "always"]);
export const DEFAULT_SAVER_MODE = "auto";
export const SAVER_THUMB = 256;                        // px, the server's ?s=256 tier

export const SAVER_LABELS = Object.freeze({ off: "Off", auto: "Auto on metered", always: "Always" });

/* The default is Auto. An unknown stored value is the default, never "Off" by accident. */
export function parseSaverMode(v) {
  return SAVER_MODES.indexOf(v) >= 0 ? v : DEFAULT_SAVER_MODE;
}

/* What this browser can tell about the connection, from the Network Information API
   (navigator.connection) where it exists.
     known     -- the browser answered the ONE question Auto asks: is this connection metered?
     metered   -- cellular, or the user's own "save data" request. Only meaningful when known.
   A browser with no API at all (every iPhone browser, and desktop Safari and Firefox) is not known,
   and neither is one that only reports a speed class (effectiveType says how fast, never what it
   costs). Chrome on Android reports `type`, which is what makes it known there. */
export function connectionInfo(conn) {
  if (!conn || typeof conn !== "object") {
    return { known: false, metered: false, saveData: false, type: "", api: false };
  }
  const type = typeof conn.type === "string" ? conn.type : "";
  const saveData = conn.saveData === true;
  const typed = type !== "" && type !== "unknown" && type !== "other";
  return {
    known: typed || saveData,
    metered: saveData || type === "cellular",
    saveData, type, api: true,
  };
}

/* Is Data saver acting right now? Off never, Always always, Auto only when the browser can say the
   connection is metered. */
export function saverActive(mode, info) {
  const m = parseSaverMode(mode);
  if (m === "always") return true;
  if (m === "off") return false;
  const i = info || connectionInfo(null);
  return !!(i.known && i.metered);
}

/* The Control row's sub line -- what it is doing and, for Auto, why. The Auto-where-it-can't-tell
   sentence is the honest one: iPhone Safari has no way to know, so Auto stays off there and the row
   says so and points at Always. */
export function saverSub(mode, info) {
  const m = parseSaverMode(mode);
  const i = info || connectionInfo(null);
  if (m === "off") return "Off";
  if (m === "always") return "On · always";
  if (!i.api || !i.known) {
    return "Auto · this browser can’t tell whether the connection is metered, so it stays off. Choose Always to save data.";
  }
  if (i.saveData && !(i.type === "cellular")) return "On · your browser is asking to save data";
  return i.metered ? "On · metered connection" : "Auto · on Wi-Fi, so it’s off right now";
}

/* The ONE place that turns a thumbnail URL into its saver size. Only the library's own /thumbs/
   route has the tier; a size the URL already carries is left alone; anything else is returned as it
   came. When the saver is off the URL is returned untouched, so the phone as built is byte-identical. */
export function thumbSrc(url, saver) {
  if (!saver || typeof url !== "string" || url.indexOf("/thumbs/") !== 0) return url;
  if (/[?&]s=/.test(url)) return url;
  return url + (url.indexOf("?") >= 0 ? "&" : "?") + "s=" + SAVER_THUMB;
}

/* Full size waits for a tap while the saver acts: the picture has not been loaded this session. */
export function needsFullTap(saver, loaded, mid) {
  return !!saver && !(loaded && loaded[mid]);
}

/* "2.4 MB" for the Tap to load pill, from a byte count; "" when the size is not known. */
export function humanBytes(n) {
  const b = Number(n);
  if (!Number.isFinite(b) || b <= 0) return "";
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return Math.round(b / 1024) + " KB";
  const mb = b / (1024 * 1024);
  return (mb >= 10 ? Math.round(mb) : Math.round(mb * 10) / 10) + " MB";
}

/* The phone's own background reads -- the page-1 refresh a finished generation triggers -- wait while
   the saver acts. A pull (Q6) is not one of them: it is an explicit request and never asks this. */
export function backgroundReadAllowed(saver) {
  return !saver;
}

/* ---------------------------------------------------------------------------------------------
   The placard (Q1)
   --------------------------------------------------------------------------------------------- */

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/* A catalog number the app really has: the tail of the media id (four characters), which is
   what a person can read off a card and tell apart. There is no separate accession register in
   the catalog, so nothing is invented -- a local import's id is local_<hex> and gives its last four
   hex characters, upper-cased. */
export function catalogNumber(mediaId) {
  const s = String(mediaId == null ? "" : mediaId).replace(/[^0-9A-Za-z]/g, "");
  if (!s) return "";
  return s.slice(-4).toUpperCase().padStart(4, "0");
}

function localDateParts(iso) {
  if (!iso) return null;
  const raw = String(iso);
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return { y: Number(raw.slice(0, 4)), m: Number(raw.slice(5, 7)), d: Number(raw.slice(8, 10)) };
  }
  const t = new Date(raw);
  if (isNaN(t)) return null;
  return { y: t.getFullYear(), m: t.getMonth() + 1, d: t.getDate() };
}

/* "ACC. 2026·0918·4401 · 18 SEP" -- the catalog number and the date, the desktop placard's two facts
   in the page's own stamp. The date is the viewer's LOCAL day (the same rule every stamp in the app
   keeps, gen/dates.js); with no date only the number is drawn, and with neither, nothing. */
export function accessionStamp(item) {
  if (!item) return "";
  const no = catalogNumber(item.media_id);
  const p = localDateParts(item.created_at);
  if (!p && !no) return "";
  const pad = (n) => String(n).padStart(2, "0");
  if (!p) return "ACC. " + no;
  const head = "ACC. " + p.y + "·" + pad(p.m) + pad(p.d) + (no ? "·" + no : "");
  return head + " · " + pad(p.d) + " " + MONTHS[p.m - 1];
}

/* The distinct task ids of a page of pictures, for the ONE batched /api/siblings read. A picture with
   no task (a local import) has no batch. */
export function taskIdsOf(items) {
  const out = [], seen = new Set();
  (items || []).forEach((it) => {
    const t = it && it.task_id ? String(it.task_id) : "";
    if (t && !seen.has(t)) { seen.add(t); out.push(t); }
  });
  return out;
}

/* The sibling strip for the picture on screen.
     siblings   what the batched read answered for this picture's task ([{media_id, is_video, thumb}],
                self included, absent for a single) -- never fetched per picture
     items      the loaded page, so a tap can swap in place: each sibling carries its index there, or
                -1 when it lives on another page (drawn dimmed, not tappable)
   Returns {single, line, tiles}. A single image (no siblings, or only itself) says so instead of
   drawing a strip. */
export function placardStrip(item, siblings, items) {
  const list = Array.isArray(siblings) ? siblings : [];
  if (!item || list.length < 2) return { single: true, line: "single image", tiles: [] };
  const at = new Map();
  (items || []).forEach((it, k) => at.set(it.media_id, k));
  const tiles = list.map((s) => ({
    media_id: s.media_id, thumb: s.thumb, is_video: !!s.is_video,
    index: at.has(s.media_id) ? at.get(s.media_id) : -1,
    current: s.media_id === item.media_id,
  }));
  return { single: false, line: "siblings · batch of " + list.length, tiles };
}

/* ---------------------------------------------------------------------------------------------
   New since (Q5)
   --------------------------------------------------------------------------------------------- */

/* The marker is the newest picture seen when the gallery was last left: its id, its own timestamp,
   and the clock time the visit ended (what "HH:MM" says). */
export function makeMarker(items, nowMs) {
  const top = items && items[0];
  if (!top || !top.media_id) return null;
  return { id: String(top.media_id), ts: tsOf(top.created_at), at: Number(nowMs) || 0 };
}

export function parseMarker(raw) {
  let m = raw;
  if (typeof raw === "string") { try { m = JSON.parse(raw); } catch { return null; } }
  if (!m || typeof m !== "object" || !m.id) return null;
  return { id: String(m.id), ts: Number.isFinite(Number(m.ts)) ? Number(m.ts) : 0, at: Number(m.at) || 0 };
}

export function tsOf(iso) {
  if (!iso) return 0;
  const t = Date.parse(String(iso));
  return Number.isNaN(t) ? 0 : t;
}

/* How many of the loaded (newest-first) pictures are newer than the marker. The marker picture itself
   is the boundary when it is on the page; when it is not (deleted, or pushed off by more than a page)
   the timestamp decides, and when every loaded picture is newer the count is capped (`capped`) so the
   label says "N+". Zero with no marker: a first visit has nothing to be new since. */
export function newSince(items, marker) {
  const list = items || [];
  if (!marker || !list.length) return { count: 0, capped: false };
  const at = list.findIndex((it) => String(it.media_id) === marker.id);
  if (at >= 0) return { count: at, capped: false };
  let n = 0;
  while (n < list.length && marker.ts > 0 && tsOf(list[n].created_at) > marker.ts) n += 1;
  if (marker.ts <= 0) return { count: 0, capped: false };
  return { count: n, capped: n === list.length };
}

/* "5 new since 21:40" (24-hour local HH:MM, as the page draws it). No rule at zero. */
export function newSinceLabel(count, capped, atMs) {
  if (!count) return "";
  const d = new Date(Number(atMs) || 0);
  const pad = (n) => String(n).padStart(2, "0");
  const t = atMs ? pad(d.getHours()) + ":" + pad(d.getMinutes()) : "";
  return count + (capped ? "+" : "") + " new" + (t ? " since " + t : "");
}

/* #64, "14 of 3,240": a picture's place in the WHOLE filtered walk (the detail route's `position` and
   `nav_total`, which come from the same list Prev and Next step through), formatted the way the pager
   prints its match count. "" when either number is missing, so the record draws nothing rather than a
   guess; a picture the filter does not contain has no position. */
export function positionLabel(position, total) {
  const p = Number(position);
  const t = Number(total);
  if (!(p >= 1) || !(t >= 1)) return "";
  return p.toLocaleString() + " of " + t.toLocaleString();
}

/* The library route clamps page_size to 1..200 (moonglade_gallery.py, api_next_library); the offset the
   viewer adds to its place in the page has to use the size the server really cut the page with. */
const MAX_PAGE_SIZE = 200;
const DEFAULT_PAGE_SIZE = 100;

/* How many pictures come before the loaded page in the walk. The phone grid is ungrouped, so this is
   exact: (page - 1) full pages. */
export function pageOffset(page, perPage) {
  const p = Math.max(1, Math.floor(Number(page)) || 1);
  const size = Math.min(MAX_PAGE_SIZE, Math.max(1, Math.floor(Number(perPage)) || DEFAULT_PAGE_SIZE));
  return (p - 1) * size;
}

/* The viewer's big number and its "OF N" (#64), both formatted like the pager. `index` is the place in
   the loaded page, `offset` the pictures before that page, `total` the walk's length, `loaded` the
   page's length. With no total yet it falls back to the page it holds (what it always showed), and a
   total the page has outgrown (pictures deleted since) never reads "k of fewer than k". */
export function lightboxCount(index, offset, total, loaded) {
  const fmt = (n) => Number(n).toLocaleString();
  const t = Number(total);
  if (!(t >= 1)) return { at: fmt(index + 1), of: fmt(loaded) };
  const at = Math.max(0, Number(offset) || 0) + index + 1;
  return { at: fmt(at), of: fmt(Math.max(t, at)) };
}

/* The rule only means something for the library's own front page: page 1, newest first, nothing
   filtered, not a lookalike set. Anywhere else there is no rule and the marker is left alone.
   Continuous (Session U, U3a): a stacked list always runs from the top of the walk, so it is the front
   page however far down it has loaded; the rule stays at its place in it. */
export function isFrontPage({ page, advCount, applied, media, shelf, similar, loaded, continuous }) {
  if (similar || !loaded) return false;
  if (!continuous && (page || 1) !== 1) return false;
  if (advCount) return false;                 // any Advanced Search field, the sort included
  return !(String(applied || "").trim() || media || shelf);
}

/* A pull over a stacked list (Session U, U3a): what is new goes ABOVE everything loaded, every loaded
   page is kept, and the rule -- which follows the marker picture -- is pushed down only by what was
   prepended above it. The shell reads the top of the walk a page at a time; the new run is everything
   before the first picture already loaded (`met`: the run reached the loaded list, so nothing between is
   missing). A run longer than PREPEND_MAX_PAGES pages is too much to splice in, and the list starts
   over from the top instead (useLibrary.prependNewest). */
export const PREPEND_MAX_PAGES = 5;

export function newestAbove(page, loadedIds) {
  const fresh = [];
  const list = page || [];
  for (let i = 0; i < list.length; i += 1) {
    if (loadedIds.has(list[i].media_id)) return { fresh, met: true };
    fresh.push(list[i]);
  }
  return { fresh, met: false };
}

/* The new ones first, then the list as it was; a picture already loaded stays once, where it was.
   Nothing new answers the SAME list. */
export function prependUnique(fresh, old) {
  const list = old || [];
  const have = new Set(list.map((it) => it.media_id));
  const add = (fresh || []).filter((it) => it && !have.has(it.media_id) && (have.add(it.media_id), true));
  return add.length ? add.concat(list) : list;
}

/* "↑ Newest" shows after one screen of scrolling. */
export function showNewest(scrollTop, viewportHeight) {
  const vh = Number(viewportHeight);
  return Number(scrollTop) > (Number.isFinite(vh) && vh > 0 ? vh : 560);
}

/* ...and steps aside while the pager row is on screen (owner's walk, 2026-10-03: it sat on top of
   "‹ Prev · Page 1 of 380 · 37,917 matches · Next ›" and hid its middle). Where the pager shows, the
   page is ending anyway. `pager` and `view` are the pager row's and the scroller's boxes ({top,
   bottom}); a missing one is "not on screen". */
export function pagerInView(pager, view) {
  if (!pager || !view) return false;
  return Number(pager.top) < Number(view.bottom) && Number(pager.bottom) > Number(view.top);
}

export function newestLabel(count) {
  return "↑ Newest" + (count ? " · " + count + " new" : "");
}

/* ---------------------------------------------------------------------------------------------
   Pull to refresh (Q6)
   --------------------------------------------------------------------------------------------- */

export const PULL_THRESHOLD = 72;     // px of pull that arms the release
export const PULL_MAX = 90;           // the content never follows the finger further than this
export const PULL_HOLD = 44;          // where the content rests while it syncs
export const PULL_RESISTANCE = 0.6;   // the finger moves 1 px, the page 0.6

/* Finger travel -> how far the page follows. Zero or negative travel is no pull. */
export function pullDistance(dy) {
  const d = Number(dy);
  if (!Number.isFinite(d) || d <= 0) return 0;
  return Math.min(PULL_MAX, d * PULL_RESISTANCE);
}

/* The moon's phase: a TRUE fraction of the distance to the release line (the moon gauge fills only
   on one, DECISIONS "The moon gauge fills only on a true fraction"). */
export function pullFraction(px) {
  const p = Number(px);
  if (!Number.isFinite(p) || p <= 0) return 0;
  return Math.min(1, p / PULL_THRESHOLD);
}

export function pullArmed(px) {
  return Number(px) >= PULL_THRESHOLD;
}

/* A pull can only begin at the very top of the scroller, and never while one is already syncing. */
export function pullMayStart(scrollTop, syncing) {
  return !syncing && Number(scrollTop) <= 0;
}

export function pullLabel({ syncing, px }) {
  if (syncing) return "syncing with PixAI…";
  return pullArmed(px) ? "release to sync" : "pull to refresh";
}

/* How the sync ended, in a sentence for the toast; "" when it needs none. */
export function syncOutcomeText(outcome) {
  if (!outcome) return "";
  if (outcome.state === "done") return "";
  if (outcome.state === "busy") return "A sync is already running — the library will refresh when it finishes.";
  if (outcome.state === "timeout") return "Still syncing in the background — pull again in a minute to bring in what arrives.";
  if (outcome.state === "failed") return "The sync didn’t finish" + (outcome.error ? ": " + outcome.error : ".");
  return outcome.error ? String(outcome.error) : "The sync didn’t start.";
}

/* ---------------------------------------------------------------------------------------------
   Landscape (Q4)
   --------------------------------------------------------------------------------------------- */

export const PHONE_MAX = 520;         // the phone line: a screen this narrow (or this short) is a phone
/* The one landscape-phone geometry. gallery/src/styles/phone-landscape.css writes the same query as
   its @media condition (a test holds the two together), and hooks/usePhoneLandscape.js watches it. */
export const LANDSCAPE_QUERY = "(orientation: landscape) and (max-height: 520px)";
export const LANDSCAPE_COLS = 4;      // Q4: the gallery's columns in landscape...
export const LANDSCAPE_COLS_NARROW = 3;   // ...and under this many CSS px wide
export const LANDSCAPE_NARROW_PX = 700;

/* Is this screen a phone -- the question main.jsx asks to choose the phone shell (the ONE rule; the
   Loom defers to it too). It was portrait-only until Q4: a phone turned sideways is 844 px wide, past
   the 520 line, so it fell onto the desktop build and lost every phone screen. Now:
     width <= 520                       any window that narrow (a phone upright, a desktop window dragged in)
     coarse, upright, screen <= 520     the fallback for iOS Chrome / Firefox, whose layout viewport can
                                        report desktop-wide on a real phone
     sideways, SHORT SIDE <= 520        a phone turned to landscape. The short side, because iOS Safari
                                        keeps screen.width at the upright width whichever way the phone
                                        is held while Android swaps the two -- the minimum is right for
                                        both. An iPad mini's short side is 744, so a tablet never trips
                                        it, and a laptop's is far beyond it.
   `landscapePhones: false` is the Loom's ask: its wide four-panel board is at home in landscape, so a
   phone turned sideways opens the board, not the phone view. */
export function isPhoneViewport({ width, coarse, portrait, screenW, screenH, landscapePhones = true }) {
  const w = Number(width);
  if (Number.isFinite(w) && w <= PHONE_MAX) return true;
  const sw = Number.isFinite(Number(screenW)) && Number(screenW) > 0 ? Number(screenW) : Infinity;
  const sh = Number.isFinite(Number(screenH)) && Number(screenH) > 0 ? Number(screenH) : Infinity;
  if (portrait) return !!coarse && sw <= PHONE_MAX;
  return landscapePhones && Math.min(sw, sh) <= PHONE_MAX;
}

/* How many columns the phone gallery draws: two upright; sideways four, or three under 700 px wide. */
/* A TURN IS READ AGAIN ONCE IT HAS SETTLED (owner's walk, 2026-10-03). A phone's browser can deliver a
   turn's resize and orientation events while the orientation query still answers for the old way up,
   and fire nothing once it settles -- so a read made only on the events kept the sideways columns on
   an upright phone (a column hung off the edge). hooks/usePhoneLandscape.js reads again on the next
   frame and at each of these delays after any such event; a read that finds nothing changed changes
   nothing. */
export const TURN_SETTLE_MS = [120, 400, 1000];

export function phoneColumns(width, landscape) {
  if (!landscape) return 2;
  const w = Number(width);
  return Number.isFinite(w) && w < LANDSCAPE_NARROW_PX ? LANDSCAPE_COLS_NARROW : LANDSCAPE_COLS;
}

/* Rotation keeps your place. Before the turn the gallery notes WHICH picture sits at the top of the
   view and how far below the top edge it is; after the columns re-flow it scrolls that same picture
   back to the same place, rather than trusting a pixel offset into a list that is now a different
   height. `tiles` is [{id, top, bottom}] (any order); `viewTop` is the top of the visible area (below
   the sticky search bar). Returns {id, offset} or null when nothing is in view. */
export function pickAnchor(tiles, viewTop) {
  let best = null;
  for (const t of tiles || []) {
    if (!t || !(Number(t.bottom) > Number(viewTop) + 1)) continue;
    if (!best || Number(t.top) < Number(best.top)) best = t;
  }
  return best ? { id: best.id, offset: Number(best.top) - Number(viewTop) } : null;
}

/* The scrollTop that puts the anchored picture back where it was, never negative. */
export function anchorScrollTop(scrollTop, tileTop, viewTop, offset) {
  const next = Number(scrollTop) + (Number(tileTop) - Number(viewTop) - Number(offset || 0));
  return Number.isFinite(next) ? Math.max(0, Math.round(next)) : 0;
}
