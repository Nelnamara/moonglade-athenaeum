import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The release ANNOUNCEMENT (owner ruling 2026-09-04, reversing his own 2026-09-01 "no
   background tick anywhere"; reworked 2026-09-07, "update should be noticed anywhere").

   Until 2026-09-07 this was ONE sticky corner toast per version, deduped per browser
   through a localStorage key -- so it could be dismissed, or missed while nobody was at the
   keyboard, and then the Control Panel was the only place left to learn a release existed.
   It is now a STANDING banner (gallery/src/notify/bannerStore.js): it goes up when a
   release newer than the running build is found and stays up until the update is actually
   applied. The properties worth pinning moved with it --

     1. IT STANDS. The hourly check finds the same release every hour; every one of those
        ticks must leave the strip exactly where it is, not re-raise or re-emit it.
     2. IT IS NEWS OR IT IS NOTHING. Equal to, or lower than, the version this process is
        really running is not an announcement, and takes the strip down.
     3. IT ANNOUNCES AND CANNOT APPLY. The owner first read "full background" as the app
        updating itself and said "I don't want that" -- auto-apply is explicitly rejected, so
        the client half of the path is walked for any route into it.

   Driven for real, not by source-reading: updateStore and bannerStore are both pure
   modules, so a fake localStorage is the only stand-in needed. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");
const storeURL = new URL("../../gallery/src/notify/updateStore.js", import.meta.url).href;
const bannerURL = new URL("../../gallery/src/notify/bannerStore.js", import.meta.url).href;

// A localStorage that behaves like the browser's for the calls these modules make. Set
// BEFORE the modules are imported: the receipt's reads are guarded, and with no
// localStorage at all the armed-receipt case would silently no-op.
const bag = new Map();
// `blocked` makes it throw on every call, which is what a storage-blocked browser really
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
/* The banner is compared against the version THIS PROCESS is running, which the browser
   learns from the served shell's boot blob. A plain object is exactly what window is for
   that purpose here, and it lets the running build be moved between tests rather than
   asserted about. */
globalThis.window = { MG_BOOT: { build_stamp: "v3.0.0 · a1b2c3d" } };

const RECEIPT_KEY = "mg_update_receipt";

/* ONE bannerStore, and a fresh updateStore per test. updateStore imports "./bannerStore.js"
   by its own plain specifier, so a query-string copy of the banner would be a DIFFERENT
   module that nothing writes to -- the un-queried instance is the one the code under test
   really talks to, and setBanner(null) is what resets it between tests (its state is
   in-memory by design: there is nothing persisted left to clear). A fresh updateStore under
   a new query is what a page reload really is. */
const { getBanner, isCollapsed, collapse, expand, setBanner, subscribe: subscribeBanner } =
  await import(bannerURL);
let tab = 0;
let note, getUpdate, subscribe, armReceipt;
const newTab = () => import(storeURL + "?tab=" + (++tab));

const rel = (latest, extra) => ({ current: "3.0.0", latest, behind: true, ...(extra || {}) });

describe("the release announcement", () => {
  beforeEach(async () => {
    bag.clear();
    blocked = false;
    globalThis.window.MG_BOOT = { build_stamp: "v3.0.0 · a1b2c3d" };
    setBanner(null);
    ({ note, getUpdate, subscribe, armReceipt } = await newTab());
    note(null);
  });

  test("a newly discovered release raises the banner, naming the version", () => {
    assert.equal(note(rel("v9.9.9")), true);
    assert.deepEqual(getBanner(), { version: "v9.9.9", notes: "" });
  });

  test("the release notes link rides along when the server sends one", () => {
    note(rel("v9.9.9", { notes_url: "https://example.invalid/r/9.9.9" }));
    assert.equal(getBanner().notes, "https://example.invalid/r/9.9.9");
  });

  /* THE WHOLE POINT OF THE REWORK. The old toast fired once per version and was gone; this
     strip is still there an hour later, and twenty polls later, because a person who was
     not at the keyboard when it went up must still find it when they come back. */
  test("the same release found again leaves the banner standing, untouched", () => {
    note(rel("v9.9.9"));
    const first = getBanner();
    const seen = [];
    const stop = subscribeBanner((b) => seen.push(b && b.version));
    for (let i = 0; i < 20; i++) note(rel("v9.9.9"));   // ~a minute of the jobs poll
    stop();
    assert.equal(getBanner(), first, "the strip is not re-raised, it simply stays");
    assert.deepEqual(seen, ["v9.9.9"], "and subscribers are not woken on every tick");
  });

  test("a higher release replaces it", () => {
    note(rel("v9.9.9"));
    assert.equal(note(rel("v9.10.0")), true);
    assert.equal(getBanner().version, "v9.10.0");
  });

  test("a reload finds the banner again -- there is no per-browser 'already told you'", async () => {
    note(rel("v9.9.9"));
    // A fresh store against the same storage, and a strip that starts empty because it was
    // only ever in memory -- which is exactly what a page reload is.
    const reloaded = await newTab();
    setBanner(null);
    assert.equal(reloaded.note(rel("v9.9.9")), true);
    assert.equal(getBanner().version, "v9.9.9",
      "the news stands until the update is applied, not until the tab is closed");
  });

  test("a browser with storage blocked shows the banner just the same", () => {
    blocked = true;
    assert.equal(note(rel("v9.9.9")), true);
    assert.equal(getBanner().version, "v9.9.9");
  });

  /* EQUAL OR LOWER IS NOT NEWS, measured against the version this process is really
     running. Equal is an up-to-date answer the server still marked `behind`; lower is a
     rollback -- the owner pulling a bad release -- which must not raise a strip offering to
     "update" a build that is already past it. */
  test("a release equal to the running build never raises it", () => {
    globalThis.window.MG_BOOT = { build_stamp: "v9.9.9 · a1b2c3d" };
    assert.equal(note(rel("v9.9.9")), false);
    assert.equal(getBanner(), null);
  });

  test("a release older than the running build never raises it, and takes it down", () => {
    globalThis.window.MG_BOOT = { build_stamp: "v9.10.0 · a1b2c3d" };
    assert.equal(note(rel("v9.11.0")), true);
    assert.equal(getBanner().version, "v9.11.0");
    assert.equal(note(rel("v9.9.9")), false, "a rollback is not an announcement");
    assert.equal(getBanner(), null);
  });

  test("with no boot stamp at all, the server's own `current` is what it is measured against", () => {
    delete globalThis.window.MG_BOOT;
    assert.equal(note({ current: "9.9.9", latest: "v9.9.9", behind: true }), false);
    assert.equal(getBanner(), null);
    assert.equal(note({ current: "3.0.0", latest: "v9.9.9", behind: true }), true);
    assert.equal(getBanner().version, "v9.9.9");
  });

  test("a version nobody can parse is not announced either", () => {
    assert.equal(note(rel("banana")), false);
    assert.equal(getBanner(), null);
  });

  /* AN APPLY ALREADY UNDER WAY. armReceipt() has written down the version this browser is
     on its way to; the poll behind this store keeps running for the second or two before
     the reload, and a strip offering 3.10 over a modal installing 3.10 is just noise. */
  test("an armed receipt suppresses the banner", () => {
    note(rel("v9.9.9"));
    assert.equal(getBanner().version, "v9.9.9");
    assert.equal(armReceipt("v9.9.9"), true);
    assert.equal(bag.get(RECEIPT_KEY), "v9.9.9");
    assert.equal(note(rel("v9.9.9")), false, "the apply is already happening");
    assert.equal(getBanner(), null);
  });

  test("an up-to-date answer clears both the announcement and the banner", () => {
    note(rel("v9.9.9"));
    assert.equal(getUpdate().latest, "v9.9.9");
    note({ current: "9.9.9", latest: "v9.9.9", behind: false });
    assert.equal(getUpdate(), null, "the stamp must stop offering an update that is applied");
    assert.equal(getBanner(), null);
    // ...and an offline check (no answer at all) is not an announcement either
    note(null);
    assert.equal(getUpdate(), null);
    assert.equal(getBanner(), null);
  });

  test("subscribers see the announcement, so the Panel's version stamp can light up", () => {
    const seen = [];
    const stop = subscribe((u) => seen.push(u && u.latest));
    note(rel("v9.9.9"));
    stop();
    assert.deepEqual(seen, [null, "v9.9.9"]);
  });
});

/* "NOT NOW" FOLDS, IT DOES NOT DISMISS (owner, 2026-09-07: no dismiss that makes it
   vanish). The pill is this tab's own, never written down, and a poll finding the same
   release again must not pop it back open a few seconds after it was folded. */
describe("the banner's pill", () => {
  beforeEach(async () => {
    bag.clear();
    blocked = false;
    globalThis.window.MG_BOOT = { build_stamp: "v3.0.0 · a1b2c3d" };
    setBanner(null);
    ({ note } = await newTab());
  });

  test("Not now folds the strip and leaves the release standing", () => {
    note(rel("v9.9.9"));
    assert.equal(isCollapsed(), false);
    collapse();
    assert.equal(isCollapsed(), true);
    assert.equal(getBanner().version, "v9.9.9", "folded, not dismissed");
    expand();
    assert.equal(isCollapsed(), false);
  });

  test("the hourly tick does not unfold it", () => {
    note(rel("v9.9.9"));
    collapse();
    for (let i = 0; i < 10; i++) note(rel("v9.9.9"));
    assert.equal(isCollapsed(), true);
  });

  test("...but a different release is news again", () => {
    note(rel("v9.9.9"));
    collapse();
    note(rel("v9.10.0"));
    assert.equal(isCollapsed(), false);
    assert.equal(getBanner().version, "v9.10.0");
  });

  test("nothing about the pill is written down", () => {
    note(rel("v9.9.9"));
    collapse();
    assert.equal(bag.size, 0, "a per-browser 'hide the news' is what this rework removed");
  });
});

describe("announce-only, on the client side too", () => {
  const read = (p) => readFileSync(path.join(SRC, p), "utf8").replace(/\r\n/g, "\n");

  test("the announcement path has no route into applying an update", () => {
    // Everything the background news touches on the way to a person: the store itself, the
    // banner it now sets, the banner's own surface, and the poll that hands the payload
    // over. None may POST anything, least of all the apply.
    for (const file of ["notify/updateStore.js", "notify/bannerStore.js", "notify/BannerHost.jsx"]) {
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
