import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// PORTED 2026-08-08 (static/ -> React, vanilla campaign step 4): static/mg-cost-badge.js's
// <mg-cost-badge> custom element was reimplemented as gallery/src/components/CostBadge.jsx --
// a forwardRef + useImperativeHandle component so every existing costRef.current.setPrice/
// setChecking/clear call site (useGenerate/useEditGenerate/EditTab/FixTab and the Loom's
// priceInto) keeps working verbatim. static/mg-cost-badge.js was deleted with its last embedder,
// the video drawer, in step 7 (the campaign's end) -- the video drawer is now the React
// <VideoDrawer>, which embeds this same React <CostBadge>.
//
// No jsdom/React harness in this runner (same as ModelPicker.jsx / master-storyboard.jsx) --
// source-presence assertions are the established pattern; real interaction was verified live
// (the Gallery drawer's CostBadge priced a picked model to its FREE state, 2026-08-08). What
// these pin is the HONESTY MACHINE: the whole reason this component exists is that a displayed
// "free"/"0 credits" must only ever mean a settled zero-cost result, never "not priced yet"
// and never "the check failed". Those invariants must survive any future refactor.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/CostBadge.jsx"), "utf8");

test("CostBadge is a forwardRef whose imperative handle keeps the setPrice/clear/setChecking contract", () => {
  assert.match(src, /const CostBadge = forwardRef\(/);
  assert.match(src, /useImperativeHandle\(ref, \(\) => \(\{/);
  assert.match(src, /setPrice\(resp\)\s*\{\s*setView\(classify\(resp\)\);/,
    "setPrice must feed the parsed response straight through classify()");
  assert.match(src, /clear\(h\)\s*\{/);
  assert.match(src, /setChecking\(\)\s*\{/);
});

test("classify: a null/undefined response is the could-not-verify ERROR state, never idle", () => {
  // resp === null/undefined means the fetch itself failed -- the fail-closed state a spend
  // gate exists for. Conflating it with clear()'s idle is precisely the bug this prevents.
  assert.match(src, /if \(!d\) return \{ state: "error"/);
});

test("classify checks a real cost BEFORE the server's note, so a note can never hide a cost", () => {
  const costIdx = src.indexOf('return { state: "paid"');
  const noteIdx = src.indexOf('return { state: "idle"');
  assert.ok(costIdx > -1 && noteIdx > -1, "both the paid and note(idle) branches must exist");
  assert.ok(costIdx < noteIdx,
    "the cost/paid branch must be tested before the note/idle branch");
});

test("classify: free:false + cost:null + no note + no error is ERROR, not a silent zero", () => {
  // the trailing branch: nothing was actually priced -> honest 'we don't know', never "0 credits".
  assert.match(src, /\/\/ free:false, cost:null, no note[\s\S]{0,180}return \{ state: "error"/);
  assert.match(src, /if \(d\.free\) return \{ state: "free"/);
});

test("all five honesty states are represented", () => {
  for (const st of ["idle", "checking", "free", "paid", "error"]) {
    assert.ok(src.includes(`"${st}"`), `state "${st}" must appear in the source`);
  }
});

test("CostBadge NEVER fetches -- the host owns the /api/price call and pushes the result in", () => {
  assert.doesNotMatch(src, /\bfetch\s*\(/, "CostBadge must not call fetch; pricing is pushed in via the ref");
  assert.doesNotMatch(src, /XMLHttpRequest|EventSource|WebSocket/,
    "CostBadge must not open any network channel of its own");
});

test("a settled ZERO renders as paid-spends-nothing, never borrowing the free-card wording", () => {
  // loom-core.js's distinction: a priced 0 is real but is NOT the free-card state.
  assert.match(src, /n === 0.*"0 credits — this spends nothing"/);
  assert.match(src, /🎫 FREE — /, "the free-card branch keeps its own ticket wording");
});
