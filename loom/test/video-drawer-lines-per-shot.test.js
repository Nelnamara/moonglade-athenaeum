import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { linesShown } from "../../gallery/src/gen/videoDrawerCore.js";

/* THE LOOM'S VIDEO TAB SHOWS THE BOUND SHOT'S LINES ONLY (owner walk 2026-09-30). The Loom mounts
   ONE <VideoDrawer> for every shot. With E·02 bound (after E·01 rendered), the panel's result
   block under "Generate video" still showed "✓ Rendered — 70,000 credits. Added to your gallery."
   with E·01's picture, and E·02's own "Rendering… (task N)" line went in underneath it: the
   drawer's result lines were one list for the whole drawer. A line now belongs to the shot it was
   pushed for, and the Loom draws the bound shot's lines only. The gallery's dock and the phone's
   Video mode are unchanged. (No React harness in this runner: the pure filter is unit-tested,
   the wiring is a source-text check.) */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(here, "../../gallery/src/components/VideoDrawer.jsx"), "utf8").replace(/\r\n/g, "\n");

const E1 = [
  { id: 1, shot: "E1", kind: "result", mediaIds: ["V1"], cost: 70000 },
];
const both = E1.concat([{ id: 2, shot: "E2", kind: "status", moon: true, text: "Rendering under the eclipse… (task 123456)" }]);

describe("linesShown", () => {
  test("the walk: E·02 bound shows E·02's progress line and not E·01's result", () => {
    assert.deepEqual(linesShown(both, { loom: true, shot: "E2" }).map((l) => l.id), [2]);
    assert.deepEqual(linesShown(E1, { loom: true, shot: "E2" }), [], "E·02 bound before its own render: no result block");
  });
  test("binding E·01 again shows its lines again (nothing is dropped)", () => {
    assert.deepEqual(linesShown(both, { loom: true, shot: "E1" }).map((l) => l.id), [1]);
  });
  test("the draft has its own lines, and an unbound drawer only its own", () => {
    const rs = [{ id: 3, shot: "__draft__", kind: "error", text: "x" }, { id: 4, shot: "", kind: "error", text: "y" }];
    assert.deepEqual(linesShown(rs, { loom: true, shot: "__draft__" }).map((l) => l.id), [3]);
    assert.deepEqual(linesShown(rs, { loom: true, shot: "" }).map((l) => l.id), [4]);
    assert.deepEqual(linesShown(rs, { loom: true }).map((l) => l.id), [4]);
  });
  test("outside the Loom nothing changes: the dock draws errors only, the phone everything", () => {
    const rs = [{ id: 5, kind: "status", text: "Submitting…" }, { id: 6, kind: "error", text: "Pick a source image first." }];
    assert.deepEqual(linesShown(rs, { dock: true }).map((l) => l.id), [6]);
    assert.deepEqual(linesShown(rs, {}).map((l) => l.id), [5, 6]);
    assert.deepEqual(linesShown(null, {}), []);
  });
});

describe("the wiring (VideoDrawer.jsx)", () => {
  test("a Loom line is stamped with its shot when it is pushed", () => {
    assert.match(SRC, /const boundShot = \(\) => \(\(loomCtx && st\.current\.loomTarget && st\.current\.loomTarget\.card_id\) \|\| ""\);/);
    assert.match(SRC, /const shot = loomCtx \? \(line\.shot != null \? String\(line\.shot\) : boundShot\(\)\) : undefined;/);
    assert.match(SRC, /setResults\(\(rs\) => rs\.concat\(\[\{ id, \.\.\.line, \.\.\.\(loomCtx \? \{ shot \} : \{\}\) \}\]\)\);/);
  });
  test("a render's line is the shot captured at the click, whatever is bound when it updates", () => {
    const gen = SRC.slice(SRC.indexOf("const doGenerate = async () => {"));
    const cap = gen.indexOf("const target = loomCtx ? st.current.loomTarget : null;");
    const line = gen.indexOf('const id = pushLine({ kind: "status", moon: true, text: "Submitting…", ...(loomCtx ? { shot: target.card_id } : {}) });');
    assert.ok(cap >= 0 && line > cap, "the Submitting line names the captured target's shot");
  });
  test("a change of bound shot repaints the lines; the render draws linesShown for the bound shot", () => {
    const at = SRC.indexOf("const setLoomTarget = (t) => {");
    const body = SRC.slice(at, SRC.indexOf("\n  };", at));
    assert.match(body, /const was = boundShot\(\);/);
    assert.match(body, /if \(boundShot\(\) !== was\) rerender\(\);/);
    assert.match(SRC, /const shown = linesShown\(results, \{ dock: inDock, loom: !!loomCtx, shot: boundShot\(\) \}\);/);
  });
});
