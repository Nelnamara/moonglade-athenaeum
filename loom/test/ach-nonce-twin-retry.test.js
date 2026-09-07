import { test, describe, afterEach } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

/* THE STALE-PAGE RETRY IS FOR AN IDLE TAB, NOT FOR A DOUBLE-FIRED CLICK (2026-09-07).

   /api/ach-event spends a nonce per event, so ONE double-fired click is two posts carrying
   ONE nonce: the first spends it, the second comes back 403 "stale page". achNonce.js used
   to answer every 403 the same way -- fetch a fresh nonce, send the event again -- which
   put the swallowed half of the gesture BACK on the wire with a nonce the server would
   accept. The server's debounce is the only thing left standing between that retry and a
   double count, and it is 150ms wide: a refresh + retry round trip on LAN or phone wifi
   routinely outruns it, and then one press counts twice. The debounce and the retry were
   quietly cancelling each other out.

   The two 403s are told apart by the AGE of the nonce that was refused: an idle tab's is
   minutes old (past the server's 60s window), a twin's is milliseconds old. So the retry
   fires only when this page's nonce is missing or older than that window.

   Behavioral, not a source grep: the module is imported for real, with `fetch` and
   `Date.now` stubbed, and each case gets its OWN module instance (the ?case= query makes
   node's ESM loader hand back a fresh one) because the nonce it holds is module state. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE = pathToFileURL(
  path.resolve(__dirname, "../../gallery/src/notify/achNonce.js")).href;

const realDateNow = Date.now;
let clock = 1_700_000_000_000;

function reply(status, body) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: () => Promise.resolve(body),
  });
}

/* Load a fresh achNonce.js holding `bootNonce`, with a fetch that refuses every event as a
   stale page and hands out "fresh-nonce" from the top-up route. Returns the module plus the
   log of paths it called. */
async function load(caseName, bootNonce) {
  const calls = [];
  clock = 1_700_000_000_000;
  Date.now = () => clock;
  globalThis.window = { MG_BOOT: { ach_nonce: bootNonce } };
  globalThis.fetch = (p, init) => {
    calls.push({ path: p, body: init && init.body ? JSON.parse(init.body) : null });
    if (p === "/api/ach-nonce") return reply(200, { nonce: "fresh-nonce" });
    return reply(403, { error: "stale page — reload" });
  };
  const mod = await import(MODULE + "?case=" + caseName);
  return { mod, calls };
}

afterEach(() => {
  Date.now = realDateNow;
  delete globalThis.window;
  delete globalThis.fetch;
});

describe("sendAchEvent's 403 retry", () => {
  test("does NOT refresh-and-retry a 403 on a nonce it has only just been given", async () => {
    const { mod, calls } = await load("twin", "boot-nonce");
    clock += 40;                     // the twin of one double-fired click
    const res = await mod.sendAchEvent("narrator");
    assert.equal(res.error, "stale page — reload", "the refusal is still returned, unchanged");
    assert.deepEqual(calls.map((c) => c.path), ["/api/ach-event"],
      "retrying here re-sends the swallowed half of ONE click with a nonce the server will "
      + "accept -- one press counted twice on any round trip slower than the 150ms debounce");
  });

  test("does refresh-and-retry once when the nonce is older than the 60s window", async () => {
    const { mod, calls } = await load("idle", "boot-nonce");
    clock += 120000;                 // an idle tab, one late poke
    await mod.sendAchEvent("narrator");
    assert.deepEqual(calls.map((c) => c.path),
      ["/api/ach-event", "/api/ach-nonce", "/api/ach-event"],
      "an idle tab's nonce is genuinely expired; without the top-up the tab loses the "
      + "beacon for good");
    assert.equal(calls[2].body.nonce, "fresh-nonce", "the retry must carry the NEW nonce");
  });

  test("does refresh-and-retry when the page has no nonce at all", async () => {
    const { mod, calls } = await load("none", "");
    clock += 40;                     // young by the clock, but there is nothing to lose
    await mod.sendAchEvent("docs");
    assert.deepEqual(calls.map((c) => c.path),
      ["/api/ach-event", "/api/ach-nonce", "/api/ach-event"]);
  });

  test("an adopted next_nonce restarts the clock, so the next event is not treated as idle",
    async () => {
      const { mod, calls } = await load("adopt", "boot-nonce");
      clock += 120000;
      globalThis.fetch = (p, init) => {
        calls.push({ path: p, body: init && init.body ? JSON.parse(init.body) : null });
        if (p === "/api/ach-nonce") return reply(200, { nonce: "fresh-nonce" });
        return reply(200, { ok: true, pokes: 1, next_nonce: "next-nonce" });
      };
      await mod.sendAchEvent("narrator");            // accepted; adopts next-nonce at `clock`
      assert.equal(mod.take(), "next-nonce");
      const before = calls.length;
      clock += 40;
      globalThis.fetch = (p, init) => {
        calls.push({ path: p, body: init && init.body ? JSON.parse(init.body) : null });
        return reply(403, { error: "stale page — reload" });
      };
      await mod.sendAchEvent("narrator");            // ...its twin, 40ms later
      assert.deepEqual(calls.slice(before).map((c) => c.path), ["/api/ach-event"],
        "the age is measured from when the nonce was adopted, not from page load");
    });
});
