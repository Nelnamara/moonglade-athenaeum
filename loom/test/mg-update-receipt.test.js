import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setMaxListeners } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE UPDATE'S RECEIPT (owner, 2026-09-05: "just a restart with no endpoint tells the user
   that nothing happened unless they go BACK to the panel").

   An apply ends in a reload, which takes the modal, its three ticks and its meter with it;
   what comes back is the gallery, looking exactly as it did before. So the apply writes down
   the version it is going for and the next boot pays it out -- but ONLY against the version
   that boot is really running. The three properties worth pinning are the three ways this
   could lie:

     1. MATCH -- the promised version is the running one: say so, once.
     2. MISMATCH -- a failed or rolled-back update left the old build running: say nothing,
        and tear the record up anyway so it cannot pay out later against some future release
        that happens to match.
     3. ONCE ONLY -- a second reload is not a second update.

   Driven for real against the module, not by reading its source: updateStore and toastStore
   are pure, so a fake localStorage is the only stand-in needed. Each fresh module instance
   against the same storage is what a page reload actually is. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");
const storeURL = new URL("../../gallery/src/notify/updateStore.js", import.meta.url).href;

const RECEIPT_KEY = "mg_update_receipt";

const bag = new Map();
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
  removeItem: (k) => {
    if (blocked) throw new Error("SecurityError: storage is blocked");
    bag.delete(k);
  },
};
// The store attaches a `storage` listener at import; an EventTarget is what window is for
// that purpose. One instance per boot means one listener per boot on this target.
globalThis.window = new EventTarget();
setMaxListeners(64, globalThis.window);

let n = 0;
const boot = () => import(storeURL + "?boot=" + (++n));
const toasts = await import("../../gallery/src/notify/toastStore.js");

/* Toasts are counted as a DELTA from a mark taken at the top of each test: dismissal is
   two-phase (a 340ms exit before unmounting), so an absolute length would just be measuring
   the tests before it. */
let mark = 0;
const since = () => toasts.getToasts().slice(mark);

describe("the update's receipt", () => {
  beforeEach(() => {
    bag.clear();
    blocked = false;
    mark = toasts.getToasts().length;
  });

  test("the promised version is the running one: one note, in plain words", async () => {
    const applying = await boot();
    assert.equal(applying.armReceipt("v3.8.0"), true);
    assert.equal(bag.get(RECEIPT_KEY), "v3.8.0");

    // ...the page reloads, and the new process says what it is running.
    const after = await boot();
    assert.equal(after.claimReceipt("v3.8.0 · a1b2c3d"), true);
    const shown = since();
    assert.equal(shown.length, 1);
    assert.equal(shown[0].title, "Updated to v3.8.0");
    // Dismissible, and it waits to be dismissed -- the reload is a bad moment to blink a
    // 5-second toast at somebody.
    assert.equal(shown[0].sticky, true);
    assert.equal(bag.has(RECEIPT_KEY), false, "the record is spent");
  });

  test("a failed update says nothing, and cannot fire later", async () => {
    const applying = await boot();
    applying.armReceipt("v3.8.0");

    // The restart came back on the OLD build: the update did not land.
    const after = await boot();
    assert.equal(after.claimReceipt("v3.7.2 · a1b2c3d"), false);
    assert.equal(since().length, 0, "nothing landed, so nothing is claimed");
    assert.equal(bag.has(RECEIPT_KEY), false,
      "the record is torn up all the same -- it must not pay out against a later release");

    // ...and the release it was waiting for, arriving later by any other route, is silent.
    const later = await boot();
    assert.equal(later.claimReceipt("v3.8.0"), false);
    assert.equal(since().length, 0);
  });

  test("a second reload is not a second update", async () => {
    (await boot()).armReceipt("v3.8.0");
    assert.equal((await boot()).claimReceipt("v3.8.0"), true);
    assert.equal(since().length, 1);
    for (let i = 0; i < 3; i++) {
      assert.equal((await boot()).claimReceipt("v3.8.0"), false);
    }
    assert.equal(since().length, 1, "one note per update, not one per page load");
  });

  test("with nothing promised, a boot says nothing at all", async () => {
    assert.equal((await boot()).claimReceipt("v3.8.0 · a1b2c3d"), false);
    assert.equal(since().length, 0);
  });

  test("the v is cosmetic on both sides -- 3.8.0 and v3.8.0 are the same release", async () => {
    (await boot()).armReceipt("3.8.0");
    assert.equal((await boot()).claimReceipt("v3.8.0 · a1b2c3d"), true);
    assert.equal(since()[0].title, "Updated to v3.8.0");
  });

  test("a boot that cannot tell what it is running keeps the record for one that can", async () => {
    (await boot()).armReceipt("v3.8.0");
    assert.equal((await boot()).claimReceipt(""), false, "no stamp is not a mismatch");
    assert.equal(since().length, 0);
    assert.equal(bag.get(RECEIPT_KEY), "v3.8.0", "still owed");
    assert.equal((await boot()).claimReceipt("v3.8.0 · a1b2c3d"), true);
    assert.equal(since().length, 1);
  });

  test("a version nobody can parse is never written down", async () => {
    const applying = await boot();
    assert.equal(applying.armReceipt("banana"), false);
    assert.equal(applying.armReceipt(""), false);
    assert.equal(bag.has(RECEIPT_KEY), false, "an unpayable record is litter in the next boot's way");
  });

  test("a browser with storage blocked simply has no receipt to pay", async () => {
    blocked = true;
    const applying = await boot();
    assert.equal(applying.armReceipt("v3.8.0"), false);
    assert.equal((await boot()).claimReceipt("v3.8.0"), false);
    assert.equal(since().length, 0);
  });

  test("the build stamp's sha is not part of the version", async () => {
    const { versionFromStamp } = await boot();
    assert.equal(versionFromStamp("v3.8.0 · a1b2c3d"), "v3.8.0");
    assert.equal(versionFromStamp("v3.8.0"), "v3.8.0");
    assert.equal(versionFromStamp(""), "");
    assert.equal(versionFromStamp(null), "");
  });
});

describe("the receipt is wired to the boot that follows an apply", () => {
  const read = (p) => readFileSync(path.join(SRC, p), "utf8").replace(/\r\n/g, "\n");

  test("the apply arms it before the reload, and the boot claims it", () => {
    const hook = read("hooks/useControlPanel.js");
    const armed = hook.indexOf("armUpdateReceipt(");
    const reload = hook.indexOf("window.location.reload()");
    assert.ok(armed > 0, "the successful apply must write the receipt");
    assert.ok(reload > armed, "and must write it BEFORE the page goes");

    const installer = read("notify/index.jsx");
    assert.ok(installer.includes("claimReceipt("),
      "the boot path that starts the announcement must also pay the receipt");
    assert.ok(installer.includes("build_stamp"),
      "and must judge it against the version this process is really running");
  });

  test("the receipt still cannot apply anything", () => {
    // Same rule the announcement lives under: this module says things, it never installs.
    const src = read("notify/updateStore.js");
    assert.ok(!src.includes("/api/update/apply"));
    assert.ok(!/\bapiPost\b/.test(src));
    assert.ok(!/\bfetch\s*\(/.test(src));
  });
});
