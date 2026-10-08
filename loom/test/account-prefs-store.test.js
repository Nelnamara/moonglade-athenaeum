import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  createPrefsStore, applyOps, prefKeyProblem, readPref,
} from "../../gallery/src/hooks/accountPrefsStore.js";

/* THE PER-ACCOUNT PREFERENCES STORE (2026-09-28). The store half is importless for exactly
   the reason swrStore.js is: the behaviour worth pinning is the STORE's -- one load shared
   by every subscriber, an optimistic write, and a rollback that removes exactly the failed
   change -- and each is a plain assertion against a fake transport. The server half
   (GET/POST /api/account/prefs) is pinned by dev/tests/test_account_prefs.py. */

// A transport whose answers the test releases by hand, so ordering is under test control.
function manualTransport() {
  const calls = [];
  const next = (kind, body) => new Promise((resolve) => calls.push({ kind, body, resolve }));
  return {
    calls,
    load: () => next("load"),
    save: (patch) => next("save", patch),
  };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

async function settle(t, i, answer) {
  await tick();
  assert.ok(t.calls[i], "expected request #" + i + " to have been sent");
  t.calls[i].resolve(answer);
  await tick();
}

describe("prefKeyProblem -- the same key rule the server enforces", () => {
  test("lowercase dotted names pass", () => {
    for (const k of ["a", "unleash", "guide.library", "seen.whatsnew", "seen.feat.12",
                     "gen.defaults.sdxl-1", "seen.feat.great_library", "a".repeat(64)]) {
      assert.equal(prefKeyProblem(k), "", k);
    }
  });
  test("everything else is refused with a sentence", () => {
    for (const k of ["", "Guide", "1a", "_a", "a..b", "a.", ".a", "a b", "a/b", "a:b",
                     "a".repeat(65), null, 7]) {
      assert.ok(prefKeyProblem(k).length > 0, String(k));
    }
  });
});

describe("applyOps / readPref", () => {
  test("ops apply in order and never mutate the base", () => {
    const base = Object.freeze({ a: 1, b: 2 });
    const out = applyOps(base, [
      { set: { c: 3 }, unset: ["a"] },
      { set: { a: 9 }, unset: [] },
    ]);
    assert.deepEqual(out, { a: 9, b: 2, c: 3 });
    assert.deepEqual(base, { a: 1, b: 2 });
  });
  test("readPref: a present key (null included) wins, an absent one gets the fallback", () => {
    assert.equal(readPref({ a: null }, "a", "fb"), null);
    assert.equal(readPref({}, "a", "fb"), "fb");
    assert.equal(readPref({ a: 0 }, "a", 5), 0);
    assert.equal(readPref({}, "toString", "fb"), "fb", "inherited names are not stored keys");
  });
});

describe("one load for the whole page", () => {
  test("many ensureLoaded calls share one request; every subscriber hears it", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    const heard = [0, 0];
    s.subscribe(() => heard[0]++);
    s.subscribe(() => heard[1]++);
    const a = s.ensureLoaded();
    const b = s.ensureLoaded();
    s.ensureLoaded();
    assert.equal(s.getSnapshot().status, "loading");
    await settle(t, 0, { prefs: { "seen.whatsnew": "3.14.0" }, csrf: "tok" });
    assert.equal(await a, true);
    assert.equal(await b, true);
    assert.equal(t.calls.length, 1, "a second component must not cause a second GET");
    assert.equal(s.getSnapshot().status, "ready");
    assert.equal(s.get("seen.whatsnew", ""), "3.14.0");
    assert.ok(heard[0] > 0 && heard[0] === heard[1]);
    // loaded is loaded: a later mount does not refetch
    assert.equal(await s.ensureLoaded(), true);
    assert.equal(t.calls.length, 1);
  });

  test("a failed load reports its error and the next ensureLoaded tries again", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    const first = s.ensureLoaded();
    await settle(t, 0, { error: "network error: offline" });
    assert.equal(await first, false);
    assert.equal(s.getSnapshot().status, "error");
    assert.equal(s.getSnapshot().error, "network error: offline");
    assert.equal(s.get("a", "fb"), "fb");
    const again = s.ensureLoaded();
    await settle(t, 1, { prefs: { a: 1 } });
    assert.equal(await again, true);
    assert.equal(s.get("a"), 1);
  });

  test("a transport that throws is an error answer, not an unhandled rejection", async () => {
    const s = createPrefsStore({ load: async () => { throw new Error("boom"); }, save: async () => ({}) });
    assert.equal(await s.ensureLoaded(), false);
    assert.match(s.getSnapshot().error, /boom/);
  });
});

describe("optimistic writes", () => {
  test("set shows at once, then the server's document becomes the base", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    await settle(t, 0, { prefs: { keep: 1 } });
    const w = s.set("guide.library", { step: 2 });
    assert.deepEqual(s.getSnapshot().prefs, { keep: 1, "guide.library": { step: 2 } },
      "the change must be visible before the server answers");
    await tick();
    assert.deepEqual(t.calls[1].body, { set: { "guide.library": { step: 2 } }, unset: [] });
    await settle(t, 1, { prefs: { keep: 1, "guide.library": { step: 2 }, other: "server" } });
    assert.deepEqual(await w, { ok: true });
    assert.deepEqual(s.getSnapshot().prefs,
      { keep: 1, "guide.library": { step: 2 }, other: "server" });
  });

  test("a failed set rolls back to exactly what was there", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    await settle(t, 0, { prefs: { unleash: false } });
    const w = s.set("unleash", true);
    assert.equal(s.get("unleash"), true);
    await settle(t, 1, { error: "Your session expired. Reload the page and try again.", http_status: 400 });
    assert.deepEqual(await w, { error: "Your session expired. Reload the page and try again." });
    assert.deepEqual(s.getSnapshot().prefs, { unleash: false });
  });

  test("a failed unset puts the key back", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    await settle(t, 0, { prefs: { "goal.pinned": "g1" } });
    const w = s.unset("goal.pinned");
    assert.equal(s.get("goal.pinned", "none"), "none");
    await tick();
    assert.deepEqual(t.calls[1].body, { set: {}, unset: ["goal.pinned"] });
    await settle(t, 1, { error: "503 Service Unavailable" });
    assert.ok((await w).error);
    assert.equal(s.get("goal.pinned"), "g1");
  });

  test("rolling back one write never undoes a LATER write to the same key", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    await settle(t, 0, { prefs: { k: "server" } });
    const w1 = s.set("k", "first");
    const w2 = s.set("k", "second");
    assert.equal(s.get("k"), "second");
    await settle(t, 1, { error: "refused" });          // the first write fails...
    assert.equal(s.get("k"), "second", "...but the pending second write is still applied");
    await settle(t, 2, { prefs: { k: "second" } });
    assert.deepEqual(await w1, { error: "refused" });
    assert.deepEqual(await w2, { ok: true });
    assert.equal(s.get("k"), "second");
  });

  test("writes go out one at a time, in call order", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    s.set("a", 1);
    s.set("b", 2);
    await tick();
    assert.equal(t.calls.length, 1, "nothing may be sent while the load is outstanding");
    await settle(t, 0, { prefs: {} });
    assert.equal(t.calls.length, 2, "only the first write is in flight");
    await settle(t, 1, { prefs: { a: 1 } });
    assert.deepEqual(s.getSnapshot().prefs, { a: 1, b: 2 }, "b is still pending, still shown");
    await settle(t, 2, { prefs: { a: 1, b: 2 } });
    assert.deepEqual(t.calls.slice(1).map((c) => c.body.set), [{ a: 1 }, { b: 2 }]);
  });

  test("a write before any load still loads first, and its answer is the document", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    const w = s.set("a", 1);
    await tick();
    assert.equal(t.calls[0].kind, "load", "the load (and its token) must precede the first write");
    await settle(t, 0, { error: "network error: offline" });
    await settle(t, 1, { prefs: { a: 1, b: 2 } });
    assert.deepEqual(await w, { ok: true });
    assert.equal(s.getSnapshot().status, "ready");
    assert.deepEqual(s.getSnapshot().prefs, { a: 1, b: 2 });
  });

  test("the optimistic value is the JSON the server will store", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    await settle(t, 0, { prefs: {} });
    s.set("a", { when: new Date(0), list: [1, NaN] });
    assert.deepEqual(s.get("a"), { when: "1970-01-01T00:00:00.000Z", list: [1, null] });
  });
});

describe("refusals that never reach the server", () => {
  test("a bad key or a non-JSON value is refused without a request or a flicker", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    s.ensureLoaded();
    await settle(t, 0, { prefs: { a: 1 } });
    let heard = 0;
    s.subscribe(() => heard++);
    const cyclic = {};
    cyclic.self = cyclic;
    for (const [k, v] of [["Bad.Key", 1], ["a", undefined], ["a", () => 1], ["a", 10n], ["a", cyclic]]) {
      const d = await s.set(k, v);
      assert.ok(d.error, String(k));
    }
    assert.ok((await s.unset("")).error);
    await tick();
    assert.equal(t.calls.length, 1, "nothing was sent");
    assert.equal(heard, 0, "nothing was published");
    assert.deepEqual(s.getSnapshot().prefs, { a: 1 });
  });
});

describe("the snapshot contract useSyncExternalStore depends on", () => {
  test("the snapshot identity is stable until something changes", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    const a = s.getSnapshot();
    assert.equal(s.getSnapshot(), a);
    s.ensureLoaded();
    const b = s.getSnapshot();
    assert.notEqual(b, a);
    assert.equal(s.getSnapshot(), b);
  });

  test("an unsubscribed listener hears nothing more", async () => {
    const t = manualTransport();
    const s = createPrefsStore(t);
    let heard = 0;
    const off = s.subscribe(() => heard++);
    off();
    s.ensureLoaded();
    await settle(t, 0, { prefs: {} });
    assert.equal(heard, 0);
  });
});

describe("the React half stays thin", () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const read = (f) => readFileSync(path.join(here, "..", "..", "gallery", "src", "hooks", f), "utf8");
  const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  test("the store imports nothing (so this file can test it with no DOM or React)", () => {
    assert.doesNotMatch(codeOnly(read("accountPrefsStore.js")), /^\s*import\s/m);
  });

  test("the hook talks to the server only through api.js, and sends the csrf field", () => {
    const hook = codeOnly(read("useAccountPrefs.js"));
    assert.match(hook, /from "\.\.\/api\.js"/);
    assert.doesNotMatch(hook, /\bfetch\(/);
    assert.match(hook, /apiPost\(PATH, \{ \.\.\.patch, csrf:/);
    assert.match(hook, /const PATH = "\/api\/account\/prefs"/);
  });
});
