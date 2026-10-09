import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE THREAD IN DETAILS, WIRED (Session R, R5b + R6c; Inbox and Event Handoff §5-6, §10; drift
   127-128). Source guards: where the thread mounts, that it reads only when scrolled to, and
   that one question's press is at most one POST -- the first write that posts words to another
   person. The thread's pure rules are inbox-core.test.js; the server's write rules,
   dev/tests/test_inbox_comments.py. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const details = src("gallery/src/components/DetailsView.jsx");
const mobile = src("gallery/src/components/ImageDetailsMobile.jsx");
const thread = src("gallery/src/inbox/CommentsThread.jsx");
const css = src("gallery/src/styles/comments.css");

describe("where it lives", () => {
  test("Image Details and Image Details Mobile both carry the thread; the 💬 count left the Engagement line", () => {
    assert.match(details, /<CommentsThread row=\{row\} \/>/);
    assert.match(mobile, /<CommentsThread row=\{row\} phone \/>/);
    assert.ok(!/💬 " \+ \(row\.comment_count/.test(details), "the desktop's 💬 n count is gone");
    assert.ok(!/💬 \{row\.comment_count/.test(mobile), "the phone's 💬 n count is gone");
  });

  test("only a published work of yours gets one", () => {
    assert.match(thread, /const published = !!\(row && row\.is_published === "1" && artworkId\);/);
    assert.match(thread, /if \(!published\) return null;/);
  });
});

describe("the read (R5b)", () => {
  test("it reads when the section scrolls into view, not when Details opens", () => {
    assert.match(thread, /new IntersectionObserver/);
    assert.match(thread, /if \(published && seen\) read\(1\);/);
  });

  test("flagged comments hide behind one count line; there is no like, react or report control", () => {
    assert.match(thread, /hiddenLine\(t\.hidden\)/);
    // Every write the thread can make is the reply or the delete -- nothing likes, reacts or reports.
    const targets = (thread.match(/apiPost\([^,]+,/g) || []).map((s) => s.replace(/\s+/g, " "));
    assert.equal(targets.length, 2);
    assert.ok(targets.every((t) => /"\/reply",$|"\/delete",$/.test(t)), targets.join(" | "));
  });

  test("a read that lands after the picture changed is dropped; arriving from the inbox opens at the comments", () => {
    assert.match(thread, /if \(current\.current !== artworkId\) return;/);
    assert.match(thread, /arrived\.current = !!f;/);
    assert.match(thread, /else ref\.current\.scrollIntoView\(\{ block: "start" \}\);/);
  });

  test("the header count is the catalog's until the read lands, then PixAI's", () => {
    assert.match(thread, /data && data\.total != null \? data\.total : Number\(row\.comment_count \|\| 0\)/);
  });
});

describe("the reply (R6c): one question, one press, one POST", () => {
  test("Send asks first -- a wide quoting toast on the desktop, a bottom sheet on the phone", () => {
    assert.match(thread, /quote: b\.text\.trim\(\), wide: true, sticky: true/);
    assert.match(thread, /\{ label: "Post publicly", run: \(\) => post\(tok, b\) \}/);
    assert.match(thread, /<MobileSheet open=\{!!ask\}/);
    assert.match(css, /\.cm-askacts \.big \{ flex: 1; min-height: 44px;/);
  });

  test("a question's press spends its token, and nothing posts while a post is in flight", () => {
    assert.match(thread, /if \(tok !== askToken\.current \|\| inFlight\.current \|\| !b\) return;\n    askToken\.current \+= 1;\n    inFlight\.current = true;/);
  });

  test("an unclear answer keeps Send off until the text changes; READ_ONLY shows the box disabled with why", () => {
    assert.match(thread, /lastSent: state === "unclear" \? b\.text : null/);
    assert.match(thread, /\(box\.lastSent != null && box\.lastSent === box\.text\)/);
    assert.match(thread, /Read-only mode is on \(READ_ONLY in config\.json\), so replies are off\./);
  });

  test("the counter turns peach past 4,095 and Esc cancels", () => {
    assert.match(css, /\.cm-count\.over \{ color: var\(--peach\); \}/);
    assert.match(thread, /e\.key === "Escape"\) \{ e\.preventDefault\(\); setBox\(null\); \}/);
  });

  test("a reply's or a delete's answer is dropped if another picture is open by then (review item 6)", () => {
    const sends = thread.match(/const aid = artworkId;/g) || [];
    assert.equal(sends.length, 2, "both writes remember which work they were sent for");
    const drops = thread.match(/inFlight\.current = false;\n\s*if \(current\.current !== aid\) return;/g) || [];
    assert.equal(drops.length, 2, "both answers release the lock, then drop themselves when the work changed");
  });

  test("an unclear delete keeps that reply's Delete off until the thread is read again (review item 3)", () => {
    assert.match(thread, /if \(state === "unclear"\) setDelLocked\(\(ids\) => ids\.concat\(\[c\.id\]\)\);/);
    assert.match(thread, /if \(p === 1\) setDelLocked\(\[\]\);/);
    assert.match(thread, /if \(inFlight\.current \|\| delLocked\.indexOf\(c\.id\) >= 0\) return;/);
    assert.match(thread, /deleteOff=\{delLocked\.indexOf\(ch\.root\.id\) >= 0\}/);
  });

  test("Delete my reply is ruby, offered under a reply you posted while the thread is open, and asks first", () => {
    assert.match(css, /\.cm-delete \{[^}]*color: var\(--ruby\)/);
    assert.match(thread, /const canDelete = \(c\) => c\.you && !readOnly && posted\.indexOf\(c\.id\) >= 0;/);
    assert.match(thread, /\{ label: "Delete", tone: "ruby", run: \(\) => del\(tok, c\) \}/);
  });
});
