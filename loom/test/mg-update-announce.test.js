import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setMaxListeners } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The release ANNOUNCEMENT (owner ruling 2026-09-04, reversing his own 2026-09-01 "no
   background tick anywhere"): the server checks roughly hourly and the app says so wherever
   the person is. Two properties are worth pinning on this side of the wire --

     1. ONE toast per new version, surviving a reload. The check is hourly and finds the same
        release every hour once one is out; a notice that re-fired every hour, or on every
        page load, is a notice you learn to ignore.
     2. It ANNOUNCES and cannot APPLY. The owner first read "full background" as the app
        updating itself and said "I don't want that" -- auto-apply is explicitly rejected, so
        the client half of the path is walked for any route into it.

   Driven for real, not by source-reading: updateStore and toastStore are both pure modules,
   so a fake localStorage is the only stand-in needed. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");
const storeURL = new URL("../../gallery/src/notify/updateStore.js", import.meta.url).href;

// A localStorage that behaves like the browser's for the two calls this module makes. Set
// BEFORE the module is imported: readSeen()/writeSeen() are guarded, and with no
// localStorage at all the dedupe would silently no-op and this file would pass on nothing.
const bag = new Map();
// `blocked` makes it throw on BOTH calls, which is what a storage-blocked browser really
// does (private mode, a locked-down profile, a third-party-cookie block on an embedded
// view) -- not "returns null".
let blocked = false;
globalThis.localStorage = {
  getItem: (k) => {
    if (blocked) throw new Error("SecurityError: storage is blocked");
    return bag.has(k) ? bag.get(k) : null;
  },
  setItem: (k, v) => {
    if (blocked) throw new Error("SecurityError: storage is blocked");
    bag.set(k, String(v));
  },
  removeItem: (k) => bag.delete(k),
};
// The store listens for `storage` -- the browser's own cross-tab notification. An
// EventTarget is exactly what window is for that purpose, and it lets a second "tab" be
// driven for real rather than asserted about.
globalThis.window = new EventTarget();
// One instance per test (see newTab below) means one listener per test on this target;
// node's default warning at ten is about leaks, and these are deliberate.
setMaxListeners(64, globalThis.window);
const fireStorage = (key, newValue) => {
  const ev = new Event("storage");
  ev.key = key;
  ev.newValue = newValue;
  globalThis.window.dispatchEvent(ev);
};

/* A FRESH MODULE INSTANCE PER TEST, because that is what a fresh TAB is -- and it is the
   only honest way to reset the in-memory half of the dedupe, which exists precisely so
   that nothing during a tab's life can clear it. `bag` (the cross-reload layer) is cleared
   alongside it. Two instances at once are two tabs, which is how the cross-tab tests are
   driven rather than asserted about. */
const SEEN_KEY = "mg_update_announced";
let tab = 0;
const newTab = () => import(storeURL + "?tab=" + (++tab));
let note, getUpdate, subscribe;
const toasts = await import("../../gallery/src/notify/toastStore.js");

const rel = (latest, extra) => ({ current: "3.0.0", latest, behind: true, ...(extra || {}) });

/* Toasts are counted as a DELTA from a mark taken at the top of each test, never as an
   absolute length: dismissal in the real store is two-phase (it plays a 340ms exit before
   unmounting), so a synchronous teardown cannot empty it and an absolute count would just be
   measuring the tests before it. */
let mark = 0;
const since = () => toasts.getToasts().slice(mark);

describe("the release announcement", () => {
  beforeEach(async () => {
    bag.clear();
    blocked = false;
    ({ note, getUpdate, subscribe } = await newTab());
    note(null);
    mark = toasts.getToasts().length;
  });

  test("a newly discovered release announces once, and says where to go", () => {
    assert.equal(note(rel("v9.9.9")), true);
    const shown = since();
    assert.equal(shown.length, 1);
    assert.match(shown[0].title, /^Moonglade v9\.9\.9 is ready$/);
    assert.match(shown[0].msg, /Control Panel/);
    // Sticky: the hourly check can land while nobody is at the keyboard, and it only ever
    // fires once for a given release.
    assert.equal(shown[0].sticky, true);
  });

  test("the same release found again is not news", () => {
    note(rel("v9.9.9"));
    for (let i = 0; i < 5; i++) note(rel("v9.9.9"));   // five more hourly polls
    assert.equal(since().length, 1);
  });

  test("a higher release is a new announcement", () => {
    note(rel("v9.9.9"));
    assert.equal(note(rel("v9.10.0")), true);
    assert.deepEqual(since().map((t) => t.title),
      ["Moonglade v9.9.9 is ready", "Moonglade v9.10.0 is ready"]);
  });

  test("a reload does not re-announce a version this browser was already told about", async () => {
    note(rel("v9.9.9"));
    assert.equal(since().length, 1);
    // A fresh module instance against the same storage -- what a page reload really is.
    const reloaded = await newTab();
    assert.equal(reloaded.note(rel("v9.9.9")), false);
    assert.equal(since().length, 1, "one toast per version, not per page load");
  });

  /* THE BLOCKED-STORAGE CASE, which is the one that stacked toasts forever. readSeen()
     swallowed the exception and answered "", so no version ever matched and the poll
     behind this store -- every 2.5 to 7 seconds -- announced the same release on every
     tick, sticky, with an × on each. The in-memory half exists so the promise holds
     without storage at all. */
  test("a browser with storage blocked still announces exactly once", () => {
    blocked = true;
    assert.equal(note(rel("v9.9.9")), true);
    for (let i = 0; i < 20; i++) note(rel("v9.9.9"));   // ~a minute of the jobs poll
    assert.equal(since().length, 1, "one toast per version, storage or no storage");
  });

  /* A ROLLBACK -- the owner pulling a bad release, so an hour later the check answers a
     LOWER version. Under plain string inequality that was both a second toast and a write
     of the lower version into the seen key, which then made the real newer release look
     already-announced when it came back. */
  test("a rollback is not news, and does not lower what this browser was told", () => {
    assert.equal(note(rel("v9.10.0")), true);
    assert.equal(since().length, 1);
    assert.equal(note(rel("v9.9.9")), false, "a lower version is not an announcement");
    assert.equal(since().length, 1);
    assert.equal(bag.get(SEEN_KEY), "v9.10.0", "the memory must not be poisoned downward");
    // ...and the release that really is newer still announces afterwards.
    assert.equal(note(rel("v9.11.0")), true);
    assert.equal(since().length, 2);
  });

  test("a version nobody can parse is not announced either", () => {
    assert.equal(note(rel("banana")), false);
    assert.equal(since().length, 0);
    assert.equal(bag.get(SEEN_KEY), undefined, "and nothing is written for it");
  });

  /* CROSS-TAB. Two tabs both polling can each read "not announced" and each toast; the
     browser's own `storage` event is how one tab learns what another just wrote. Driven
     with the event ALONE -- nothing is put in `bag` -- so it is the listener being tested
     and not the storage read that would otherwise cover for it. */
  test("a sibling tab's announcement is not repeated in this one", () => {
    fireStorage(SEEN_KEY, "v9.9.9");
    assert.equal(note(rel("v9.9.9")), false, "the other tab already said it");
    assert.equal(since().length, 0);
    // A stale sibling write must not lower the memory either.
    assert.equal(note(rel("v9.10.0")), true);
    fireStorage(SEEN_KEY, "v9.9.9");
    assert.equal(note(rel("v9.10.0")), false);
    assert.equal(since().length, 1);
  });

  test("an up-to-date answer clears the standing announcement", () => {
    note(rel("v9.9.9"));
    assert.equal(getUpdate().latest, "v9.9.9");
    note({ current: "9.9.9", latest: "v9.9.9", behind: false });
    assert.equal(getUpdate(), null, "the stamp must stop offering an update that is applied");
    // ...and an offline check (no answer at all) is not an announcement either
    note(null);
    assert.equal(getUpdate(), null);
  });

  test("subscribers see the announcement, so the Panel's version stamp can light up", () => {
    const seen = [];
    const stop = subscribe((u) => seen.push(u && u.latest));
    note(rel("v9.9.9"));
    stop();
    assert.deepEqual(seen, [null, "v9.9.9"]);
  });
});

describe("announce-only, on the client side too", () => {
  const read = (p) => readFileSync(path.join(SRC, p), "utf8").replace(/\r\n/g, "\n");

  test("the announcement path has no route into applying an update", () => {
    // Everything the background news touches on the way to a person: the store itself, and
    // the poll that hands it the payload. Neither may POST anything, least of all the apply.
    for (const file of ["notify/updateStore.js"]) {
      const src = read(file);
      assert.ok(!src.includes("/api/update/apply"), `${file} must not name the apply route`);
      assert.ok(!/\bapiPost\b/.test(src), `${file} must not POST anything`);
      assert.ok(!/\bfetch\s*\(/.test(src), `${file} must not call the network at all`);
    }
    const jobs = read("notify/jobsStore.js");
    assert.ok(jobs.includes("noteUpdate("), "the jobs poll must hand the announcement over");
    assert.ok(!jobs.includes("/api/update/apply"),
      "the poll that carries the announcement must not be able to apply one");
  });

  test("applying is still the Control Panel's own confirmed action", () => {
    // The one place /api/update/apply may be called from, unchanged by the background work.
    const hook = read("hooks/useControlPanel.js");
    assert.ok(hook.includes("/api/update/apply"));
    assert.ok(hook.includes("/api/update/check?fresh=1"),
      "a Panel open asks for a fresh answer past the server's 30-minute cache");
  });
});
