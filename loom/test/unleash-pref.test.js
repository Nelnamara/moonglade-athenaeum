import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  UNLEASH_KEY, LEGACY_KEY, isUnleashed, migrationPlan, syncLegacyUnleash,
} from "../../gallery/src/folio/unleashPref.js";
import { createPrefsStore } from "../../gallery/src/hooks/accountPrefsStore.js";

/* THE UNLEASH SWITCH, ACCOUNT-WIDE (Session L, decision 1). The switch moved from this
   browser's localStorage to the account's preferences; an old browser value carries over
   once, and only into an account that has not answered. The glitch reveal and the server's
   gate are untouched (their own tests pin them) -- what moved is where the boolean is read
   from, so that is what is pinned here. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");

/* A fake browser storage. */
function storage(initial) {
  const m = new Map(Object.entries(initial || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    removeItem: (k) => { m.delete(k); },
    has: (k) => m.has(k),
  };
}

/* A real prefs store on a fake server: `doc` is what the account already has. */
function accountStore(doc, { failSave = false } = {}) {
  const saves = [];
  let server = { ...doc };
  const store = createPrefsStore({
    load: async () => ({ prefs: { ...server } }),
    save: async (patch) => {
      saves.push(patch);
      if (failSave) return { error: "nope" };
      server = { ...server, ...patch.set };
      for (const k of patch.unset) delete server[k];
      return { prefs: { ...server } };
    },
  });
  return { store, saves, doc: () => server };
}

describe("the key and the reading", () => {
  test("the account key is `unleash`, the same word the old browser key used", () => {
    assert.equal(UNLEASH_KEY, "unleash");
    assert.equal(LEGACY_KEY, "unleash");
  });

  test("only a real true is on", () => {
    assert.equal(isUnleashed({ unleash: true }), true);
    for (const off of [null, undefined, {}, { unleash: false }, { unleash: 1 }, { unleash: "1" },
      { unleash: "true" }, { unleash: null }]) {
      assert.equal(isUnleashed(off), false, JSON.stringify(off));
    }
  });
});

describe("the one-time migration plan", () => {
  const P = (o) => migrationPlan({ status: "ready", stored: undefined, legacy: null, ...o });

  test("nothing is decided before the account has answered, and nothing with no account", () => {
    assert.deepEqual(P({ status: "loading", legacy: "1" }), { wait: true, write: false, clear: false });
    assert.deepEqual(P({ status: "idle", legacy: "1" }), { wait: true, write: false, clear: false });
    assert.deepEqual(P({ status: "error", legacy: "1" }), { wait: false, write: false, clear: false });
  });

  test("an old '1' moves to an account that has no value, and the old key goes", () => {
    assert.deepEqual(P({ legacy: "1" }), { wait: false, write: true, clear: true });
  });

  test("an account that already answered is never overwritten, whichever way it answered", () => {
    for (const stored of [true, false, null, 0]) {
      assert.deepEqual(P({ legacy: "1", stored }), { wait: false, write: false, clear: true });
    }
  });

  test("an old value that is not '1' has nothing to carry and is just dropped", () => {
    for (const legacy of ["0", "", "true", "yes"]) {
      assert.deepEqual(P({ legacy }), { wait: false, write: false, clear: true });
    }
  });

  test("no old value, nothing to do", () => {
    assert.deepEqual(P({}), { wait: false, write: false, clear: false });
  });
});

describe("the runner", () => {
  test("an old '1' is written to the account once, then the key is cleared", async () => {
    const st = storage({ unleash: "1" });
    const a = accountStore({});
    const plan = await syncLegacyUnleash(a.store, st);
    assert.equal(plan.write, true);
    assert.equal(a.doc().unleash, true);
    assert.equal(st.has("unleash"), false);
    assert.equal(a.saves.length, 1);
    // a second run has nothing left to do and writes nothing
    await syncLegacyUnleash(a.store, st);
    assert.equal(a.saves.length, 1);
  });

  test("an account that has its own value keeps it; the old key is still dropped", async () => {
    const st = storage({ unleash: "1" });
    const a = accountStore({ unleash: false });
    await syncLegacyUnleash(a.store, st);
    assert.equal(a.doc().unleash, false, "the account's own answer wins");
    assert.equal(a.saves.length, 0);
    assert.equal(st.has("unleash"), false);
  });

  test("a failed write keeps the old key so the next load tries again", async () => {
    const st = storage({ unleash: "1" });
    const a = accountStore({}, { failSave: true });
    await syncLegacyUnleash(a.store, st);
    assert.equal(st.has("unleash"), true, "not cleared until the account really holds it");
    assert.equal(a.store.get("unleash", undefined), undefined, "and the optimistic write rolled back");
  });

  test("with no old value it neither loads the store nor writes", async () => {
    const a = accountStore({});
    await syncLegacyUnleash(a.store, storage({}));
    await syncLegacyUnleash(a.store, null);
    assert.equal(a.store.getSnapshot().status, "idle");
    assert.equal(a.saves.length, 0);
  });

  test("blocked storage is not an error", async () => {
    const boom = { getItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
    const plan = await syncLegacyUnleash(accountStore({}).store, boom);
    assert.equal(plan.write, false);
  });

  test("a store that cannot load writes nothing and clears nothing", async () => {
    const st = storage({ unleash: "1" });
    const store = createPrefsStore({ load: async () => ({ error: "down" }), save: async () => ({}) });
    const plan = await syncLegacyUnleash(store, st);
    assert.deepEqual(plan, { wait: false, write: false, clear: false });
    assert.equal(st.has("unleash"), true);
  });
});

describe("where the boolean is read from now", () => {
  const walk = (d) => readdirSync(d).flatMap((n) => {
    const p = path.join(d, n);
    return statSync(p).isDirectory() ? walk(p) : (/\.jsx?$/.test(n) ? [p] : []);
  });
  const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  test("nothing under gallery/src touches the old browser key except the one migration", () => {
    const readers = walk(SRC)
      .filter((f) => /localStorage[^;\n]*["']unleash["']|["']unleash["'][^;\n]*localStorage/.test(
        codeOnly(readFileSync(f, "utf8"))))
      .map((f) => path.relative(SRC, f).replace(/\\/g, "/"));
    assert.deepEqual(readers, [], "a second reader of the per-browser key is the drift this move ended");
    assert.match(src("folio/unleashPref.js"), /LEGACY_KEY = "unleash"/);
    assert.match(src("folio/unleashPref.js"), /storage\.getItem\(LEGACY_KEY\)/);
  });

  test("the celebration engine asks a registered source, and the installer registers the account's", () => {
    const ach = src("notify/ach.js");
    assert.match(ach, /export function registerUnleashSource\(fn\)/);
    assert.match(ach, /function unleashed\(\) \{\s*try \{ return !!_unleashSource\(\); \} catch \{ return false; \}/);
    const idx = src("notify/index.jsx");
    assert.match(idx, /ach\.registerUnleashSource\(\(\) => isUnleashed\(\{ \[UNLEASH_KEY\]: prefs\.get\(UNLEASH_KEY, undefined\) \}\)\)/);
    assert.match(idx, /prefs\.ensureLoaded\(\);/);
    assert.match(idx, /syncLegacyUnleash\(prefs, storage\);/);
  });

  test("the Folio reads the switch from the account store and writes it back there", () => {
    const hook = src("hooks/useFolio.js");
    assert.match(hook, /const unleashed = isUnleashed\(prefs\.prefs\);/);
    assert.match(hook, /function toggleUnleash\(\) \{\s*const next = !unleashed;\s*prefs\.set\(UNLEASH_KEY, next\);/);
    assert.doesNotMatch(hook, /useState\(false\);\s*\n\s*const \[reveal/, "no local unleashed state remains");
    assert.doesNotMatch(hook, /setUnleashed/);
  });

  test("the pill is still the Folio header's, behind `triggered`, and not in the Control Panel", () => {
    const desk = src("components/FolioOverlay.jsx");
    assert.match(desk, /\{triggered && \(\s*<div className="mgfo-unleash"/);
    const phone = src("components/FolioMobile.jsx");
    assert.match(phone, /\{triggered && \(\s*<div className="fm-unleash"/);
    for (const f of ["components/ControlPanelOverlay.jsx", "components/ControlMobile.jsx",
      "hooks/useControlPanel.js"]) {
      assert.doesNotMatch(src(f), /unleash/i, f + " must not carry the switch: that would spoil it");
    }
  });
});
