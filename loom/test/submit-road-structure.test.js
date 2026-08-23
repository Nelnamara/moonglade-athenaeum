import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* ONE SUBMIT ROAD, ONE POLL LOOP (2026-08-23). Sibling of price-probe-structure.test.js, and
   the same argument: these are STRUCTURAL properties, and structural properties rot back,
   because the cheapest way to "just submit from here" is another inline fetch.

   What went wrong the first time is the reason the guard is worth its weight. The video drawer
   POSTed /api/loom/generate itself, polled /api/task-status itself off a hand-copied copy of
   the Loom's tier thresholds, and did NOT register its own job -- it dispatched an mg-submit
   DOM event and trusted whichever shell had mounted it to call Jobs.register. App.jsx did;
   AppMobile.jsx never had that listener. So a ~210k-credit video started from the phone existed
   nowhere the app could see it: not in /api/jobs, not in the Activity tray, not in the server's
   orphan sweep. Nothing was broken in any one file -- the gap was in which file was expected to
   do it, which is exactly the kind of thing only a tree-level check catches.

   There is no jsdom/React harness in this runner, so source-level guards are the established
   pattern for files in this position (see price-probe-structure.test.js's own note). */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const POLLER = "notify/jobs.js";
const ROAD = "gen/submitTask.js";

// Every route submitTask is allowed to POST. Named here so ADDING one is a deliberate edit to
// this list rather than a silent widening -- each is a route that spends real credits.
const SPEND_ROUTES = [
  "/api/edit",
  "/api/enhance",
  "/api/fix",
  "/api/generate",
  "/api/loom/generate",
  "/api/scene",
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
const fileNamed = (r) => {
  const f = files.find((x) => rel(x) === r);
  assert.ok(f, "expected " + r + " to exist");
  return read(f);
};
// A "this file must not call X" assertion has to read CODE only: the comment explaining why the
// call was removed names it, and would otherwise trip the very guard it documents. (Same device,
// same reason, as loom-image-job-register.test.js's own codeOnly.)
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("web surfaces never add a second poll loop", () => {
  test("exactly one file under gallery/src fetches /api/task-status, and it is notify/jobs.js", () => {
    const callers = files.filter((f) => read(f).includes('fetch("/api/task-status')).map(rel).sort();
    assert.deepEqual(callers, [POLLER],
      "/api/task-status is the route that writes the authoritative terminal job event. A second "
      + "loop against it duplicates traffic and creates a competing source of truth about whether "
      + "a paid task finished. Completion comes from Jobs.track. Found: " + JSON.stringify(callers));
  });

  test("the poller takes its cadence from the shared tier table, not its own constants", () => {
    const poller = fileNamed(POLLER);
    assert.match(poller, /import \{ cadenceFor \} from "\.\/pollCadence\.js";/,
      "the tier table must be the pure module, so it is node-testable and cannot be copied per host");
    assert.doesNotMatch(poller, /20 \* 60 \* 1000|90 \* 60 \* 1000|6 \* 60 \* 60 \* 1000/,
      "a threshold literal has reappeared inside the poller -- that is the start of the second "
      + "copy the tier table was extracted to prevent");
  });

  test("the tier table itself stays pure -- no DOM, no fetch, no React", () => {
    const table = fileNamed("notify/pollCadence.js");
    assert.doesNotMatch(table, /\bfetch\(|\bdocument\b|\bwindow\b|from "react"/,
      "pollCadence.js must stay importable by a plain node test");
  });
});

describe("every spend rides submitTask", () => {
  test("no file under gallery/src POSTs /api/loom/generate any more", () => {
    const callers = files.filter((f) => read(f).includes('fetch("/api/loom/generate"')).map(rel);
    assert.deepEqual(callers, [],
      "the video route is a spend route: it must go through gen/submitTask.js, which owns the "
      + "no-retry rule, the HTTP-200-body-keyed error read, the `adjusted` disclosure and the "
      + "Jobs.track registration. Found: " + JSON.stringify(callers));
  });

  test("VideoDrawer.jsx imports submitTask", () => {
    assert.match(fileNamed("components/VideoDrawer.jsx"),
      /import \{ submitTask \} from "\.\.\/gen\/submitTask\.js";/,
      "the video drawer must submit through the shared road, not its own fetch");
  });

  test("the routes handed to submitTask are exactly the known spend routes", () => {
    const found = new Set();
    files.forEach((f) => {
      const m = read(f).match(/submitTask\(\s*["']([^"']+)["']/g) || [];
      m.forEach((hit) => found.add(hit.replace(/^submitTask\(\s*["']/, "").replace(/["']$/, "")));
    });
    assert.deepEqual([...found].sort(), SPEND_ROUTES,
      "a route reached the submit road without being declared here. Every route on this list "
      + "spends credits; adding one is a spend decision, not a refactor. Found: "
      + JSON.stringify([...found].sort()));
  });

  test("submitTask still refuses to retry, and still keys errors off the body", () => {
    // The two rules a second submit path would most easily lose. gql_mutate's no-retry covers
    // the server->PixAI hop only; a client re-POST creates a second CHARGED task.
    const road = fileNamed(ROAD);
    assert.doesNotMatch(road, /\bretry\b\s*\(|setTimeout\([^)]*fetch/i,
      "submitTask must never re-POST a spend route");
    assert.match(road, /if \(d\.error \|\| !d\.task_id\)/,
      "errors arrive HTTP 200 with an {error} body -- keying off r.ok would read a rejection as a submit");
    assert.match(road, /return null;/,
      "every failure path must return null, which is how a host knows to raise its own error event");
  });
});

describe("registration belongs to the road, not to the shell that mounted the drawer", () => {
  test("submitTask registers by tracking -- one call, registration and polling together", () => {
    const road = fileNamed(ROAD);
    const track = road.indexOf("window.Jobs.track(");
    assert.ok(track >= 0,
      "completion (and with it registration) must ride Jobs.track -- track() is register + poll, "
      + "which is what makes a surface's job visible in the Activity tray without the surface "
      + "having to remember to say so");
    assert.ok(road.indexOf("if (!window.Jobs)") < track,
      "a page with no Jobs engine must be handled before the track call, not by letting it throw");
  });

  test("neither gallery shell registers a job on mg-submit any more", () => {
    for (const shell of ["App.jsx", "components/AppMobile.jsx"]) {
      assert.doesNotMatch(codeOnly(fileNamed(shell)), /Jobs\.register/,
        shell + " must not register jobs. Shell-side registration is what made tracking depend on "
        + "which shell was mounted: the desktop one did it, the mobile one never had the listener, "
        + "and a video submitted from the phone was tracked nowhere at all");
    }
  });

  test("App.jsx still counts the run it stopped registering", () => {
    // The listener stays -- it drives the banner spinner. Only the registration left.
    const app = fileNamed("App.jsx");
    assert.match(app, /document\.addEventListener\("mg-submit", onSubmit\);/,
      "the shell still listens for mg-submit");
    assert.match(app, /count: r\.count \+ 1/,
      "the live-run counter must survive the removal of the register call");
  });

  test("the drawer still tells its hosts about the submit, on the task id", () => {
    // The Loom reconciles a card's durable shot mode from this event's payload at the one moment
    // the submitted mode is known for certain -- that contract predates the road and outlives it.
    const drawer = fileNamed("components/VideoDrawer.jsx");
    assert.match(drawer, /emit\("mg-submit", \{ task_id: tid, payload: p \}\);/,
      "mg-submit must still carry {task_id, payload}");
    for (const evt of ["mg-result", "mg-error", "mg-slow", "mg-paused"]) {
      assert.ok(drawer.includes('emit("' + evt + '"'), "the drawer must still emit " + evt);
    }
  });
});
