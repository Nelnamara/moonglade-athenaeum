/* inbox/inboxStore.js -- the inbox's and the gift box's state (Sessions R + Y, lane R): the
   badge counts, the loaded inbox, the gifts and the events, and the one write a row's open makes.
   A MODULE SINGLETON like notify/jobsStore.js: the desktop's two header doors (✉ Inbox and
   🎁 Gift box, owner's walk 2026-10-04) and the phone's two Menu rows read the SAME state, and
   the count must not be re-read once per mount.

   WHAT READS, AND WHEN (R4b, drift 126):
     - the count (/api/inbox/count): once on app open, on window focus (no more than once in
       30 s), and when the live mirror reconnects. The read count wins over anything pushed.
     - a push: the live mirror counts PixAI's `newNotification`, and /api/jobs -- the poll every
       open tab already runs -- carries that count here (jobsStore hands it over). A rise bumps
       the badge at once; the new rows are fetched once (/api/inbox/pushed) so a COMMENT can
       toast [Later] [Open thread] and an open panel can show them. There is no timer of our own.
     - the list (/api/inbox): one read when the panel opens (last=20), older pages at the
       scroll's end. Opening the panel, scrolling, switching tabs and a push write NOTHING.
   WHAT WRITES (R3b): opening a row or a work card marks the ids it gathers read on PixAI -- one
   call per open, through the server's READ_ONLY-first, one-attempt, read-back route. Under
   READ_ONLY the row still opens and nothing is marked. An unclear answer leaves it unread and
   puts the peach line under it. A failure never blocks the navigation. */

import { apiGet, apiPost } from "../api.js";
import { show as toastShow } from "../notify/toastStore.js";
import { onInboxLive } from "../notify/jobsStore.js";
import { toasts, commentToast } from "./inboxCore.js";

const FOCUS_GAP_MS = 30000;

let state = {
  count: null,          // the phone Menu's badge: PixAI's unread (TASK excluded) + pending gifts; null = unknown
  unread: null,         // the ✉ inbox's badge: PixAI's unread notifications (TASK excluded)
  gifts: null,          // the 🎁 gift box's badge: the pending gifts PixAI counts
  items: [], cursor: null, hasMore: false, loaded: false, loading: false, error: "",
  csrf: "", readOnly: false,
  notice: null,         // {key, text}: the peach line under a row whose mark-read was unclear
  allNotice: "",        // the line under ⋯ Mark all read
  giftData: null,       // {gifts, bonuses, has_thread, my_name} | null
  giftError: "", giftsLoading: false, claim: null,   // claim: {id, state, message}
  claimLocked: {},      // gift id -> true after an unclear claim, until the gifts are read again
  events: null,
};
const subs = new Set();
let started = false;
let lastFocusRead = 0;
let live = null;      // {seq, connects} last seen on /api/jobs
let pendingFocus = null;

function set(patch) {
  state = { ...state, ...patch };
  subs.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  subs.add(fn);
  fn(state);
  return () => subs.delete(fn);
}

export function getState() { return state; }

// ---- the count ---------------------------------------------------------------------------

export function readCount() {
  return apiGet("/api/inbox/count").then((d) => {
    if (d && d.csrf) set({ csrf: d.csrf || state.csrf });
    if (d && !d.error && d.total != null) set({ count: d.total, unread: d.unread, gifts: d.gifts });
  });
}

/* The CSRF token every write carries. The panel's read hands it out, and so does the count
   read at app open; a write that comes before either (a comment toast's Open thread, before
   the panel was ever opened) fetches it first rather than sending an empty one. */
export function ensureCsrf() {
  if (state.csrf) return Promise.resolve(state.csrf);
  return apiGet("/api/inbox/count").then((d) => {
    if (d && d.csrf) set({ csrf: d.csrf });
    if (d && !d.error && d.total != null) set({ count: d.total, unread: d.unread, gifts: d.gifts });
    return state.csrf;
  });
}

/* Once per app (both shells call it): the open read, and the focus backstop. */
export function start() {
  if (started) return;
  started = true;
  lastFocusRead = Date.now();
  readCount();
  onInboxLive(noteLive);
  if (typeof window !== "undefined") {
    window.addEventListener("focus", () => {
      if (Date.now() - lastFocusRead < FOCUS_GAP_MS) return;
      lastFocusRead = Date.now();
      readCount();
    });
  }
}

/* jobsStore's poll answered: {seq, connects} from the live mirror, or null. */
export function noteLive(inbox) {
  if (!inbox || typeof inbox.seq !== "number") return;
  const prev = live;
  live = { seq: inbox.seq, connects: inbox.connects || 0 };
  if (!prev) return;                                   // the first answer is the baseline
  if (live.connects > prev.connects) readCount();       // a reconnect: the read count wins
  if (live.seq > prev.seq) {
    // a push is a notification: the total and the unread rise, the gifts do not
    if (state.count != null) {
      set({ count: state.count + (live.seq - prev.seq),
        unread: state.unread != null ? state.unread + (live.seq - prev.seq) : state.unread });
    }
    pullPushed(prev.seq);
  }
}

function pullPushed(after) {
  apiGet("/api/inbox/pushed", { after }).then((d) => {
    if (!d || d.error) return;
    const fresh = (d.items || []).filter((it) => !state.items.some((x) => x.id === it.id));
    if (state.loaded && fresh.length) set({ items: fresh.concat(state.items) });
    fresh.filter(toasts).forEach((it) => {
      const words = commentToast(it);
      toastShow({
        kind: "", icon: "❝", title: words.title, msg: words.msg, sticky: true,
        actions: [
          { label: "Later", run: () => {} },
          { label: "Open thread", run: () => openItem({ kind: "work", ids: [it.id], artwork: it.artwork,
            focusId: it.id, unread: it.unread }) },
        ],
      });
    });
  });
}

// ---- the list -----------------------------------------------------------------------------

export function loadFirst() {
  if (state.loading) return Promise.resolve();
  set({ loading: true, error: "", notice: null, allNotice: "" });
  return apiGet("/api/inbox").then((d) => {
    set({ loading: false, loaded: !d.error, items: d.items || [], cursor: d.cursor || null,
      hasMore: !!d.has_more, error: d.error || "", csrf: d.csrf || state.csrf,
      readOnly: !!d.read_only });
  });
}

export function loadMore() {
  if (state.loading || !state.hasMore || !state.cursor) return Promise.resolve();
  set({ loading: true });
  return apiGet("/api/inbox", { before: state.cursor }).then((d) => {
    if (d.error) { set({ loading: false, error: d.error }); return; }
    const have = new Set(state.items.map((x) => x.id));
    set({ loading: false, items: state.items.concat((d.items || []).filter((x) => !have.has(x.id))),
      cursor: d.cursor || null, hasMore: !!d.has_more });
  });
}

export function loadEvents() {
  return apiGet("/api/inbox/events").then((d) => set({ events: (d && d.events) || [] }));
}

export function loadGifts() {
  set({ giftsLoading: true });
  return apiGet("/api/inbox/gifts").then((d) => {
    set({ giftsLoading: false, giftError: d.error || "", csrf: d.csrf || state.csrf,
      claimLocked: d.error ? state.claimLocked : {},
      readOnly: d.read_only != null ? !!d.read_only : state.readOnly,
      giftData: d.error ? state.giftData : { gifts: d.gifts || [], bonuses: d.bonuses || [],
        has_thread: !!d.has_thread, my_name: d.my_name || "" } });
  });
}

// ---- opening a row: navigate, and mark it read (one write) --------------------------------

/* Each shell's door to its contest surface (the desktop's Contests overlay, the phone's
   Contests screen) -- a contest row opens it. */
let contestOpener = null;
const marking = new Set();      // rows whose mark-read is in flight
export function registerContestOpener(fn) {
  contestOpener = typeof fn === "function" ? fn : null;
  return () => { if (contestOpener === fn) contestOpener = null; };
}

/* A thread opener for Details: the panel asks for a picture, Details asks which comment. */
export function takeFocus(artworkId) {
  if (!pendingFocus || pendingFocus.artworkId !== String(artworkId || "")) return null;
  const f = pendingFocus;
  pendingFocus = null;
  return f;
}

function navigate(row) {
  const art = row.artwork || (row.item && row.item.artwork);
  if (row.kind === "work" || (art && art.id)) {
    if (art && art.media_id) {
      pendingFocus = { artworkId: String(art.id), commentId: row.focusId || "" };
      document.dispatchEvent(new CustomEvent("mg-open-details", { bubbles: true, composed: true,
        detail: { mid: art.media_id } }));
    } else if (art && art.id) {
      window.open("https://pixai.art/en/artwork/" + encodeURIComponent(art.id), "_blank", "noopener");
    }
    return;
  }
  const it = row.item || {};
  if (row.kind === "follow") {
    const who = (row.users || it.users || [])[0];
    if (who && who.id) window.open("https://pixai.art/en/user/" + encodeURIComponent(who.id), "_blank", "noopener");
    return;
  }
  if (row.kind === "contest") {
    if (contestOpener) contestOpener((it.contest && it.contest.slug) || "");
    return;
  }
  if (it.link && /^https:\/\//.test(it.link)) window.open(it.link, "_blank", "noopener");
}

export function openItem(row) {
  navigate(row);
  if (!row.unread || state.readOnly) return Promise.resolve(null);
  // Only what is still unread: a work card gathers read rows too. A row the panel never
  // loaded (a pushed comment's toast) sends its own ids.
  const loaded = new Map(state.items.map((x) => [x.id, x]));
  const ids = (row.ids || []).filter((id) => !loaded.has(id) || loaded.get(id).unread);
  if (!ids.length) return Promise.resolve(null);
  // One mark-read per row at a time: a double click is one write, not two.
  const key = row.key || ids.join(",");
  if (marking.has(key)) return Promise.resolve(null);
  marking.add(key);
  return ensureCsrf().then(() => apiPost("/api/inbox/read", { csrf: state.csrf, ids })).then((d) => {
    if (d && d.state === "done") {
      const gone = new Set(ids);
      const was = state.items.filter((x) => gone.has(x.id) && x.unread).length;
      set({ items: state.items.map((x) => (gone.has(x.id) ? { ...x, unread: false } : x)),
        count: state.count != null ? Math.max(0, state.count - was) : state.count,
        unread: state.unread != null ? Math.max(0, state.unread - was) : state.unread,
        notice: state.notice && state.notice.key === row.key ? null : state.notice });
    } else if (d && d.state === "read_only") {
      set({ readOnly: true });
    } else {
      set({ notice: { key: row.key, text: (d && d.message) ||
        "Couldn't confirm it was marked read. It stays unread here; nothing was sent twice." } });
    }
    return d;
  }).finally(() => marking.delete(key));
}

export function markAllRead(tab) {
  if (state.readOnly) {
    set({ allNotice: "Read-only mode is on, so nothing is marked read on PixAI." });
    return Promise.resolve(null);
  }
  return ensureCsrf().then(() => apiPost("/api/inbox/read-all", { csrf: state.csrf, tab })).then((d) => {
    if (d && d.state === "done") {
      set({ allNotice: "", items: state.items.map((x) => ({ ...x, unread: false })) });
      readCount();
    } else {
      set({ allNotice: (d && (d.message || d.error)) || "No clear answer. Check on PixAI." });
    }
    return d;
  });
}

// ---- a gift's claim (one write) -----------------------------------------------------------

/* One claim per gift. A claim whose answer was not clear (no done, no refusal) may still have
   gone through, so that gift's Claim stays off -- `claimLocked` -- until the gift list is read
   again (the next panel or sheet open), which is what shows whether it landed. */
export function claimGift(id) {
  if (state.claim && state.claim.state === "sending") return Promise.resolve(null);
  if (state.claimLocked[id]) return Promise.resolve(null);
  set({ claim: { id, state: "sending", message: "" } });
  return ensureCsrf().then(() => apiPost("/api/inbox/gifts/claim", { csrf: state.csrf, id })).then((d) => {
    const answer = (d && d.state) || "unclear";
    set({ claim: { id, state: answer,
      message: (d && (d.message || d.error)) || "No clear answer from PixAI. Check on PixAI before trying again." } });
    if (answer === "done" || answer === "refused") { loadGifts(); readCount(); }
    else if (answer !== "read_only") set({ claimLocked: { ...state.claimLocked, [id]: true } });
    return d;
  });
}

export function clearClaim() { set({ claim: null }); }
