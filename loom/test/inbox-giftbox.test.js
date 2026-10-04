import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE GIFT BOX, WIRED (Sessions R + Y, lane R; Inbox and Event Handoff §1-4, §7, §9). Source
   guards in the way details-actions.test.js reads its components: the door's place and gate,
   what the panel's opening may and may not do, the live count's road, and how Activity tells a
   job PixAI's inbox named. The pure rules are inbox-core.test.js; the server, tests/test_inbox*.py. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const bar = src("gallery/src/components/SeparatorBar.jsx");
const box = src("gallery/src/inbox/GiftBox.jsx");
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
  for (let k = text.indexOf("{", i); k < text.length; k++) {
    if (text[k] === "{") depth++;
    else if (text[k] === "}" && --depth === 0) return text.slice(i, k + 1);
  }
  throw new Error(name + " never closes");
};

describe("the door (R1a)", () => {
  test("it sits in the header's right group just before the credits chip, only with a linked account", () => {
    const door = bar.indexOf("<GiftBox ");
    const chip = bar.indexOf('className="mgx-cred" data-expiring');
    assert.ok(door > 0 && chip > door, "the gift box renders before the credits chip");
    assert.match(bar, /\{linked \? <GiftBox /);
    assert.match(bar, /const linked = !!\(account && !account\.error && account\.credits != null\)/);
  });

  test("30 x 30, radius 9, the pack's gift art at 22 px, a lavender badge, a ring while open", () => {
    assert.match(css, /\.ib-door \{[^}]*width: 30px; height: 30px;[^}]*border-radius: 9px;/);
    assert.match(css, /url\(\/branding\/rewards\/gift\.png\) center \/ 22px auto no-repeat/);
    assert.match(css, /\.ib-badge \{[^}]*background: var\(--lavender\)/);
    assert.match(css, /\.ib-door\.lift \{ box-shadow: 0 0 0 2px var\(--lavender\); \}/);
    assert.match(box, /title="PixAI inbox"/);
  });

  test("the panel: 380 px, z 300, scrolls inside, .42 s in and .35 s out with a 350 ms unmount", () => {
    assert.match(css, /\.ib-panel \{[^}]*z-index: 300;[^}]*width: 380px;[^}]*max-height: calc\(100dvh - 96px\)/);
    assert.match(css, /animation: ibIn \.42s/);
    assert.match(css, /\.ib-panel\.closing \{ animation: ibOut \.35s/);
    assert.match(box, /const CLOSE_MS = 350;/);
    assert.match(css, /prefers-reduced-motion: reduce\)[^]*\.ib-panel \{ animation: none; \}/);
  });

  test("Esc, an outside click or the button closes it", () => {
    assert.match(box, /e\.key === "Escape"\) close\(\)/);
    assert.match(box, /addEventListener\("mousedown", onDoc\)/);
  });
});

describe("opening writes nothing (R3b)", () => {
  test("the panel's reads are GETs: the first page, the gifts, the events", () => {
    for (const name of ["loadFirst", "loadMore", "loadEvents", "loadGifts", "readCount"]) {
      const body = fnBody(store, name);
      assert.ok(!/apiPost/.test(body), name + " must not write");
      assert.match(body, /apiGet\(/);
    }
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
  test("the Gifts tab has no Mark all read, and no tab is ever turned into All", () => {
    assert.match(list, /export function MarkAllMenu\(\{ tab \}\) \{\n  const \[menu, setMenu\] = useState\(false\);\n  if \(tab === "gifts"\) return null;/);
    assert.ok(!/"gifts" \? "all"/.test(list + box + src("gallery/src/inbox/InboxSheets.jsx")));
    assert.match(fnBody(store, "markAllRead"), /\{ csrf, tab \}|tab \}\)/);
    assert.ok(!/tab \|\| "all"/.test(fnBody(store, "markAllRead")), "the store must not default a tab to all");
  });
});

describe("delivery (R4b)", () => {
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
