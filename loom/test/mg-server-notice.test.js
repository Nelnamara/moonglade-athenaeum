import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The server's one-time notice (3.20, "the move"): a server started through the stand-in an
   old launcher left behind asks every open tab, once per server start, to stop Moonglade
   once and start it again. gallery/src/notify/serverNotice.js decides when; the existing corner
   toast says it.

     1. ONCE PER SERVER START. The same key on every poll, a reload or a second tab: one toast.
        A new key (the server started again, still through the old launcher): one more.
     2. NOTHING TO SAY IS NOTHING SHOWN. null, a dropped poll, a notice with no key.
     3. A BROWSER THAT BLOCKS STORAGE still says it once, not on every poll.
     4. IT RIDES THE POLL every tab already runs (jobsStore.js), not a loop of its own.

   Driven for real: serverNotice.js and toastStore.js are pure modules, so a fake
   localStorage is the only stand-in needed. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");

const bag = new Map();
let blocked = false;
globalThis.localStorage = {
  getItem: (k) => { if (blocked) throw new Error("SecurityError"); return bag.has(k) ? bag.get(k) : null; },
  setItem: (k, v) => { if (blocked) throw new Error("SecurityError"); bag.set(k, String(v)); },
  removeItem: (k) => bag.delete(k),
};

const toastURL = new URL("../../gallery/src/notify/toastStore.js", import.meta.url).href;
const noticeURL = new URL("../../gallery/src/notify/serverNotice.js", import.meta.url).href;
const toasts = await import(toastURL);

let n = 0;
async function freshNotice() {
  // a fresh module per test (its memory copy is module state); the toast store is shared
  return import(noticeURL + "?t=" + (++n));
}

const MOVED = { key: "a1", title: "Moonglade moved into its new folder.",
                msg: "Stop it once (Control Panel → Server → ■ Stop, and confirm), then start it again from its shortcut." };

function shown() { return toasts.getToasts().filter((t) => !t.out); }
function clearToasts() { toasts.getToasts().forEach((t) => toasts.dismiss(t.id)); }

beforeEach(() => { bag.clear(); blocked = false; clearToasts(); });

test("the same server start says it once, however often the poll brings it", async () => {
  const { noteServerNotice } = await freshNotice();
  const before = shown().length;
  assert.equal(noteServerNotice(MOVED), true);
  assert.equal(noteServerNotice(MOVED), false);
  assert.equal(noteServerNotice({ ...MOVED }), false);
  const added = shown().slice(before);
  assert.equal(added.length, 1);
  assert.equal(added[0].title, MOVED.title);
  assert.equal(added[0].msg, MOVED.msg);
  assert.equal(added[0].sticky, true);
  assert.equal(added[0].kind, "");
});

test("a reload or a second tab does not say it again; the next server start does", async () => {
  (await freshNotice()).noteServerNotice(MOVED);
  const tab2 = await freshNotice();
  assert.equal(tab2.noteServerNotice(MOVED), false);
  assert.equal(tab2.noteServerNotice({ ...MOVED, key: "b2" }), true);
});

test("nothing to say shows nothing", async () => {
  const { noteServerNotice } = await freshNotice();
  const before = shown().length;
  for (const v of [null, undefined, {}, { key: "" , title: "x" }, { key: "k" }]) {
    assert.equal(noteServerNotice(v), false);
  }
  assert.equal(shown().length, before);
});

test("a browser that blocks storage still says it once", async () => {
  blocked = true;
  const { noteServerNotice } = await freshNotice();
  assert.equal(noteServerNotice(MOVED), true);
  assert.equal(noteServerNotice(MOVED), false);
});

test("it rides the jobs poll every open tab already runs", () => {
  const jobs = readFileSync(path.join(SRC, "notify/jobsStore.js"), "utf8");
  assert.match(jobs, /import \{ noteServerNotice \} from "\.\/serverNotice\.js";/);
  assert.match(jobs, /if \(d && !d\.error\) noteServerNotice\(d\.notice\);/);
});
