import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* ONE PROBE BEHIND EVERY COST LINE (2026-08-22). Six front-end hosts each hand-rolled the same
   debounce -> POST /api/price -> sequence guard -> push into <CostBadge> loop, and only ONE of
   them (the video drawer) carried the payload-identity spend gate written after issue #15 -- a
   settled FREE for a 5s payload let Go submit a 15s one. Five paid surfaces ran without it.

   The loop is now one module (gallery/src/gen/priceProbeCore.js + gen/usePriceProbe.js) and the
   hosts are thin callers. That is a STRUCTURAL property, and structural properties rot back:
   the cheapest way to "just add a price check here" is another inline fetch. So this walks the
   real tree rather than checking a hardcoded list -- a SEVENTH copy in a file nobody thought of
   fails it exactly like a regression in one of the six. There is no jsdom/React harness in this
   runner, so source-level guards are the established pattern for files in this position. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const PROBE = "gen/usePriceProbe.js";

// The six hosts. Named here only to assert they ARE callers -- the "one fetch" rule below is
// derived from the tree, never from this list.
const HOSTS = [
  "gen/useGenerate.js",
  "gen/useEditGenerate.js",
  "components/EditTab.jsx",
  "components/FixTab.jsx",
  "components/UpscalePanel.jsx",
  "components/VideoDrawer.jsx",
];

function walk(dir, out = []) {
  readdirSync(dir).forEach((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(js|jsx)$/.test(name)) out.push(full);
  });
  return out;
}
const files = walk(SRC);
const rel = (f) => path.relative(SRC, f).split(path.sep).join("/");
const read = (f) => readFileSync(f, "utf8").replace(/\r\n/g, "\n");

describe("the price probe is the one /api/price caller under gallery/src", () => {
  test("exactly one file fetches /api/price, and it is gen/usePriceProbe.js", () => {
    const callers = files.filter((f) => read(f).includes('fetch("/api/price"')).map(rel).sort();
    assert.deepEqual(callers, [PROBE],
      "a second inline /api/price fetch is a second copy of the debounce, the seq guard, the abort "
      + "and -- the part that actually costs money -- the payload-identity gate. Call usePriceProbe "
      + "instead. Found: " + JSON.stringify(callers));
  });

  test("no host writes the CostBadge checking handshake by hand", () => {
    // setChecking() is the "blank the number FIRST, synchronously" half of the badge contract:
    // an old quote next to new settings is the one thing worse than no quote. The probe owns it,
    // paired with dropping the verdict identity in the same breath -- a host calling it alone
    // would blank the badge while leaving Go live on a stale verdict.
    const offenders = files
      .filter((f) => rel(f) !== PROBE && rel(f) !== "components/CostBadge.jsx")
      .filter((f) => /setChecking\(/.test(read(f)))
      .map(rel);
    assert.deepEqual(offenders, [],
      "setChecking() belongs to the probe (CostBadge itself declares it). Found: " + JSON.stringify(offenders));
  });
});

describe("every cost line rides the probe", () => {
  HOSTS.forEach((h) => {
    test(h + " imports usePriceProbe", () => {
      const f = files.find((x) => rel(x) === h);
      assert.ok(f, "expected " + h + " to exist");
      assert.match(read(f), /import\s+usePriceProbe\s+from\s+["'][^"']*usePriceProbe\.js["']/,
        h + " must get its price check from the shared probe, not its own loop");
    });
  });

  test("no host keeps a private debounce constant for pricing", () => {
    // PRICE_DEBOUNCE_MS lives in the core; six independent literal 250s is how a timing rule
    // drifts. (Other 250s in these files -- animation, polling -- are not setTimeout(fireCost).)
    HOSTS.forEach((h) => {
      const src = read(files.find((x) => rel(x) === h));
      assert.doesNotMatch(src, /setTimeout\(\s*(fireCost|firePrice|costNow|doPrice)\b/,
        h + " must not schedule its own price fire");
    });
  });
});

/* ---- the probe's own wiring (no React harness in this runner) ----------------------------
   These pinned VideoDrawer's debCost/costNow before the loop was shared; they follow the
   mechanism. Each one is a review finding from 2026-08-16 that cost, or nearly cost, money. */
describe("usePriceProbe's host half of the CostBadge contract", () => {
  const hook = read(files.find((x) => rel(x) === PROBE));
  // refresh() and the fire step both talk to the badge, so the ordering guards below are scoped
  // to the one function each is about.
  const refreshBody = hook.slice(hook.indexOf("const refresh = useCallback("),
    hook.indexOf("/* enabled:"));
  assert.ok(refreshBody.length > 100, "expected to find refresh() in usePriceProbe.js");

  test("refresh() short-circuits BEFORE it blanks the badge, and `force` bypasses it", () => {
    // prompt/negative are outside priceKey ("never prices") yet their handlers refresh, so every
    // typing pause used to blank the badge, disable the submit control and re-POST /api/price for
    // a byte-identical payload. `force` exists for the ONE case where the payload is identical but
    // the verdict is stale anyway -- right after a submit debited the tickets.
    const sc = refreshBody.indexOf("shouldShortCircuit(");
    const check = refreshBody.indexOf("badge.setChecking()");
    assert.ok(sc >= 0 && check >= 0, "refresh must consult shouldShortCircuit and setChecking");
    assert.ok(sc < check, "the short-circuit must come BEFORE setChecking()");
    assert.match(refreshBody, /const force = !!\(opts && opts\.force\);/);
  });

  test("refresh() blanks the badge SYNCHRONOUSLY, before scheduling -- and drops the verdict identity", () => {
    const check = refreshBody.indexOf("badge.setChecking()");
    const sched = refreshBody.indexOf("setTimeout(fire, PRICE_DEBOUNCE_MS)");
    assert.ok(check >= 0 && sched > check, "setChecking() must run BEFORE the setTimeout -- 250ms of stale FREE was the bug");
    const between = refreshBody.slice(check, sched);
    assert.match(between, /put\(scheduled\(\)\)/, "refresh must un-settle the verdict and mark it pending");
    assert.match(between, /seq\.current\+\+/, "refresh must invalidate any answer already in flight");
  });

  test("the fire step clears pendingTimer BEFORE any early bail, and bounds the fetch with a timeout", () => {
    // (a) an early return (no badge mounted) that ran before the verdict write left
    // {pendingTimer:true} forever, so the gate never opened again; (b) an unbounded fetch that
    // hung left the control disabled forever on a muted "Checking cost…" -- fail-silent-closed.
    const write = hook.indexOf("put(fired())");
    const bail = hook.indexOf("if (!badge) return;");
    assert.ok(write >= 0 && bail >= 0 && write < bail, "pendingTimer must be cleared before the no-badge bail");
    assert.match(hook, /AbortController/, "the price fetch must be abortable");
    assert.match(hook, /setTimeout\(\(\) => c\.abort\(\), PRICE_FETCH_TIMEOUT_MS\)/);
    assert.match(hook, /signal: c \? c\.signal : undefined/, "the fetch must carry the abort signal");
  });

  test("every exit settles for the payload it judged, under the sequence guard", () => {
    // A FAILED check settles too: the badge's red "couldn't verify — may spend" IS this payload's
    // verdict, whereas a verdict for a DIFFERENT payload is exactly what canSubmit refuses.
    assert.match(hook, /const key = priceKey\(p, skip\);/,
      "the key must be taken off the SAME payload that is sent");
    const guards = hook.match(/if \(mine !== seq\.current \|\| !costRef\.current\) return;/g) || [];
    assert.equal(guards.length, 2, "both the answer and the failure path must be seq-guarded");
    assert.match(hook, /costRef\.current\.setPrice\(d\);\n\s*setResponse\(d\);\n\s*put\(settledFor\(key\)\);/);
    assert.match(hook, /costRef\.current\.setPrice\(null\);\n\s*setResponse\(null\);\n\s*put\(settledFor\(key\)\);/,
      "a failed check settles too -- fail-closed-but-live");
    assert.match(hook, /put\(settledFor\(key\)\);\n\s*return;/, "an idle build settles as well");
  });

  test("disabling (or unmounting) clears the timer AND aborts the request in flight", () => {
    // #27: leaving a tab used to leave the armed timer, so one stray /api/price fired ~250ms
    // after the tab was gone. Coming back forces a re-price -- the badge remounted idle.
    assert.match(hook, /const stop = useCallback\(\(\) => \{[\s\S]{0,400}clearTimeout\(timer\.current\)[\s\S]{0,400}abort\(\)/);
    assert.match(hook, /if \(!enabled\) \{ stop\(\); return; \}\n\s*refresh\(\{ force: true \}\);/,
      "enabled false stops everything; enabled true forces a fresh price");
    assert.match(hook, /useEffect\(\(\) => stop, \[stop\]\);/, "unmount runs the same teardown");
  });

});
