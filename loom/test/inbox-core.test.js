import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  TABS, badgeText, groupInbox, workDelta, rowText, timeAgo, toasts, commentToast, threadOf,
  hiddenLine, commentMeta, replyCheck, replyQuestion, deleteQuestion, monDay, expiryWhen,
  expiringLines, expiryText, giftMeta, giftPreview, bonusText, giftBoxMeta, REPLY_MAX,
} from "../../gallery/src/inbox/inboxCore.js";

/* SESSIONS R + Y, THE PURE HALF (lane R, 2026-10-03): the gift box's badge, the inbox read by
   work, the thread's chains, the reply's counter, the cards about to expire, the gift rows.
   Design: Inbox and Event Handoff.dc.html, notes/inbox-event/NOTES.md, drift 123-133. The
   server half (moonglade_inbox.py) is pinned by tests/test_inbox*.py. */

const ART = { id: "17886", title: "Moonwell Vigil", thumb: "", media_id: "m1" };
const ART2 = { id: "17887", title: "Lantern Choir", thumb: "", media_id: "" };
const u = (name) => ({ id: "u" + name, name });
const like = (id, at, o) => ({ id, type: "LIKE", cat: "like", unread: true, created_at: at,
  users: [u("Aster")], artwork: ART, content: "", ...o });
const comment = (id, at, o) => ({ id, type: "COMMENT", cat: "comment", unread: true,
  created_at: at, users: [u("kurone")], artwork: ART, content: "the hair light is unreal\nsecond line", ...o });
const follow = (id, at, name) => ({ id, type: "FOLLOW", cat: "follow", unread: true, created_at: at,
  users: [u(name)], artwork: null });

describe("the badge", () => {
  test("nothing at zero or unknown, the number up to 99, then 99+", () => {
    assert.equal(badgeText(0), "");
    assert.equal(badgeText(null), "");
    assert.equal(badgeText(5), "5");
    assert.equal(badgeText(99), "99");
    assert.equal(badgeText(100), "99+");
  });

  test("the tabs are the handoff's six, in its order", () => {
    assert.deepEqual(TABS.map((t) => t[1]), ["All", "Comments", "Likes", "Follows", "Gifts", "PixAI"]);
  });
});

describe("the inbox, by work (R2c)", () => {
  const items = [
    comment("c1", "2026-10-03T11:00:00Z"),
    like("l1", "2026-10-03T10:00:00Z", { users: [u("Aster"), u("Ilya")] }),
    comment("c0", "2026-10-03T09:00:00Z", { unread: false }),
    like("l2", "2026-10-03T08:00:00Z", { artwork: ART2, unread: false }),
    follow("f1", "2026-10-02T09:00:00Z", "Aster"),
    follow("f2", "2026-10-02T10:00:00Z", "Ilya"),
    follow("f3", "2026-10-02T11:00:00Z", "Mio"),
    { id: "k1", type: "CONTEST_RESULT_PUBLISHED", cat: "contest", unread: false,
      created_at: "2026-10-01T00:00:00Z", users: [], contest: { slug: "x", title: "Cool pose" } },
  ];

  test("one card per work, newest first, carrying every id it gathers", () => {
    const g = groupInbox(items, "all");
    assert.deepEqual(g.works.map((w) => w.artwork.id), ["17886", "17887"]);
    assert.deepEqual(g.works[0].ids, ["c1", "l1", "c0"]);
    assert.equal(g.works[0].unread, true);
    assert.equal(g.works[1].unread, false);
  });

  test("likes count the people, comments count unread as new, zeroes are omitted", () => {
    const g = groupInbox(items, "all");
    assert.equal(workDelta(g.works[0]), "♥ +2 · ❝ 1 new");
    assert.equal(workDelta(g.works[1]), "♥ +1");
  });

  test("the quote is the newest unread comment's first line", () => {
    const g = groupInbox(items, "all");
    assert.deepEqual(g.works[0].quote, { name: "kurone", text: "the hair light is unreal", id: "c1" });
  });

  test("follows fold per day with two names and the rest counted", () => {
    const g = groupInbox(items, "all");
    const f = g.rest.find((r) => r.kind === "follow");
    assert.deepEqual(f.ids, ["f1", "f2", "f3"]);
    assert.equal(f.text, "3 new followers · Aster, Ilya and 1 more");
  });

  test("a contest is one row of its own", () => {
    const g = groupInbox(items, "all");
    assert.equal(g.rest.find((r) => r.kind === "contest").text, "Contest results are out: “Cool pose”");
  });

  test("each tab shows its own kinds", () => {
    assert.equal(groupInbox(items, "follows").works.length, 0);
    assert.equal(groupInbox(items, "likes").works[0].ids.join(), "l1");
    assert.equal(groupInbox(items, "pixai").rest.length, 1);
    assert.equal(groupInbox(items, "gifts").rest.length, 0);
  });

  test("a news row says PixAI and its first line", () => {
    assert.equal(rowText({ cat: "news", type: "NEWS", content: "Tsubaki.3 now supports 4K\nmore" }),
      "PixAI: Tsubaki.3 now supports 4K");
  });

  test("time is hours and days, never seconds", () => {
    const now = Date.parse("2026-10-03T14:00:00Z");
    assert.equal(timeAgo("2026-10-03T11:00:00Z", now), "3h");
    assert.equal(timeAgo("2026-10-02T13:00:00Z", now), "1d");
    assert.equal(timeAgo("2026-10-03T13:59:30Z", now), "now");
  });
});

describe("delivery (R4b): only comments toast", () => {
  test("a comment or a reply toasts; a like, a follow, news and contests only move the badge", () => {
    assert.equal(toasts(comment("c1", "")), true);
    assert.equal(toasts({ type: "COMMENT_REPLY" }), true);
    ["LIKE", "FOLLOW", "NEWS", "CONTEST_RESULT_PUBLISHED"].forEach((t) => assert.equal(toasts({ type: t }), false));
  });

  test("the toast names who and which work, and quotes the first line", () => {
    assert.deepEqual(commentToast(comment("c1", "")),
      { title: "kurone commented on Moonwell Vigil", msg: "“the hair light is unreal”" });
  });
});

describe("the thread (R5b)", () => {
  const c = (id, at, o) => ({ id, created_at: at, reply_to: "", you: false, flagged: false,
    reactions: 0, author: { name: id }, content: id, ...o });
  const thread = [
    c("a", "2026-10-03T10:00:00Z"),
    c("a1", "2026-10-03T11:00:00Z", { reply_to: "a", you: true }),
    c("b", "2026-10-02T10:00:00Z"),
    c("b1", "2026-10-02T12:00:00Z", { reply_to: "b" }),
    c("b2", "2026-10-02T11:00:00Z", { reply_to: "b1" }),
    c("x", "2026-10-01T00:00:00Z", { flagged: true }),
    c("orphan", "2026-10-01T05:00:00Z", { reply_to: "not-loaded" }),
  ];

  test("top-level newest first, replies flat under their root, oldest first", () => {
    const t = threadOf(thread, "");
    assert.deepEqual(t.chains.map((ch) => ch.root.id), ["a", "b", "orphan"]);
    assert.deepEqual(t.chains[1].replies.map((r) => r.id), ["b2", "b1"]);
  });

  test("a chain holding your comment opens by itself; one an inbox quote names does too", () => {
    const t = threadOf(thread, "b2");
    assert.equal(t.chains[0].open, true);
    assert.equal(t.chains[1].open, true);
    assert.equal(threadOf(thread, "").chains[1].open, false);
  });

  test("flagged comments are hidden and counted, never blurred", () => {
    const t = threadOf(thread, "");
    assert.equal(t.hidden, 1);
    assert.ok(!t.chains.some((ch) => ch.root.id === "x"));
    assert.equal(hiddenLine(1), "1 comment hidden by PixAI");
    assert.equal(hiddenLine(0), "");
  });

  test("the meta line reads time, reactions and the replies toggle", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    assert.equal(commentMeta(c("a", "2026-10-03T10:00:00Z", { reactions: 3 }), now, 1, true),
      "2h · reactions 3 · 1 reply ▾");
    assert.equal(commentMeta(c("a", "2026-10-03T10:00:00Z"), now, 3, false), "2h · 3 replies ▸");
  });
});

describe("the reply (R6c)", () => {
  test("the counter, and Send off past 4,095 with how far over", () => {
    assert.equal(replyCheck("x".repeat(52)).label, "52 / 4,095");
    assert.equal(replyCheck("x".repeat(REPLY_MAX)).ok, true);
    const over = replyCheck("x".repeat(REPLY_MAX + 3));
    assert.equal(over.ok, false);
    assert.equal(over.tooLong, "Too long by 3");
    assert.equal(replyCheck("   ").empty, true);
  });

  test("counted as PixAI counts: an emoji is two", () => {
    assert.equal(replyCheck("🌙").n, 2);
  });

  test("the questions name who, whose comment and which work", () => {
    assert.equal(replyQuestion("Nelnamara", "kurone", "Moonwell Vigil"),
      "Post publicly as Nelnamara, replying to kurone on Moonwell Vigil?");
    assert.equal(replyQuestion("", "kurone", "Moonwell Vigil"),
      "Post publicly as your PixAI name, replying to kurone on Moonwell Vigil?");
    assert.equal(deleteQuestion("Moonwell Vigil"), "Delete your reply on Moonwell Vigil? This can't be undone.");
  });
});

describe("expiring free cards (Y1c + Y2a)", () => {
  // 2026-10-03 at noon, local time: the lines are in the viewer's calendar.
  const now = new Date(2026, 9, 3, 12, 0, 0).getTime();
  const at = (d, h) => new Date(2026, 9, d, h || 0, 0, 0).toISOString();
  const cards = [
    { name: "Tsubaki.3", count: 15, expiry_counts: [{ expires_at: at(6, 9), count: 5 }, { expires_at: at(9), count: 10 }] },
    { name: "Daily recipe", count: 2, expiry_counts: [{ expires_at: at(4, 23), count: 2 }] },
    { name: "Video", count: 6, expiry_counts: [] },
  ];

  test("one line per kind and date within 72 hours, soonest first", () => {
    const e = expiringLines(cards, now);
    assert.deepEqual(e.lines.map(expiryText),
      ["2 Daily recipe expire Oct 4 · tomorrow", "5 Tsubaki.3 expire Oct 6 · in 3 days"]);
    assert.equal(e.other, 16);
    assert.equal(e.soonest.kind, "Daily recipe");
  });

  test("nothing within the window means no lines at all", () => {
    assert.equal(expiringLines([{ name: "x", count: 1, expiry_counts: [{ expires_at: at(20), count: 1 }] }], now).lines.length, 0);
    assert.equal(expiringLines([], now).soonest, null);
  });

  test("calendar days, never hours: today, tomorrow, in N days", () => {
    assert.equal(expiryWhen(at(3, 23), now), "today");
    assert.equal(expiryWhen(at(4, 1), now), "tomorrow");
    assert.equal(expiryWhen(at(6, 1), now), "in 3 days");
    assert.equal(monDay(at(6, 1)), "Oct 6");
  });

  test("the phone's Gift box row shows the soonest expiry, else the pending gifts", () => {
    assert.deepEqual(giftBoxMeta(expiringLines(cards, now), 1), { text: "2 expire Oct 4", peach: true });
    assert.deepEqual(giftBoxMeta(expiringLines([], now), 2), { text: "2 gifts", peach: false });
    assert.deepEqual(giftBoxMeta(null, 0), { text: "", peach: false });
  });
});

describe("gifts (R9c)", () => {
  const g = { id: "1", what: "3 Tsubaki.3 cards", status: "PENDING", expires_at: "2026-10-09T12:00:00Z" };

  test("a pending gift shows its expiry, a done one says so", () => {
    assert.equal(giftMeta(g), "exp Oct 9");
    assert.equal(giftMeta({ ...g, status: "CLAIMED" }), "claimed");
    assert.equal(giftMeta({ ...g, status: "EXPIRED" }), "expired");
  });

  test("the preview says what, to whom, when it expires, and one attempt", () => {
    assert.equal(giftPreview(g, "Nelnamara"),
      "Claims 3 Tsubaki.3 cards to Nelnamara. They expire Oct 9. One attempt.");
  });

  test("a credit-pack bonus reads as one", () => {
    assert.equal(bonusText({ percent: 20, until: "2026-10-14T12:00:00Z" }),
      "Extra bonus: +20% on credit packs · until Oct 14");
  });
});
