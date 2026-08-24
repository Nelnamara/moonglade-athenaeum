import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The Control Panel's "Mirror to PixAI website" tile (MirrorTile in ControlPanelOverlay.jsx).
// No jsdom/React harness in this runner (same as CostBadge.jsx / ModelPicker.jsx / master-
// storyboard.jsx) -- source-presence assertions are the established pattern here; the live
// interaction was verified in a real browser (the tile connected off localStorage and mirrored
// a real generation, 2026-08-15). What this pins is the credential-switch HONESTY the 2026-08-15
// ultrareview fixed: the tile must never drive itself from a FABRICATED status object, and must
// never let the toggle be switched ON with no session. (Flare flagged this file changed + not
// exercised by any test; this is that test.)
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(
  path.join(__dirname, "../../gallery/src/components/ControlPanelOverlay.jsx"), "utf8");

test("the tile drives off the SERVER's real status, never a fabricated object", () => {
  // A single refresh() helper re-reads /api/mirror/status and setSt()s the real answer.
  assert.match(src, /const refresh = async \(\) => \{/,
    "MirrorTile must have a refresh() helper");
  // Re-anchored 2026-08-23: the read rides api.js's apiGet. Same endpoint, same "server truth".
  assert.match(src, /apiGet\("\/api\/mirror\/status"\)/,
    "refresh() must re-read the real status endpoint");
  // The old bug fabricated {...(s||{}), connected:true, days_left:d.days_left} -- a status with
  // no `enabled` key that drove the toggle from `undefined`. It must be gone.
  assert.doesNotMatch(src, /connected: true, days_left: d\.days_left/,
    "connect() must NOT fabricate a status object; it must refresh() the real one");
  // Both connect() and toggle() end by re-reading the real status.
  const refreshCalls = (src.match(/await refresh\(\)/g) || []).length;
  assert.ok(refreshCalls >= 2,
    `connect() and toggle() must both await refresh() (found ${refreshCalls})`);
});

test("the toggle refuses to enable the credential switch with no session", () => {
  assert.match(src, /const want = !st\.enabled;/,
    "toggle() must compute the requested state from the current one");
  assert.match(src, /if \(want && !st\.connected\)\s*\{/,
    "toggle() must guard: turning ON requires a connected session");
  // The guard returns early (does not POST enable) and tells the user to connect first.
  assert.match(src, /Connect a session first[\s\S]*?return;/,
    "the no-session guard must message the user and return before enabling");
});
