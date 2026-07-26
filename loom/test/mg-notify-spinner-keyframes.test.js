import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner screen recording 2026-07-25: "active jobs in the loom tracker show up but do nothing
// to show it's actually active." Two frames two seconds apart were pixel-identical -- the
// running job's spinner was frozen solid.
//
// Cause: static/mg-notify.js styles BOTH the mascot (.jt-spin .jt-nel) and the ring
// (.jt-spin .gen-ring) with `animation: gen-spin ...`, but never DEFINED @keyframes gen-spin.
// The only definition lived in the gallery's own page CSS (inside create_app, beside
// .header-stats/.ver-badge). So on the gallery the animation worked by accident of the host
// page supplying the keyframes, and on the Loom -- whose _LOOM_SHELL does not carry that CSS
// -- the animation named a keyframe that did not exist and silently did nothing. A running
// job was therefore indistinguishable from a stalled one, on the surface where that matters
// most.
//
// mg-notify.js is deliberately host-neutral (its own comments say so) and already injects six
// of its own @keyframes. This asserts it owns every animation it references, so the next
// component to be styled here cannot inherit the same invisible dependency on its host.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8");

describe("mg-notify owns every keyframe it animates", () => {
  test("defines @keyframes gen-spin itself", () => {
    assert.match(src, /@keyframes gen-spin\s*\{/,
      "mg-notify.js animates `gen-spin` but does not define it -- on any host page that " +
      "lacks the gallery's CSS (the Loom) the tracker spinner is frozen");
  });

  test("every animation name it uses is defined in its own stylesheet", () => {
    // `animation: <name> ...` / `animation:<name>` -- collect the names it relies on
    const used = new Set();
    for (const m of src.matchAll(/animation:\s*([a-zA-Z_][\w-]*)\s/g)) used.add(m[1]);
    // names that are CSS keywords rather than a custom keyframe
    for (const kw of ["none", "inherit", "initial", "unset", "revert"]) used.delete(kw);
    const defined = new Set(
      [...src.matchAll(/@keyframes\s+([a-zA-Z_][\w-]*)/g)].map((m) => m[1]));
    const missing = [...used].filter((n) => !defined.has(n));
    assert.deepEqual(missing, [],
      "animation name(s) referenced but never defined here, so they depend on the host " +
      "page happening to provide them: " + missing.join(", "));
  });
});
