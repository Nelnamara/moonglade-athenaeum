import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner screen recording 2026-07-25: "active jobs in the loom tracker show up but do nothing
// to show it's actually active." Two frames two seconds apart were pixel-identical -- the
// running job's spinner was frozen solid.
//
// Cause: static/mg-notify.js styled BOTH the mascot (.jt-spin .jt-nel) and the ring
// (.jt-spin .gen-ring) with `animation: gen-spin ...`, but never DEFINED @keyframes gen-spin.
// The only definition lived in the gallery's own page CSS (inside create_app, beside
// .header-stats/.ver-badge). So on the gallery the animation worked by accident of the host
// page supplying the keyframes, and on the Loom -- whose _LOOM_SHELL does not carry that CSS
// -- the animation named a keyframe that did not exist and silently did nothing. A running
// job was therefore indistinguishable from a stalled one, on the surface where that matters
// most.
//
// Port note 2026-08-08 (React migration): static/mg-notify.js is deleted; the notify system's
// styles now live verbatim in gallery/src/styles/notify.css, riding gallery/dist/app.css
// (Vite) AND loom/dist/master-storyboard.bundle.css (esbuild). The self-ownership contract
// transfers wholesale: that stylesheet is the only thing standing between the Loom shell and
// a frozen spinner, so it must own every @keyframes it references -- gen-spin first among
// them -- and keep the .jt-spin rules pointed at it. The name-collector below also grew up
// with the move: the CSS uses comma-separated `animation:` shorthand lists (the old
// first-name-only scan would have skipped the trailing names), so it now reads every name
// in each list.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
  path.join(__dirname, "../../gallery/src/styles/notify.css"), "utf8");

describe("notify.css owns every keyframe it animates", () => {
  test("defines @keyframes gen-spin itself", () => {
    assert.match(src, /@keyframes gen-spin\s*\{/,
      "notify.css animates `gen-spin` but does not define it -- on any host page that " +
      "lacks extra CSS (the Loom shell) the tracker spinner is frozen");
  });

  test("the .jt-spin rules still animate gen-spin", () => {
    // The mascot and the ring are the two visible 'this job is alive' signals; both
    // must stay wired to the keyframe the previous test proves exists.
    assert.match(src, /\.jt-spin\s+\.jt-nel\s*\{[^}]*animation:\s*gen-spin/,
      ".jt-spin .jt-nel no longer animates gen-spin -- the mascot spinner is frozen");
    assert.match(src, /\.jt-spin\s+\.gen-ring\s*\{[^}]*animation:\s*gen-spin/,
      ".jt-spin .gen-ring no longer animates gen-spin -- the ring spinner is frozen");
  });

  test("every animation name it uses is defined in its own stylesheet", () => {
    // `animation: <a> ..., <b> ...` -- collect every name the stylesheet relies on.
    // Split each declaration's value on commas and take the leading ident of each
    // segment (commas inside cubic-bezier(...) yield numeric-led fragments, which the
    // ident regex simply doesn't match).
    const used = new Set();
    for (const decl of src.matchAll(/animation:\s*([^;{}]+)/g)) {
      for (const part of decl[1].split(",")) {
        const m = part.match(/^\s*([a-zA-Z_][\w-]*)/);
        if (m) used.add(m[1]);
      }
    }
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
