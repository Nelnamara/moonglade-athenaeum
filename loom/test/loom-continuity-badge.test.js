import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// AUDIT_2026-07-21: frameLinked() (loom-core.js) had zero call sites -- the continuity
// indicator it was built to power doesn't exist anywhere in V2. Owner's call: rebuild it,
// not delete it. This restores a small badge on each board card showing when a shot's
// OPENING frame is already frameLinked (continuityLinked, loom-core.js) to the immediately
// preceding shot's CLOSING frame -- i.e. the cut is visually continuous. It renders ONLY
// when linked is true (a quiet affirmation, not a warning): most shots are deliberately
// connect:"new" (an intentional fresh look/place, per CONNECT.new's own hint), so a
// non-matching frame is usually the shot's INTENT rather than a mistake to flag.
//
// This is NOT the same concept as the existing "Continuity" chip row (CONNECT/connectMeta,
// setShotMode/setShotConnect) -- that couples a SINGLE shot's own Mode to its connect field
// (how this shot's own video generation should behave); it never compares actual frame
// images across a cut the way frameLinked does. Both are real, both stay.
//
// master-storyboard.jsx has no jsdom/React test harness in this runner (same situation as
// mg-model-picker.js / the Deep Focus cost-badges) -- source-presence assertions are the
// established pattern for files in that position (see loom-cost-badges.test.js,
// loom-gen-drawer-loom-ctx.test.js); continuityLinked's own logic is exercised with real
// assertions in loom-core.test.js instead, since it is a plain, framework-free function.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("board-card continuity indicator (frameLinked, via continuityLinked)", () => {
  test("continuityLinked is imported from loom-core.js", () => {
    assert.match(src, /import\s*\{[\s\S]*?\bcontinuityLinked\b[\s\S]*?\}\s*from\s*"\.\/src\/loom-core\.js";/,
      "continuityLinked must be imported alongside frameLinked/connectMeta");
  });

  test("continuityLinked is actually CALLED against the board's per-card entry, not just imported", () => {
    // A bare identifier in the import list has no '(' after it -- this only matches a real
    // call site. `entries` is the cross-act flattened list (see prevEntry/weavePrevEntry's
    // own use of it) so continuity is checked against the true previous shot in the whole
    // project, not just within the current act.
    assert.match(src, /continuityLinked\(entries,\s*e\.c\.id\)/,
      "expected a real continuityLinked(entries, e.c.id) call site in the board card render");
  });

  test("the board card actually reacts to the result -- a badge is conditionally rendered from it", () => {
    assert.match(src, /\{linked\s*&&\s*<span className="lv-st linked"/,
      "expected a conditionally-rendered '.lv-st linked' badge gated on the continuityLinked result");
  });

  test("the linked badge renders inside the card's .lv-cmeta row, alongside mode/duration/status", () => {
    const cmetaMatch = src.match(/<div className="lv-cmeta">[\s\S]*?<\/div>/);
    assert.ok(cmetaMatch, "expected to find the board card's .lv-cmeta row");
    assert.match(cmetaMatch[0], /lv-st linked/,
      "the continuity badge must live in the same meta row as mode/duration/status, not a separate new region");
  });

  test("a '.lv-st.linked' CSS rule exists, reusing the existing small-badge visual language rather than inventing a new one", () => {
    assert.match(src, /\.lv-st\.linked\{/,
      "expected a .lv-st.linked modifier reusing the .lv-st base badge rule (font/padding/border-radius already shared by done/wip/todo/paused)");
  });
});
