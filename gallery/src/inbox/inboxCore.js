/* inbox/inboxCore.js -- the PURE half of Sessions R + Y (lane R, 2026-10-03): the doors'
   badges, how the inbox reads (one card per work, follows folded per day, TASK never told twice),
   the comment thread's chains, the reply's counter, the free cards about to expire, and the
   gift rows' words. No DOM, no fetch, no clock of its own (every function that needs "now" takes
   it), so `node --test` drives it directly (loom/test/inbox-core.test.js).

   The design: `Inbox and Event Handoff.dc.html` (picks R1a R2c R3b R4b R5b R6c R9c Y1c Y2a Y3a
   RYPc), notes/inbox-event/NOTES.md, drift 123-133. The server half is moonglade_inbox.py. */

/* The inbox's kind tabs. No Gifts tab: since the owner's walk (2026-10-04) gifts live only in
   the gift box, the inbox's twin door beside it. */
export const TABS = [
  ["all", "All"], ["comments", "Comments"], ["likes", "Likes"],
  ["follows", "Follows"], ["pixai", "PixAI"],
];

const TAB_CATS = {
  all: ["like", "comment", "follow", "contest", "news"],
  comments: ["comment"], likes: ["like"], follows: ["follow"],
  pixai: ["contest", "news"],
};

// The glyph each kind wears: ♥ like · ❝ comment · + follow · ✦ contest · ◆ PixAI news.
export const GLYPH = { like: "♥", comment: "❝", follow: "+", contest: "✦", news: "◆" };

export const REPLY_MAX = 4095;
export const EXPIRY_WINDOW_H = 72;

/* A door's badge -- the inbox's unread, the gift box's pending gifts, the phone Menu's sum of the
   two: nothing at 0 or unknown, "99+" past 99. */
export function badgeText(n) {
  const v = Number(n);
  if (n == null || !isFinite(v) || v <= 0) return "";
  return v > 99 ? "99+" : String(Math.floor(v));
}

export function inTab(item, tab) {
  return (TAB_CATS[tab] || TAB_CATS.all).indexOf(item && item.cat) >= 0;
}

/* "3h", "1d": the mono meta on a row. Never seconds; under a minute is "now". */
export function timeAgo(iso, now) {
  const t = Date.parse(iso || "");
  if (!isFinite(t)) return "";
  const s = Math.max(0, (Number(now) - t) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  if (s < 86400 * 30) return Math.floor(s / 86400) + "d";
  return Math.floor(s / (86400 * 30)) + "mo";
}

export function firstLine(text) {
  return String(text || "").split(/\r?\n/).map((l) => l.trim()).find(Boolean) || "";
}

function nameList(users, max) {
  const names = [];
  const seen = new Set();
  (users || []).forEach((u) => {
    const k = (u && (u.id || u.name)) || "";
    if (k && !seen.has(k)) { seen.add(k); names.push((u && u.name) || "someone"); }
  });
  return names;
}

function people(names, shown) {
  if (!names.length) return "";
  if (names.length <= shown) {
    return names.length === 1 ? names[0] : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  }
  return names.slice(0, shown).join(", ") + " and " + (names.length - shown) + " more";
}

function localDayKey(iso) {
  const d = new Date(iso || "");
  if (!isFinite(d.getTime())) return "";
  return d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
}

/* The words on an "everything else" row that is not a fold. */
export function rowText(item) {
  const it = item || {};
  const who = nameList(it.users);
  if (it.cat === "contest") {
    const title = (it.contest && it.contest.title) || it.ref_title || "a contest";
    if (it.type === "CONTEST_RESULT_PUBLISHED") return "Contest results are out: “" + title + "”";
    if (it.type === "CONTEST_WON") return "You placed in “" + title + "”";
    return "Contest: “" + title + "”";
  }
  if (it.cat === "news") {
    const body = firstLine(it.content) || it.ref_title || "";
    if (body) return "PixAI: " + body;
    return "PixAI: " + String(it.type || "notice").toLowerCase().replace(/_/g, " ");
  }
  if (it.cat === "like") return (people(who, 2) || "Someone") + " liked " + workTitle(it);
  if (it.cat === "comment") return (people(who, 1) || "Someone") + ": " + firstLine(it.content);
  return firstLine(it.content) || it.type || "";
}

function workTitle(it) {
  return (it.artwork && it.artwork.title) || "your work";
}

/* THE INBOX, READ (R2c): one card per work, then everything else.

   A work card gathers every like and comment on one artwork across the loaded rows: "♥ +N"
   (likes, by the people PixAI names) and "❝ N new" (unread comments; "❝ N" when they are all
   read), omitting a zero; its time is the newest row's, and it quotes the newest UNREAD
   comment. Follows fold per local day. Contest and news are one row each. TASK never reaches
   here (the server keeps it out). Cards and rows are both newest first. Each carries the ids
   it gathers: opening it marks exactly those read, in one call (R3b). */
export function groupInbox(items, tab) {
  const works = new Map();
  const rest = [];
  const follows = new Map();
  (items || []).forEach((it) => {
    if (!it || !inTab(it, tab)) return;
    const art = it.artwork;
    if (art && art.id && (it.cat === "like" || it.cat === "comment")) {
      let c = works.get(art.id);
      if (!c) {
        c = { key: "w" + art.id, kind: "work", artwork: art, ids: [], unread: false, likes: 0,
          comments: 0, newComments: 0, at: "", quote: null, quoteAt: "" };
        works.set(art.id, c);
      }
      c.ids.push(it.id);
      if (it.unread) c.unread = true;
      if (it.created_at > c.at) c.at = it.created_at;
      if (!c.artwork.media_id && art.media_id) c.artwork = art;
      if (it.cat === "like") c.likes += Math.max(1, (it.users || []).length);
      else {
        c.comments += 1;
        if (it.unread) {
          c.newComments += 1;
          if (it.created_at >= c.quoteAt) {
            c.quoteAt = it.created_at;
            c.quote = { name: nameList(it.users)[0] || "someone", text: firstLine(it.content), id: it.id };
          }
        }
      }
      return;
    }
    if (it.cat === "follow") {
      const day = localDayKey(it.created_at);
      let f = follows.get(day);
      if (!f) {
        f = { key: "f" + day, kind: "follow", ids: [], unread: false, at: "", users: [], item: it };
        follows.set(day, f);
        rest.push(f);
      }
      f.ids.push(it.id);
      f.users = f.users.concat(it.users || []);
      if (it.unread) f.unread = true;
      if (it.created_at > f.at) f.at = it.created_at;
      return;
    }
    rest.push({ key: "r" + it.id, kind: it.cat, ids: [it.id], unread: !!it.unread,
      at: it.created_at || "", item: it });
  });
  rest.forEach((r) => {
    if (r.kind === "follow") {
      const names = nameList(r.users);
      r.text = names.length + " new follower" + (names.length === 1 ? "" : "s") +
        (names.length ? " · " + people(names, 2) : "");
    } else {
      r.text = rowText(r.item);
    }
  });
  const byAt = (a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0);
  return { works: Array.from(works.values()).sort(byAt), rest: rest.sort(byAt) };
}

/* "♥ +12 · ❝ 2 new" -- zeroes omitted. */
export function workDelta(card) {
  const parts = [];
  if (card && card.likes) parts.push("♥ +" + card.likes);
  if (card && card.newComments) parts.push("❝ " + card.newComments + " new");
  else if (card && card.comments) parts.push("❝ " + card.comments);
  return parts.join(" · ");
}

/* Whether a pushed row raises a toast: comments only (R4b). */
export function toasts(item) {
  return !!item && (item.type === "COMMENT" || item.type === "COMMENT_REPLY");
}

/* The comment toast's words: "<name> commented on <work>" and the first line. */
export function commentToast(item) {
  const name = nameList(item && item.users)[0] || "Someone";
  return { title: name + (item && item.type === "COMMENT_REPLY" ? " replied on " : " commented on ") +
      workTitle(item || {}),
    msg: "“" + firstLine(item && item.content) + "”" };
}

// ---- the thread (R5b) -------------------------------------------------------------------

/* The thread as drawn: top-level comments (newest first, as PixAI sends them), each with its
   replies (oldest first, one indent deep -- later replies are flat under it). A reply whose
   parent is not on the loaded pages stands as its own top-level item. A chain holding your
   comment, or the comment an inbox quote pointed at, opens by itself. Flagged comments are
   left out and counted. */
export function threadOf(comments, focusId) {
  const shown = (comments || []).filter((c) => c && !c.flagged);
  const hidden = (comments || []).filter((c) => c && c.flagged).length;
  const byId = new Map(shown.map((c) => [c.id, c]));
  const rootOf = (c) => {
    let cur = c;
    const seen = new Set();
    while (cur.reply_to && byId.has(cur.reply_to) && !seen.has(cur.id)) {
      seen.add(cur.id);
      cur = byId.get(cur.reply_to);
    }
    return cur;
  };
  const chains = new Map();
  const order = [];
  shown.forEach((c) => {
    const root = rootOf(c);
    let ch = chains.get(root.id);
    if (!ch) { ch = { root, replies: [] }; chains.set(root.id, ch); order.push(root.id); }
    if (root.id !== c.id) ch.replies.push(c);
  });
  const out = order.map((id) => {
    const ch = chains.get(id);
    ch.replies.sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
    const all = [ch.root].concat(ch.replies);
    ch.open = ch.replies.length > 0 &&
      (all.some((c) => c.you) || (!!focusId && all.some((c) => c.id === focusId)));
    return ch;
  });
  // top-level newest first whatever order the pages arrived in
  out.sort((a, b) => (a.root.created_at < b.root.created_at ? 1 : a.root.created_at > b.root.created_at ? -1 : 0));
  return { chains: out, hidden };
}

export function hiddenLine(n) {
  return n ? n + " comment" + (n === 1 ? "" : "s") + " hidden by PixAI" : "";
}

/* The meta line under a comment: "2h · reactions 3 · 1 reply ▾". */
export function commentMeta(c, now, replies, open) {
  const parts = [timeAgo(c && c.created_at, now)];
  if (c && c.reactions) parts.push("reactions " + c.reactions);
  if (replies) parts.push(replies + " repl" + (replies === 1 ? "y" : "ies") + (open ? " ▾" : " ▸"));
  return parts.filter(Boolean).join(" · ");
}

// ---- the reply (R6c) --------------------------------------------------------------------

/* The reply's counter. PixAI counts as JavaScript does (UTF-16 units), so String.length is
   exactly its limit's unit. */
export function replyCheck(text) {
  const n = String(text || "").trim().length;
  const over = n - REPLY_MAX;
  return { n, over: Math.max(0, over), empty: n === 0, ok: n > 0 && over <= 0,
    label: n.toLocaleString("en-US") + " / " + REPLY_MAX.toLocaleString("en-US"),
    tooLong: over > 0 ? "Too long by " + over.toLocaleString("en-US") : "" };
}

/* The question before a reply posts: who you post as, whose comment, which work. */
export function replyQuestion(myName, authorName, work) {
  return "Post publicly as " + (myName || "your PixAI name") + ", replying to " +
    (authorName || "this comment") + " on " + (work || "this work") + "?";
}

export function deleteQuestion(work) {
  return "Delete your reply on " + (work || "this work") + "? This can't be undone.";
}

// ---- expiring free cards (Y1c + Y2a) -------------------------------------------------------

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* "Oct 6", in the viewer's own calendar. */
export function monDay(iso) {
  const d = new Date(iso || "");
  return isFinite(d.getTime()) ? MONTHS[d.getMonth()] + " " + d.getDate() : "";
}

/* How far off an expiry is, in calendar days and never in hours: "today", "tomorrow",
   "in 3 days". (The design's "tomorrow at under 48 h" read as calendar days: a card that
   lapses tonight is "today", never "tomorrow".) */
export function expiryWhen(iso, now) {
  const d = new Date(iso || "");
  const n = new Date(Number(now));
  if (!isFinite(d.getTime()) || !isFinite(n.getTime())) return "";
  const day = (x) => Date.UTC(x.getFullYear(), x.getMonth(), x.getDate());
  const diff = Math.round((day(d) - day(n)) / 86400000);
  if (diff <= 0) return "today";
  if (diff === 1) return "tomorrow";
  return "in " + diff + " days";
}

/* The cards that lapse within the window (72 h): one line per kind and date, soonest first --
   "5 Tsubaki.3 expire Oct 6 · in 3 days" -- plus how many held cards are NOT expiring soon.
   Empty when nothing does: then there is no underline and the tooltip is as shipped. */
export function expiringLines(cardsBy, now, windowH) {
  const limit = Number(now) + (windowH || EXPIRY_WINDOW_H) * 3600 * 1000;
  const lines = [];
  let held = 0;
  let soon = 0;
  (cardsBy || []).forEach((c) => {
    held += Math.max(0, Number(c && c.count) || 0);
    ((c && c.expiry_counts) || []).forEach((e) => {
      const at = Date.parse(e && e.expires_at);
      const n = Number(e && e.count) || 0;
      if (!isFinite(at) || n <= 0 || at <= Number(now) || at > limit) return;
      soon += n;
      lines.push({ count: n, kind: (c && c.name) || "free", at: e.expires_at,
        date: monDay(e.expires_at), when: expiryWhen(e.expires_at, now) });
    });
  });
  lines.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return { lines, other: Math.max(0, held - soon), soonest: lines[0] || null };
}

export function expiryText(line) {
  return line.count + " " + line.kind + " expire" + (line.count === 1 ? "s" : "") + " " + line.date +
    " · " + line.when;
}

// ---- gifts (R9c) ------------------------------------------------------------------------

export function giftMeta(g) {
  if (!g) return "";
  if (g.status === "CLAIMED") return "claimed";
  if (g.status === "EXPIRED") return "expired";
  return g.expires_at ? "exp " + monDay(g.expires_at) : "";
}

/* The preview a Claim ▸ opens: what, which account, expiry, "One attempt." */
export function giftPreview(g, myName) {
  const exp = g && g.expires_at ? " They expire " + monDay(g.expires_at) + "." : "";
  return "Claims " + ((g && g.what) || "this gift") + " to " + (myName || "this account") + "." +
    exp + " One attempt.";
}

export function bonusText(b) {
  return "Extra bonus: +" + ((b && b.percent) || 0) + "% on credit packs" +
    (b && b.until ? " · until " + monDay(b.until) : "");
}

/* The phone's Gift box row meta: the soonest expiry when one falls in the window (peach),
   otherwise the pending gift count. */
export function giftBoxMeta(expiry, pendingGifts) {
  if (expiry && expiry.soonest) {
    const s = expiry.soonest;
    return { text: s.count + " expire " + s.date, peach: true };
  }
  const n = Number(pendingGifts) || 0;
  return { text: n ? n + " gift" + (n === 1 ? "" : "s") : "", peach: false };
}
