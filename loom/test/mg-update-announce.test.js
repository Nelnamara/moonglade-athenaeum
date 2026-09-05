import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
globalThis.localStorage = {
  getItem: (k) => (bag.has(k) ? bag.get(k) : null),
  setItem: (k, v) => bag.set(k, String(v)),
  removeItem: (k) => bag.delete(k),
};

const { note, getUpdate, subscribe } = await import(storeURL);
const toasts = await import("../../gallery/src/notify/toastStore.js");

const rel = (latest, extra) => ({ current: "3.0.0", latest, behind: true, ...(extra || {}) });

/* Toasts are counted as a DELTA from a mark taken at the top of each test, never as an
   absolute length: dismissal in the real store is two-phase (it plays a 340ms exit before
   unmounting), so a synchronous teardown cannot empty it and an absolute count would just be
   measuring the tests before it. */
let mark = 0;
const since = () => toasts.getToasts().slice(mark);

describe("the release announcement", () => {
  beforeEach(() => {
    bag.clear();
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
    const reloaded = await import(storeURL + "?reload=1");
    assert.equal(reloaded.note(rel("v9.9.9")), false);
    assert.equal(since().length, 1, "one toast per version, not per page load");
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
