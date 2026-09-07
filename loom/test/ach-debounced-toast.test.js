import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* A DEBOUNCED POKE HOLDS THE LINE; IT NEVER REWINDS THE TOAST (2026-09-07).

   /api/ach-event debounces the same (session, event) inside its window: the second half of
   a double-fired click is accepted, hands back a nonce, and counts NOTHING. That reply used
   to be `{ok, debounced, next_nonce}` and no more, so pokeNarrator's `res.pokes || 1` fell
   back to 1 and re-showed POKES[0] -- "The narrator ignores you." -- on top of an
   escalation that had already reached line 3 or 4. The swallowed half of one gesture
   visibly UNDID the feedback loop the toast exists to deliver.

   Both halves were fixed: the route now sends the current `pokes`/`snapped` (read, not
   bumped) on a debounced reply, and pokeNarrator returns on `res.debounced` BEFORE any
   toast -- one gesture, one toast, and a second tap inside the window is silent rather than
   a rewind. tests/test_telemetry.py owns the server half. This is the client half.

   There is no jsdom/React harness in this runner, so rather than regex-matching the source
   (which would pin the shape of the fix, not its behavior) this lifts pokeNarrator's own
   text out of useFolio.js and RUNS it against stub collaborators. If the extraction ever
   fails it fails loudly here, which is the correct outcome for a guard that has lost sight
   of the thing it guards. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FILE = path.resolve(__dirname, "../../gallery/src/hooks/useFolio.js");
// Same device, same reason, as ach-nonce-callers.test.js next door: the comments around
// this function talk ABOUT toasts and pokes, and would confuse the extraction below.
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

function pokeNarratorSource() {
  const code = codeOnly(readFileSync(FILE, "utf8").replace(/\r\n/g, "\n"));
  const start = code.indexOf("function pokeNarrator()");
  assert.ok(start >= 0, "useFolio.js no longer declares `function pokeNarrator()` -- if the "
    + "narrator beacon moved or was renamed, move this guard with it");
  let depth = 0, end = -1;
  for (let i = code.indexOf("{", start); i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}" && --depth === 0) { end = i + 1; break; }
  }
  assert.ok(end > start, "could not find the end of pokeNarrator()");
  return code.slice(start, end);
}

const POKES = ["ignores you", "eyebrow", "DESCRIBING", "eye twitches", "FINE"];

/* Run the real pokeNarrator against one canned /api/ach-event reply. Returns what it did:
   which toasts it showed, and whether it armed Triggered. */
async function poked(res) {
  const seen = { toasts: [], triggered: 0, refetched: 0 };
  const prevWindow = globalThis.window;
  globalThis.window = { Toast: { show: (o) => seen.toasts.push(o) } };
  try {
    const build = new Function(
      "sendAchEvent", "mountedRef", "POKES", "setTriggered", "apiGet", "put", "setData",
      pokeNarratorSource() + "\nreturn pokeNarrator;");
    build(
      () => Promise.resolve(res),
      { current: true },
      POKES,
      () => { seen.triggered++; },
      () => { seen.refetched++; return Promise.resolve({}); },
      () => {},
      () => {})();
    await new Promise((r) => setTimeout(r, 0));   // flush the .then chain
  } finally {
    globalThis.window = prevWindow;
  }
  return seen;
}

describe("pokeNarrator and the debounced reply", () => {
  test("a debounced reply shows no toast at all", async () => {
    const seen = await poked({ ok: true, debounced: true, pokes: 4, snapped: false });
    assert.deepEqual(seen.toasts, [],
      "the swallowed half of a double-fire must be silent -- toasting here shows POKES[0] "
      + "(or a repeat) on top of an escalation that has already passed it");
  });

  test("a debounced reply at the snap point is silent too, counter or not", async () => {
    const seen = await poked({ ok: true, debounced: true, pokes: 5, snapped: true });
    assert.deepEqual(seen.toasts, [],
      "debounced means this tap counted nothing; the accepted poke that reached 5 is the "
      + "one that gets the moment, and it already had it");
  });

  test("an accepted reply still shows the line its count earned", async () => {
    const seen = await poked({ ok: true, pokes: 3, snapped: false });
    assert.equal(seen.toasts.length, 1, "an accepted poke still toasts -- this is the "
      + "feedback loop that makes five pokes feel earned");
    assert.equal(seen.toasts[0].title, POKES[2],
      "the toast must follow the server's count, not restart at the first line");
    assert.equal(seen.triggered, 0);
  });

  test("an accepted reply that snaps still arms Triggered", async () => {
    const seen = await poked({ ok: true, pokes: 5, snapped: true });
    assert.equal(seen.toasts[0].title, POKES[4]);
    assert.equal(seen.triggered, 1, "the early return for `debounced` must not swallow the "
      + "snap on an ACCEPTED poke");
    assert.equal(seen.refetched, 1, "the snap still refetches /api/achievements so the "
      + "unblanked roast is there to scramble to");
  });

  test("a refusal is still a silent no-op", async () => {
    const seen = await poked({ error: "stale page — reload" });
    assert.deepEqual(seen.toasts, []);
    assert.equal(seen.triggered, 0);
  });
});
