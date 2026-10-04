import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE PHONE'S DOORS (Sessions R + Y, RYPc; Inbox and Event Handoff §10, drift 132). The phone
   keeps its 320 px header as shipped, carries the badge on its Menu door, and makes Inbox and
   Gift box the Menu's first two rows, each a full-height sheet. Since the owner's walk
   (2026-10-04) the desktop has the same two doors, and gifts live only in the Gift box: the
   Inbox sheet has no Gifts tab. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const app = src("gallery/src/components/AppMobile.jsx");
const sheets = src("gallery/src/inbox/InboxSheets.jsx");
const css = src("gallery/src/styles/inbox.css");
const list = src("gallery/src/inbox/InboxList.jsx");
const core = src("gallery/src/inbox/inboxCore.js");

const fnBody = (text, name) => {
  const i = text.indexOf("export function " + name + "(");
  assert.ok(i >= 0, name + " is exported");
  let depth = 0;
  // the body's brace, after the parameter list (which may destructure: "({ st, tab }) {")
  for (let k = text.indexOf(") {", i) + 2; k < text.length; k++) {
    if (text[k] === "{") depth++;
    else if (text[k] === "}" && --depth === 0) return text.slice(i, k + 1);
  }
  throw new Error(name + " never closes");
};

describe("the Menu door and its rows", () => {
  test("the Menu door carries the inbox's badge: unread plus pending gifts", () => {
    const door = app.indexOf('title="More"');
    const badge = app.indexOf("<MenuBadge st={inboxSt} />");
    assert.ok(door > 0 && badge > door && badge - door < 400, "the badge sits inside the Menu button");
    assert.match(fnBody(sheets, "MenuBadge"), /badgeText\(st\.count\)/);
  });

  test("the Inbox row counts unread notifications only; gifts are the Gift box row's", () => {
    const rows = fnBody(sheets, "MenuInboxRows");
    assert.match(rows, /const n = st \? badgeText\(st\.unread\) : "";/);
  });

  test("Inbox and Gift box are the Menu's first two rows, with a linked account", () => {
    const menu = app.indexOf('<MobileSheet open={sheet === "menu"}');
    const rows = app.indexOf("<MenuInboxRows ", menu);
    const items = app.indexOf("MENU_ITEMS.map", menu);
    assert.ok(menu > 0 && rows > menu && items > rows, "the two rows come before every other Menu row");
    assert.match(app, /\{account && !account\.error && account\.credits != null \? \(\n\s*<MenuInboxRows/);
    assert.match(sheets, />Inbox\n/);
    assert.match(sheets, /Gift box\n/);
  });

  test("the Gift box row shows the soonest expiry in peach, otherwise the pending gifts", () => {
    assert.match(sheets, /const meta = giftBoxMeta\(expiry, st \? st\.gifts : 0\);/);
    assert.match(sheets, /"ib-mrow-meta" \+ \(meta\.peach \? " peach" : ""\)/);
    assert.match(css, /\.ib-mrow-meta\.peach \{[^}]*color: var\(--peach\); \}/);
  });
});

describe("the two sheets", () => {
  test("each opens full height with MobileSheet's own 280 ms exit", () => {
    assert.match(app, /<MobileSheet open=\{sheet === "inbox"\}[^>]*\n?\s*className="ib-sheet">/);
    assert.match(app, /<MobileSheet open=\{sheet === "gifts"\}[^>]*\n?\s*className="ib-sheet">/);
    assert.match(css, /\.glm-sheet\.ib-sheet \{ height: calc\(100dvh - 40px\);/);
  });

  test("the Inbox sheet has no Gifts tab, reads no gifts, and its N new is the unread count", () => {
    const body = fnBody(sheets, "InboxSheetBody");
    assert.ok(!/loadGifts|loadEvents|GiftRows|EventCards/.test(body), "gifts live only in the Gift box");
    assert.match(body, /st\.unread \? st\.unread \+ " new" : ""/);
    assert.ok(!/"gifts"|"Gifts"/.test(core.slice(core.indexOf("export const TABS"), core.indexOf("];") + 2)),
      "no Gifts tab");
  });

  test("the Inbox sheet's tabs scroll as one row; rows are at least 44 px", () => {
    assert.match(sheets, /<KindTabs tab=\{tab\} onTab=\{setTab\} phone \/>/);
    assert.match(css, /\.ib-tabs\.phone \{ flex-wrap: nowrap; overflow-x: auto;/);
    assert.match(css, /\.ib-sheetbody \.ib-row \{ min-height: 44px; \}/);
  });

  test("the Gift box sheet is the desktop gift box's body: events, the expiring cards in peach, the gifts", () => {
    const body = fnBody(sheets, "GiftSheetBody");
    assert.match(body, /<GiftBoxBody st=\{st\} account=\{account\}/);
    assert.match(body, /loadEvents\(\); loadGifts\(\);/);
    const shared = fnBody(list, "GiftBoxBody");
    const ev = shared.indexOf("<EventCards ");
    const exp = shared.indexOf("ib-expiry-line");
    const gifts = shared.indexOf("<GiftRows ", ev);
    assert.ok(ev > 0 && exp > ev && gifts > exp);
  });
});
