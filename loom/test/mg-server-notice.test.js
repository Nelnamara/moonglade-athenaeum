import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The server's once-per-start notice (3.20): things outside the app that still name its old
   files (a scheduled task, Claude's Moonglade tools, a shortcut), with one button, Fix them.
   gallery/src/notify/serverNotice.js decides when to show it and runs the button; the
   existing corner toast says it.

     1. ONCE PER SERVER START. The same key on every poll, a reload or a second tab: one toast.
        A new key (the server started again, something still unfixed): one more.
     2. NOTHING TO SAY IS NOTHING SHOWN. null, a dropped poll, a notice with no key.
     3. A BROWSER THAT BLOCKS STORAGE still says it once, not on every poll.
     4. IT RIDES THE POLL every tab already runs (jobsStore.js), not a loop of its own.
     5. THE BUTTON is the toast's one `action`: it posts the session's token to
        /api/outside/fix and says what the server answered -- fixed, or why not.

   Driven for real: serverNotice.js, toastStore.js and api.js are pure modules, so a fake
   localStorage and a fake fetch are the only stand-ins needed. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");

const bag = new Map();
let blocked = false;
globalThis.localStorage = {
  getItem: (k) => { if (blocked) throw new Error("SecurityError"); return bag.has(k) ? bag.get(k) : null; },
  setItem: (k, v) => { if (blocked) throw new Error("SecurityError"); bag.set(k, String(v)); },
  removeItem: (k) => bag.delete(k),
};

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

function stubFetch(body) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    return { ok: true, status: 200, statusText: "OK", headers: { get: () => null },
             json: async () => body };
  };
  return calls;
}

const toastURL = new URL("../../gallery/src/notify/toastStore.js", import.meta.url).href;
const noticeURL = new URL("../../gallery/src/notify/serverNotice.js", import.meta.url).href;
const toasts = await import(toastURL);

let n = 0;
async function freshNotice() {
  // a fresh module per test (its memory copy is module state); the toast store is shared
  return import(noticeURL + "?t=" + (++n));
}

const OUTSIDE = { key: "a1", title: "Some things outside Moonglade still use its old file names.",
                  msg: "The scheduled task “Moonglade sync”. Fix them points them at the new names.",
                  fix: { label: "Fix them", csrf: "tok" } };

function shown() { return toasts.getToasts().filter((t) => !t.out); }
function clearToasts() { toasts.getToasts().forEach((t) => toasts.dismiss(t.id)); }

beforeEach(() => { bag.clear(); blocked = false; clearToasts(); });

test("the same server start says it once, however often the poll brings it", async () => {
  const { noteServerNotice } = await freshNotice();
  const before = shown().length;
  assert.equal(noteServerNotice(OUTSIDE), true);
  assert.equal(noteServerNotice(OUTSIDE), false);
  assert.equal(noteServerNotice({ ...OUTSIDE }), false);
  const added = shown().slice(before);
  assert.equal(added.length, 1);
  assert.equal(added[0].title, OUTSIDE.title);
  assert.equal(added[0].msg, OUTSIDE.msg);
  assert.equal(added[0].sticky, true);
  assert.equal(added[0].kind, "");
});

test("a reload or a second tab does not say it again; the next server start does", async () => {
  (await freshNotice()).noteServerNotice(OUTSIDE);
  const tab2 = await freshNotice();
  assert.equal(tab2.noteServerNotice(OUTSIDE), false);
  assert.equal(tab2.noteServerNotice({ ...OUTSIDE, key: "b2" }), true);
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
  assert.equal(noteServerNotice(OUTSIDE), true);
  assert.equal(noteServerNotice(OUTSIDE), false);
});

test("the toast's one button is the server's Fix them; a notice without one has none", async () => {
  const { noteServerNotice } = await freshNotice();
  const before = shown().length;
  noteServerNotice(OUTSIDE);
  const t = shown().slice(before)[0];
  assert.equal(t.action.label, "Fix them");
  noteServerNotice({ key: "c3", title: "Just words." });
  assert.equal(shown().slice(before)[1].action, null);
});

test("the button posts the session's token to the fix route and says what was done", async () => {
  const { runFix } = await freshNotice();
  const calls = stubFetch({ ok: true, kind: "ok", title: "Fixed.",
                            msg: "The scheduled task “Moonglade sync” now uses the new names." });
  const before = shown().length;
  await runFix(OUTSIDE.fix);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/api/outside/fix");
  assert.equal(calls[0][1].method, "POST");
  assert.deepEqual(JSON.parse(calls[0][1].body), { csrf: "tok" });
  const said = shown().slice(before);
  assert.equal(said.length, 1);
  assert.equal(said[0].kind, "ok");
  assert.equal(said[0].title, "Fixed.");
  assert.equal(said[0].sticky, false);
});

test("what could not be fixed stays on screen, with why", async () => {
  const { runFix } = await freshNotice();
  stubFetch({ ok: true, kind: "err", title: "Couldn't fix them.",
              msg: "Couldn't fix the scheduled task “X”: it runs with a saved Windows password." });
  const before = shown().length;
  await runFix(OUTSIDE.fix);
  const t = shown().slice(before)[0];
  assert.equal(t.kind, "err");
  assert.equal(t.sticky, true);
  assert.match(t.msg, /saved Windows password/);
});

test("a refusal is said as it came", async () => {
  const { runFix } = await freshNotice();
  stubFetch({ error: "Your session expired. Reload the page and try again." });
  const before = shown().length;
  await runFix(OUTSIDE.fix);
  const t = shown().slice(before)[0];
  assert.equal(t.kind, "err");
  assert.equal(t.msg, "Your session expired. Reload the page and try again.");
});

test("it rides the jobs poll every open tab already runs", () => {
  const jobs = readFileSync(path.join(SRC, "notify/jobsStore.js"), "utf8");
  assert.match(jobs, /import \{ noteServerNotice \} from "\.\/serverNotice\.js";/);
  assert.match(jobs, /if \(d && !d\.error\) noteServerNotice\(d\.notice\);/);
});
