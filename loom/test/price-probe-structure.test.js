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
// ONE PRICE TRANSPORT (2026-08-23). The request came out of the hook: the probe still owns the
// debounce, the sequence guard, the verdict and the teardown abort, but the POST -- and the
// {response} vs {failed} distinction the spend gate reads -- lives in one module the Loom's own
// nine price sites now ride too. So "the one /api/price caller" moves here.
const TRANSPORT = "gen/priceRequest.js";
const LOOM = path.resolve(__dirname, "../master-storyboard.jsx");

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

describe("the price transport is the one /api/price caller under gallery/src", () => {
  test("exactly one file asks /api/price, and it is gen/priceRequest.js", () => {
    // Re-anchored 2026-08-23: the needle was the literal `fetch("/api/price"`, which stopped
    // covering the whole tree the moment api.js became the one request module -- a stray probe
    // would now be written apiPost("/api/price", ...) and sail straight past a fetch-only
    // needle. Both spellings are the same offence, so both are the needle.
    const ASKS = /(?:fetch|apiGet|apiPost|apiUpload)\(\s*["']\/api\/price["']/;
    const callers = files.filter((f) => ASKS.test(read(f))).map(rel).sort();
    assert.deepEqual(callers, [TRANSPORT],
      "a second inline /api/price call is a second copy of the debounce, the seq guard, the abort "
      + "and -- the part that actually costs money -- the payload-identity gate. Call usePriceProbe "
      + "(or, outside React, requestPrice) instead. Found: " + JSON.stringify(callers));
  });

  test("the probe gets its request from the transport, and keeps no fetch of its own", () => {
    // The hook is still the one PROBE (debounce + seq guard + verdict); what it no longer owns
    // is the wire. If it grew its own fetch back, the {response}-vs-{failed} rule would have two
    // homes again and the Loom's copy would be free to drift from the gallery's.
    const hook = read(files.find((x) => rel(x) === PROBE));
    assert.match(hook, /import\s*\{\s*requestPrice\s*\}\s*from\s+["'][^"']*priceRequest\.js["']/,
      PROBE + " must import requestPrice from the one transport");
    assert.match(hook, /requestPrice\(p, \{ signal: c \? c\.signal : undefined \}\)/,
      "the probe must hand its OWN AbortController's signal to the transport -- stop() aborting "
      + "a request it can no longer reach is the #27 leak coming back");
    assert.doesNotMatch(hook.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, ""), /\bfetch\(/,
      PROBE + " must not fetch for itself any more");
  });

  test("the transport is the only place the two roads are told apart", () => {
    const t = read(files.find((x) => rel(x) === TRANSPORT));
    assert.match(t, /return \{ response: await r\.json\(\) \};/,
      "any parsed body -- an HTTP-200 {error} included -- must come back as a RESPONSE");
    assert.match(t, /catch \{[\s\S]{0,200}return \{ failed: true \};/,
      "a transport failure, an abort or a timeout must come back as {failed}, never as a body");
    assert.equal((t.match(/\bfetch\(/g) || []).length, 1,
      "one POST per call: this is a paid road and a re-issued price request is how a lost "
      + "response turns into a second, paid submission");
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
describe("a badge that remounts is re-primed with force", () => {
  // The image <CostBadge> mounts and unmounts with its tab (desktop dock and mobile Create
  // alike), so it comes back idle while the probe's verdict may still be settled for the very
  // same payload. An un-forced refresh() short-circuits on "nothing priced changed" and leaves
  // Generate LIVE beside a blank badge -- a spend control with no quote on screen. The hook's
  // own contract names the remount as one of the two cases `force` exists for; pin the callers.
  test("GenerateDrawer's Image-tab entry prime passes force", () => {
    const src = read(path.join(SRC, "components/GenerateDrawer.jsx"));
    assert.match(src, /if \(open && tab === "image"\) g\.refreshPrice\(\{ force: true \}\);/);
  });
  test("CreateMobile's Image and Edit entry primes pass force", () => {
    const src = read(path.join(SRC, "components/CreateMobile.jsx"));
    assert.match(src, /if \(cmode === "image"\) refreshPrice\(\{ force: true \}\);/);
    assert.match(src, /if \(cmode === "edit" && editSub === "edit"\) edit\.refreshPrice\(\{ force: true \}\);/);
  });
});

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

  test("the fire step clears pendingTimer BEFORE any early bail, and the request stays bounded", () => {
    // (a) an early return (no badge mounted) that ran before the verdict write left
    // {pendingTimer:true} forever, so the gate never opened again; (b) an unbounded fetch that
    // hung left the control disabled forever on a muted "Checking cost…" -- fail-silent-closed.
    const write = hook.indexOf("put(fired())");
    const bail = hook.indexOf("if (!badge) return;");
    assert.ok(write >= 0 && bail >= 0 && write < bail, "pendingTimer must be cleared before the no-badge bail");
    assert.match(hook, /AbortController/, "the price request must be abortable from here -- stop() owns it");
    assert.match(hook, /signal: c \? c\.signal : undefined/, "the request must carry the abort signal");
    // Re-anchored 2026-08-23: the 25s bound moved with the request. It is asserted where it now
    // lives, and asserted to be UNCONDITIONAL -- the probe supplies its own signal, so a timeout
    // that only applied on the no-signal path would hand the hang bug straight back to the one
    // caller that most needs the bound. (loom/test/price-request.test.js drives that behaviour.)
    const transport = read(files.find((x) => rel(x) === TRANSPORT));
    assert.match(transport, /timeoutMs = PRICE_FETCH_TIMEOUT_MS/,
      "the transport must default to the shared timeout constant, not a private number");
    assert.match(transport, /setTimeout\(\(\) => ctrl\.abort\(\), timeoutMs\)/);
    assert.doesNotMatch(transport, /if \(!signal\)[\s\S]{0,80}setTimeout/,
      "the timeout must not be conditional on the caller having supplied no signal");
  });

  test("every exit settles for the payload it judged, under the sequence guard", () => {
    // A FAILED check settles too: the badge's red "couldn't verify — may spend" IS this payload's
    // verdict, whereas a verdict for a DIFFERENT payload is exactly what canSubmit refuses.
    assert.match(hook, /const key = priceKey\(p, skip\);/,
      "the key must be taken off the SAME payload that is sent");
    // Re-anchored 2026-08-23: there used to be TWO guards because the answer arrived in .then
    // and the failure in .catch. requestPrice never rejects -- it RESOLVES onto one road or the
    // other -- so both paths now join at a single guard, which must therefore stand before
    // either of them touches the badge. Same property, one copy of it.
    const guards = hook.match(/if \(mine !== seq\.current \|\| !costRef\.current\) return;/g) || [];
    assert.equal(guards.length, 1, "one join point, one seq guard");
    const guardAt = hook.indexOf("if (mine !== seq.current || !costRef.current) return;");
    assert.ok(guardAt >= 0 && guardAt < hook.indexOf("costRef.current.setPrice(null);")
      && guardAt < hook.indexOf("costRef.current.setPrice(d);"),
      "the seq guard must precede BOTH the failed write and the answer write -- a stale answer "
      + "writing a price for a payload that stopped being true is exactly what it exists to stop");
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

/* ---- the Loom's nine sites ---------------------------------------------------------------
   master-storyboard.jsx carried NINE hand-rolled
   `fetch("/api/price", {method:"POST", ...}).then(r => r.json()).catch(...)` blocks -- LoomV2's
   priceInto and its Fixer preview, LoomMobile's Image / Edit / Reference / Fixer previews, and
   useGenerationPipeline's priceShot, confirmSpend and genFix. Nine copies of one transport is
   nine private answers to "what does a dropped socket mean here", on the app's most expensive
   surface. They ride one function now, over the same gen/priceRequest.js the gallery's probe
   uses. This is a STRUCTURAL property and structural properties rot back -- the cheapest way to
   "just price this too" is a tenth inline fetch -- so it is walked, not listed. */
describe("the Loom asks for a price in exactly one place", () => {
  const loom = readFileSync(LOOM, "utf8").replace(/\r\n/g, "\n");
  // A "no code may do X" assertion has to read CODE only: the comments explaining what was
  // removed name the route, and would otherwise trip the guard they document.
  const loomCode = loom.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  test("no /api/price URL survives in the Loom's code -- the route belongs to the transport", () => {
    assert.doesNotMatch(loomCode, /["']\/api\/price["']/,
      "a hand-written /api/price in the Loom is a tenth copy of the transport, and it would be "
      + "free to disagree with the gallery about whether a failed check may imply free");
  });

  test("requestPrice is called from exactly ONE function, and it is priceBody", () => {
    // Walk: find every call and name its enclosing declaration, rather than checking a list.
    const hosts = [];
    const re = /requestPrice\(/g;
    let m;
    while ((m = re.exec(loomCode)) !== null) {
      const decls = [...loomCode.slice(0, m.index)
        .matchAll(/(?:^|\n)\s*(?:const|let|var|function)\s+(\w+)/g)];
      hosts.push(decls.length ? decls[decls.length - 1][1] : "(module top level)");
    }
    assert.deepEqual(hosts, ["priceBody"],
      "every price the Loom asks for must go through its one call site. Found callers in: "
      + JSON.stringify(hosts));
  });

  test("priceShot is the shot-shaped face of that one call, not a second one", () => {
    assert.match(loomCode, /const priceShot = \(entry\) => priceBody\(shotPayload\(entry\)\);/,
      "priceShot must delegate to priceBody -- batchGenerate, generateShot and the cost-to-finish "
      + "pill all reach the wire through it");
  });

  test("the collapse actually happened -- the old sites are real callers now", () => {
    // Guards against this suite passing vacuously if the nine were deleted rather than migrated.
    // The floor is deliberately below the real count; the count itself is not written down here.
    const callers = (loomCode.match(/\bpriceBody\(/g) || []).length;
    assert.ok(callers >= 8,
      "expected the Loom's price sites to have collapsed onto priceBody, found " + callers);
  });

  test("each caller keeps its OWN staleness contract -- only the transport is shared", () => {
    // DECISIONS: "Cost-to-finish pill deliberately does NOT share the batch's pre-confirm
    // pricing" -- a browsing estimate may be slightly stale, the number shown at the moment of
    // spending may not. Unifying the transport must not quietly unify those two, so pin both.
    assert.match(loomCode, /const \[priceCache, setPriceCache\] = useState\(\{\}\);/,
      "the cost-to-finish pill keeps its own warm per-shot cache");
    assert.match(loomCode, /priceDebounceRef\.current = setTimeout\(\(\) => notDone\.forEach\(\(e\) => ensurePriced\(e\)\), PRICE_DEBOUNCE_MS\);/,
      "the pill keeps its own board debounce");
    assert.match(loomCode, /const prices = await Promise\.all\(todo\.map\(\(e\) => priceShot\(e\)\)\);/,
      "batchGenerate must keep pricing every shot FRESH right before the confirm -- never off "
      + "the pill's cache");
    const batchAt = loomCode.indexOf("const prices = await Promise.all(todo.map((e) => priceShot(e)));");
    const confirmAt = loomCode.indexOf("if (!window.confirm(msg)) { setBatching(false); return; }");
    assert.ok(batchAt >= 0 && confirmAt > batchAt,
      "the batch's fresh pricing pass must run BEFORE its confirm, not after");
    assert.doesNotMatch(loomCode, /priceCache\[[^\]]*\][\s\S]{0,120}tallyPricesDetailed/,
      "the batch must never tally the pill's cached prices");
  });
});
