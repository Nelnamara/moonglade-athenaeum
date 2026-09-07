import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE FEAT BEACON ALWAYS CARRIES A NONCE (2026-09-07).

   /api/ach-event went back from LOCALHOST to LOGIN on the owner's ruling -- "I feel like
   triggered should be obtainable easily on a phone just like desktop. For sure build the
   nonce." -- and the nonce is the entire reason LOGIN is honest again. The server mints one
   per render, spends it on ONE event inside 60 seconds, and returns the next one.

   That makes a bare `apiPost("/api/ach-event", {event})` a silent, one-shot bug rather than
   a loud one: the FIRST such call still works (the boot nonce is sitting right there in
   MG_BOOT for anyone to send), and only the SECOND is refused. Triggered needs five pokes,
   so a caller that forgot to rotate earns exactly one of them and then quietly stops -- with
   no error on screen, because every one of these callers is deliberately fail-soft. Nothing
   in a browser or a Python test would fail; the feat would just never arrive.

   Structural properties rot back, and this one rots back the moment someone adds a fourth
   feat event and posts it "the obvious way". Same argument, same runner, and the same
   source-level device as request-module-structure.test.js next door: there is no jsdom or
   React harness here, so the guard reads the source.

   The Loom's classic help modal posts its own `docs` beacon from an inline script inside
   moonglade_gallery.py's _LOOM_SHELL -- outside gallery/src, so outside this walk. It
   carries the same three rules by hand (send, adopt, refresh-once-on-403); its Python-side
   comment says so, and tests/test_telemetry.py proves the route's half of the contract. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const MODULE = "notify/achNonce.js";
const ROUTE = "/api/ach-event";

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
// The comments EXPLAINING the beacon name the route (useFolio.js's poke history,
// FolioOverlay/FolioMobile's provenance notes), and would otherwise trip the very guard they
// document. Same device, same reason, as request-module-structure.test.js's own codeOnly.
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const fileNamed = (r) => {
  const f = files.find((x) => rel(x) === r);
  assert.ok(f, "expected " + r + " to exist");
  return read(f);
};

describe("one module owns the /api/ach-event beacon", () => {
  test("no file but notify/achNonce.js names the route in code", () => {
    const callers = files.filter((f) => codeOnly(read(f)).includes(ROUTE)).map(rel).sort();
    assert.deepEqual(callers, [MODULE],
      "a second poster means a second place that has to remember to send the nonce and adopt "
      + "next_nonce -- and forgetting is silent (the first event lands, the rest are refused "
      + "403 and swallowed). Call sendAchEvent(event) from " + MODULE + " instead. Found: "
      + JSON.stringify(callers));
  });

  test("the one poster sends a nonce and adopts next_nonce", () => {
    const mod = codeOnly(fileNamed(MODULE));
    assert.match(mod, /apiPost\(\s*"\/api\/ach-event"\s*,\s*\{[^}]*\bnonce\b/,
      "the POST body must carry `nonce` -- without it every event is a 403 stale page");
    assert.match(mod, /\bnext_nonce\b/,
      "an accepted event returns next_nonce; a poster that drops it earns exactly one feat "
      + "event per page render, which is one poke out of the five Triggered needs");
    assert.match(mod, /"\/api\/ach-nonce"/,
      "a page idle past the 60s window needs the top-up route to recover, or an open tab "
      + "loses the beacon for good");
    assert.match(mod, /http_status\s*===?\s*403/,
      "the stale-page refusal is the one that gets a refresh + one retry; a 429 must not");
  });

  test("every beacon caller gets sendAchEvent from that module", () => {
    const CALL = /\bsendAchEvent\(/;
    const IMPORT = /from\s+"\.{1,2}(?:\/\.\.)*\/?notify\/achNonce\.js"/;
    const offenders = files
      .filter((f) => rel(f) !== MODULE)
      .filter((f) => CALL.test(codeOnly(read(f))))
      .filter((f) => !IMPORT.test(read(f)))
      .map(rel).sort();
    assert.deepEqual(offenders, [],
      "sendAchEvent must come from " + MODULE + " -- a local re-implementation is the same "
      + "second poster this file exists to prevent. Found: " + JSON.stringify(offenders));
  });

  test("the two known callers still go through it", () => {
    // Not a completeness claim -- a new caller is fine. This is the regression direction:
    // the konami egg and the narrator poke are the two that HAD their own bare posts.
    for (const name of ["App.jsx", "hooks/useFolio.js"]) {
      const src = codeOnly(fileNamed(name));
      assert.match(src, /\bsendAchEvent\(/,
        name + " stopped using sendAchEvent -- if its beacon moved, move this line with it; "
        + "if it went back to a bare apiPost, that is the bug this file names");
    }
  });
});
