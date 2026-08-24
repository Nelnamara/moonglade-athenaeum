import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// FIX 2026-08-23: "Recover a task by ID" used to render the generic "imported -- N added"
// message even when the server reported the task was ALREADY catalogued ({already:true,
// saved:0}) -- so an already-in-library task read as "imported -- 0 added", which looks like
// a failure. The server flag was always correct (tests/test_web_pick.py pins {already:true,
// saved:0, media_ids}); the client just dropped it. This pins the two client halves of the
// fix: the hook keeps `already` in taskState, and BOTH surfaces (the desktop overlay and
// the mobile twin ControlMobile.jsx) branch their done-copy on it.
// No jsdom/React harness in this runner -- source-presence assertions are the established
// pattern here (see mirror-tile.test.js).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const overlay = readFileSync(
  path.join(__dirname, "../../gallery/src/components/ControlPanelOverlay.jsx"), "utf8");
const hook = readFileSync(
  path.join(__dirname, "../../gallery/src/hooks/useControlPanel.js"), "utf8");
const mobile = readFileSync(
  path.join(__dirname, "../../gallery/src/components/ControlMobile.jsx"), "utf8");

test("the import-task hook keeps the server's `already` flag in state", () => {
  // setTaskState on the import-task response must thread `already` through, not just saved --
  // the render branch below is dead if the flag is dropped here (which is exactly the bug).
  assert.match(hook, /already:\s*!!d\.already/,
    "importTask() must keep d.already in taskState");
});

test("the done-message branches on `already`, not always 'imported -- N added'", () => {
  // The already-in-library copy exists...
  assert.ok(overlay.includes("already in your library — nothing new to fetch"),
    "an already-catalogued task must get its own done-message");
  // ...and it is GATED on taskState.already (the branch), not shown unconditionally.
  assert.match(overlay, /taskState\.already\s*\?/,
    "the done-message must branch on taskState.already");
  // The original imported-count copy is still the OTHER branch (fresh imports).
  assert.ok(overlay.includes('"✓ imported — " + taskState.saved + " added to the catalog"'),
    "the fresh-import copy must remain for the not-already case");
});

test("the mobile twin (ControlMobile) branches its done-message on `already` too", () => {
  // ControlMobile renders the SAME import-task tile as the desktop overlay; it must carry
  // the identical already-branch, or mobile keeps reading "imported — 0 added" (the bug).
  assert.ok(mobile.includes("already in your library — nothing new to fetch"),
    "the mobile done-message must have the already-in-library copy");
  assert.match(mobile, /taskState\.already\s*\?/,
    "the mobile done-message must branch on taskState.already");
  assert.ok(mobile.includes('"✓ imported — " + taskState.saved + " added to the catalog"'),
    "the mobile fresh-import copy must remain for the not-already case");
});
