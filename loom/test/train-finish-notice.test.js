import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ended, finishNotice, liveRuns } from "../../gallery/src/lib/trainWatchCore.js";

/* LoRA training says when it finishes (2026-11-18; owner: "Recover a task is fine where it
   is" -- nothing moves). A run seen queued or training, then gone from the running list, is
   looked up once and announced in the normal corner notice by how it ended. */

test("live runs are the queued and training ones", () => {
  const live = liveRuns({ running: [{ id: "a", status: "running", title: "Moth" }],
                          runs: [{ id: "b", status: "waiting" }, { id: "c", status: "done" },
                                 { id: "d", status: "captioning" }] });
  assert.deepEqual([...live.keys()], ["a", "b"]);
  assert.equal(live.get("a"), "Moth");
  assert.equal(liveRuns(null).size, 0);
});

test("a watched run that left the list has ended", () => {
  const watched = new Map([["a", "Moth"], ["b", ""]]);
  assert.deepEqual(ended(watched, new Map([["b", ""]])), ["a"]);
});

test("done and failed each say so; anything else says nothing", () => {
  const ok = finishNotice({ status: "done", title: "Moth" });
  assert.equal(ok.kind, "ok");
  assert.match(ok.msg, /^Moth is ready/);
  const bad = finishNotice({ status: "failed", reason: "dataset too small" }, "Moth");
  assert.equal(bad.kind, "err");
  assert.equal(bad.sticky, true);
  assert.equal(bad.title, "Moth — training failed");
  assert.equal(bad.msg, "dataset too small");
  assert.equal(finishNotice({ status: "running" }), null);
  assert.equal(finishNotice(undefined, "Moth"), null);
});

test("the Train screens feed the watcher, and every shell starts it", () => {
  const read = (p) => readFileSync(new URL("../../gallery/src/" + p, import.meta.url), "utf8");
  assert.match(read("components/train/useTraining.js"), /noteTrainRuns\(d\)/);
  assert.match(read("notify/index.jsx"), /startTrainWatch\(\)/);
  const watch = read("notify/trainWatch.js");
  assert.match(watch, /markAnnounced\(id\);\s*toastShow\(n\)/);
  assert.match(watch, /announced\(\)\.has\(id\)/);
});
