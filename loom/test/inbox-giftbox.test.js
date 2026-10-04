import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE INBOX AND THE GIFT BOX, WIRED (Sessions R + Y, lane R; Inbox and Event Handoff §1-4, §7,
   §9). Source guards in the way details-actions.test.js reads its components: the two doors'
   place and gate, what each panel's opening may and may not do, the live count's road, and how
   Activity tells a job PixAI's inbox named. The pure rules are inbox-core.test.js; the server,
   tests/test_inbox*.py.

   TWO DOORS (owner's walk, 2026-10-04): the gift box is for rewards only. The inbox has its own
   ✉ button beside it, and the two panels are separate -- opening one closes the other. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const bar = src("gallery/src/components/SeparatorBar.jsx");
const box = src("gallery/src/inbox/GiftBox.jsx");
const inboxDoor = src("gallery/src/inbox/InboxDoor.jsx");
const door = src("gallery/src/inbox/useHeaderDoor.js");
const store = src("gallery/src/inbox/inboxStore.js");
const list = src("gallery/src/inbox/InboxList.jsx");
const css = src("gallery/src/styles/inbox.css");
const jobs = src("gallery/src/notify/jobsStore.js");
const row = src("gallery/src/notify/ActivityRow.jsx");
const toastStore = src("gallery/src/notify/toastStore.js");
const toastHost = src("gallery/src/notify/ToastHost.jsx");

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

describe("two doors: ✉ Inbox, then 🎁 Gift box, then the credits chip (owner's walk 2026-10-04)", () => {
  test("both sit in the header's right group before the credits chip, only with a linked account", () => {
    const inbox = bar.indexOf("<InboxDoor ");
    const gift = bar.indexOf("<GiftBox ");
    const chip = bar.indexOf('className="mgx-cred" data-expiring');
    assert.ok(inbox > 0 && gift > inbox && chip > gift, "✉ Inbox, then 🎁 Gift box, then the credits chip");
    assert.match(bar, /\{linked \? <InboxDoor /);
    assert.match(bar, /\{linked \? <GiftBox /);
    assert.match(bar, /const linked = !!\(account && !account\.error && account\.credits != null\)/);
  });

  test("twins: 30 x 30, radius 9, a lavender badge, a ring while open; the gift art only on the gift box", () => {
    assert.match(css, /\.ib-door \{[^}]*width: 30px; height: 30px;[^}]*border-radius: 9px;/);
    assert.ok(!/\.ib-door \{[^}]*gift\.png/.test(css), "the shared door carries no gift art");
    assert.match(css, /\.ib-door\.gift \{[^}]*url\(\/branding\/rewards\/gift\.png\) center \/ 22px auto no-repeat/);
    assert.match(css, /\.ib-badge \{[^}]*background: var\(--lavender\)/);
    assert.match(css, /\.ib-door\.lift \{ box-shadow: 0 0 0 2px var\(--lavender\); \}/);
    assert.match(inboxDoor, /className=\{"ib-door inbox"/);
    assert.match(box, /className=\{"ib-door gift"/);
  });

  test("✉ wears the phone Menu's envelope and the title \"PixAI inbox\"; 🎁 is the \"Gift box\"", () => {
    assert.match(inboxDoor, /title="PixAI inbox"/);
    assert.match(inboxDoor, /<span className="ib-door-glyph" aria-hidden="true">✉<\/span>/);
    assert.match(src("gallery/src/inbox/InboxSheets.jsx"), /aria-hidden="true">✉<\/span>Inbox/);
    assert.match(box, /title="Gift box"/);
    assert.ok(!/PixAI inbox/.test(box), "the gift box is not the inbox");
  });

  test("✉ counts unread notifications; 🎁 counts only the pending gifts", () => {
    assert.match(inboxDoor, /const badge = badgeText\(st\.unread\);/);
    assert.match(box, /const badge = badgeText\(st\.gifts\);/);
    assert.ok(!/st\.count/.test(inboxDoor + box), "neither header door shows the combined count");
  });

  test("each panel: 380 px, z 300, scrolls inside, .42 s in and .35 s out with a 350 ms unmount", () => {
    assert.match(css, /\.ib-panel \{[^}]*z-index: 300;[^}]*width: 380px;[^}]*max-height: calc\(100dvh - 96px\)/);
    assert.match(css, /animation: ibIn \.42s/);
    assert.match(css, /\.ib-panel\.closing \{ animation: ibOut \.35s/);
    assert.match(door, /export const CLOSE_MS = 350;/);
    assert.match(css, /prefers-reduced-motion: reduce\)[^]*\.ib-panel \{ animation: none; \}/);
    for (const d of [inboxDoor, box]) {
      assert.match(d, /useHeaderDoor\("/);
      assert.match(d, /className=\{"ib-panel" \+ \(door\.closing \? " closing" : ""\)\}/);
    }
  });

  test("Esc, an outside click or the button closes a panel; opening one closes the other", () => {
    assert.match(door, /e\.key === "Escape"\) close\(\)/);
    assert.match(door, /addEventListener\("mousedown", onDoc\)/);
    assert.match(door, /others\.forEach\(\(fn\) => fn\(name\)\)/);
    assert.match(door, /if \(who !== name\) close\(\);/);
    assert.notEqual(inboxDoor.match(/useHeaderDoor\("(\w+)"/)[1], box.match(/useHeaderDoor\("(\w+)"/)[1]);
  });
});

describe("what each panel holds (owner's walk 2026-10-04)", () => {
  test("the inbox: Inbox + N new, the tabs, the work cards and everything else -- no gifts, no events", () => {
    assert.match(inboxDoor, /<span className="ib-title">Inbox<\/span>/);
    assert.match(inboxDoor, /<KindTabs tab=\{tab\} onTab=\{setTab\} \/>/);
    assert.match(inboxDoor, /<MarkAllMenu tab=\{tab\} \/>/);
    assert.match(inboxDoor, /<InboxBody st=\{st\} tab=\{tab\}/);
    const body = fnBody(list, "InboxBody");
    assert.ok(!/EventCards|GiftRows|giftData|"gifts"/.test(body), "the inbox carries no gifts and no events");
    assert.ok(!/EventCards|GiftRows|loadGifts|loadEvents/.test(inboxDoor));
  });

  test("the gift box: Gift box, then ON PIXAI NOW, the expiring cards in peach, then the gifts", () => {
    assert.match(box, /<span className="ib-title">Gift box<\/span>/);
    assert.match(box, /<GiftBoxBody st=\{st\} account=\{account\}/);
    const body = fnBody(list, "GiftBoxBody");
    const ev = body.indexOf("<EventCards ");
    const exp = body.indexOf('className="ib-expiry-line"');
    const gifts = body.indexOf("<GiftRows ");
    assert.ok(ev > 0 && exp > ev && gifts > exp, "events, then the expiring cards, then the gifts");
    assert.match(body, /expiringLines\(cardsBy, now\)/);
    assert.match(body, /expiryText\(l\)/);
    assert.match(css, /\.ib-expiry-line \{[^}]*color: var\(--peach\); \}/);
    assert.ok(!/KindTabs|MarkAllMenu|InboxBody/.test(box), "no tabs, no Mark all read, no inbox rows");
  });

  test("with nothing in any of the three, one quiet line", () => {
    const body = fnBody(list, "GiftBoxBody");
    assert.match(body, /Nothing waiting\. Gifts from PixAI and cards about to expire show here\./);
  });
});

describe("opening writes nothing (R3b)", () => {
  test("the panels' reads are GETs: the first page, the gifts, the events", () => {
    for (const name of ["loadFirst", "loadMore", "loadEvents", "loadGifts", "readCount"]) {
      const body = fnBody(store, name);
      assert.ok(!/apiPost/.test(body), name + " must not write");
      assert.match(body, /apiGet\(/);
    }
  });

  test("opening the inbox reads its first page; opening the gift box reads the gifts and the events", () => {
    assert.match(inboxDoor, /useHeaderDoor\("inbox", \(\) => \{ loadFirst\(\); \}\)/);
    assert.match(box, /useHeaderDoor\("gifts", \(\) => \{ loadGifts\(\); loadEvents\(\); \}\)/);
    assert.ok(!/apiPost|claimGift|markAllRead|openItem/.test(box + door), "opening the gift box writes nothing");
  });

  test("the only writes are a row's open, Mark all read and a gift's Claim", () => {
    const posts = store.match(/apiPost\("[^"]+"/g) || [];
    assert.deepEqual(posts.sort(), ['apiPost("/api/inbox/gifts/claim"', 'apiPost("/api/inbox/read"',
      'apiPost("/api/inbox/read-all"'].sort());
    assert.ok(/apiPost\("\/api\/inbox\/read"/.test(fnBody(store, "openItem")));
  });

  test("under READ_ONLY a row opens and nothing is marked; an unclear answer leaves the peach line", () => {
    const open = fnBody(store, "openItem");
    assert.ok(open.indexOf("navigate(row)") < open.indexOf("apiPost"), "the row opens first, always");
    assert.match(open, /if \(!row\.unread \|\| state\.readOnly\) return/);
    assert.match(open, /set\(\{ notice: \{ key: row\.key/);
    assert.match(list, /Opening this marks it read on PixAI\./);
    assert.match(list, /Read-only mode is on, so this stays unread on PixAI\./);
    assert.match(list, /const TIP_DELAY_MS = 600;/);
  });

  test("a push never writes: it bumps the badge and reads the new rows", () => {
    const live = fnBody(store, "noteLive");
    assert.ok(!/apiPost/.test(live));
    assert.match(live, /readCount\(\)/);
    assert.match(live, /pullPushed\(prev\.seq\)/);
  });
});

describe("Mark all read names its own tab (review item 2)", () => {
  test("there is no Gifts tab to mark, and no tab is ever turned into All", () => {
    assert.ok(!/"gifts"/.test(fnBody(list, "MarkAllMenu")), "gifts clear on claim, and they are not in the inbox");
    assert.ok(!/"gifts" \? "all"/.test(list + box + inboxDoor + src("gallery/src/inbox/InboxSheets.jsx")));
    assert.match(fnBody(store, "markAllRead"), /\{ csrf, tab \}|tab \}\)/);
    assert.ok(!/tab \|\| "all"/.test(fnBody(store, "markAllRead")), "the store must not default a tab to all");
  });
});

describe("an unclear claim locks that gift's Claim until the gifts are read again (review item 3)", () => {
  test("the store locks it on any answer that is not a clear done or refusal, and only a fresh read unlocks", () => {
    const claim = fnBody(store, "claimGift");
    assert.match(claim, /if \(state\.claimLocked\[id\]\) return Promise\.resolve\(null\);/);
    assert.match(claim, /claimLocked: \{ \.\.\.state\.claimLocked, \[id\]: true \}/);
    assert.match(fnBody(store, "loadGifts"), /claimLocked: d\.error \? state\.claimLocked : \{\}/);
  });

  test("both of the gift's Claim buttons stay off while it is locked", () => {
    const locked = (list.match(/const locked = !!\(claimLocked && claimLocked\[g\.id\]\);/g) || []).length;
    assert.equal(locked, 1);
    assert.equal((list.match(/disabled=\{readOnly \|\| locked\}/g) || []).length, 1, "Claim ▸");
    assert.match(list, /disabled=\{!!\(mine && mine\.state === "sending"\) \|\| readOnly \|\| locked\}/);
  });
});

describe("one mark-read per open, with a token (review nit 9)", () => {
  test("a double click on a row sends one mark-read", () => {
    const open = fnBody(store, "openItem");
    assert.match(open, /if \(marking\.has\(key\)\) return Promise\.resolve\(null\);\n\s*marking\.add\(key\);/);
    assert.match(open, /\.finally\(\(\) => marking\.delete\(key\)\)/);
  });

  test("every write fetches the CSRF token first when the panel never handed one out", () => {
    assert.match(fnBody(store, "ensureCsrf"), /apiGet\("\/api\/inbox\/count"\)/);
    for (const name of ["openItem", "markAllRead", "claimGift"]) {
      assert.match(fnBody(store, name), /ensureCsrf\(\)\.then\(/, name + " waits for the token");
    }
    assert.match(fnBody(store, "readCount"), /csrf: d\.csrf \|\| state\.csrf/);
  });
});

describe("delivery (R4b)", () => {
  test("the count read keeps the unread notifications and the pending gifts apart from the total", () => {
    assert.match(fnBody(store, "readCount"), /set\(\{ count: d\.total, unread: d\.unread, gifts: d\.gifts \}\)/);
    assert.match(fnBody(store, "ensureCsrf"), /set\(\{ count: d\.total, unread: d\.unread, gifts: d\.gifts \}\)/);
    // a push is a notification: it bumps the total and the unread, never the gifts
    const live = fnBody(store, "noteLive");
    assert.match(live, /count: state\.count \+ \(live\.seq - prev\.seq\)/);
    assert.match(live, /unread: state\.unread != null \? state\.unread \+ \(live\.seq - prev\.seq\) : state\.unread/);
    // a row read comes off both
    const open = fnBody(store, "openItem");
    assert.match(open, /count: state\.count != null \? Math\.max\(0, state\.count - was\) : state\.count/);
    assert.match(open, /unread: state\.unread != null \? Math\.max\(0, state\.unread - was\) : state\.unread/);
  });

  test("the live count rides the Activity poll; a reconnect re-reads the count; focus at most every 30 s", () => {
    assert.match(jobs, /if \(d && !d\.error && d\.inbox\) pollListeners\.forEach/);
    assert.match(jobs, /export function onInboxLive\(fn\)/);
    assert.match(store, /onInboxLive\(noteLive\)/);
    assert.match(store, /const FOCUS_GAP_MS = 30000;/);
    assert.match(fnBody(store, "noteLive"), /if \(live\.connects > prev\.connects\) readCount\(\)/);
  });

  test("only comments toast, with [Later] [Open thread]", () => {
    assert.match(store, /fresh\.filter\(toasts\)\.forEach/);
    assert.match(store, /\{ label: "Later", run: \(\) => \{\} \}/);
    assert.match(store, /\{ label: "Open thread", run:/);
  });

  test("a job only PixAI's inbox told the app about is a quiet Activity line marked as PixAI's", () => {
    assert.match(jobs, /if \(j\.via === "inbox"\) \{ last\[j\.job_id\] = st; return; \}/);
    assert.match(row, /title=\{j\.via === "inbox" \? "Started on the PixAI website; PixAI's inbox told the app it finished\."/);
    assert.match(row, /PixAI says: \{j\.pixai_says\}/);
  });
});

describe("gifts (R9c) and the current event (Y3a)", () => {
  test("Claim ▸ opens a preview with [Back] [Claim]; done gifts dim", () => {
    assert.match(list, />Claim ▸<\/button>/);
    assert.match(list, /giftPreview\(g, data\.my_name\)/);
    assert.match(css, /\.ib-gift\.done \{ opacity: \.6; \}/);
  });

  test("an event card opens PixAI in a new tab and the app never requests the link", () => {
    assert.match(list, /window\.open\(e\.link, "_blank", "noopener"\)/);
    assert.ok(!/apiGet\(e\.link|fetch\(e\.link/.test(list));
    assert.match(css, /\.ib-event \{[^}]*height: 58px;[^}]*border-radius: 9px;/);
  });
});

describe("the question toast can quote", () => {
  test("a toast may carry a quote clamped at six lines and widen to 420 px", () => {
    assert.match(toastStore, /quote: o\.quote \? String\(o\.quote\) : ""/);
    assert.match(toastStore, /wide: !!o\.wide/);
    assert.match(toastHost, /className=\{"mt-quote"/);
  });
});
