import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/* The catalog is backed up before every update (owner, 2026-11-18: "We used to do this when
   the catalog was a csv...."). The server's first phase is "backup" (moonglade/updater.py
   run_update, dev/tests/test_updater.py); the update card says so before the confirm and
   shows it as its own first step, closed when the server moves on to "pulling". Read as
   source: UpdatePhases.jsx is JSX, which node cannot import. */
const read = (p) => readFileSync(new URL("../../gallery/src/" + p, import.meta.url), "utf8");
const hook = read("hooks/useControlPanel.js");

test("the confirm's plain account names the catalog copy first", () => {
  const phases = read("components/UpdatePhases.jsx");
  const what = phases.slice(phases.indexOf("export const UPDATE_WHAT"));
  assert.match(what, /^export const UPDATE_WHAT = \[\s*"Your catalog is copied first/);
});

test("the step list opens with the backup and advances to the pull on pulling", () => {
  const steps = hook.slice(hook.indexOf("const freshSteps"), hook.indexOf("const advanceSteps"));
  const keys = [...steps.matchAll(/key: "(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(keys, ["backup", "pull", "apply", "restart"]);
  assert.match(steps, /key: "backup"[^}]*state: "now"/);
  assert.match(hook, /st\.phase === "pulling" && !sawPull\)[\s\S]{0,80}advanceSteps\("pull"/);
});

test("the meter has a stop for every step of the four-step list", () => {
  const phases = read("components/UpdatePhases.jsx");
  assert.match(phases, /4: \[8, 30, 54, 78, 100\]/);
});
