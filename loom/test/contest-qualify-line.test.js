import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { qualifyLine } from "../../gallery/src/lib/contestRules.js";

/* Contest cards say whether you have used what a contest requires (2026-11-18). The statuses
   come from /api/contests/qualify (moonglade/contest_qualify.py, dev/tests/test_contest_qualify.py);
   this pins the words, and that an unknown never reads as "not used". */

test("the line says used, not used, partly used, or that it could not tell", () => {
  assert.equal(qualifyLine([{ kind: "LoRA", need: 1, used: 1, unknown: 0 }]), "Required LoRA: used ✓");
  assert.equal(qualifyLine([{ kind: "model", need: 2, used: 2, unknown: 0 }]), "Required models: all 2 used ✓");
  assert.equal(qualifyLine([{ kind: "LoRA", need: 1, used: 0, unknown: 0 }]), "Required LoRA: not used yet");
  assert.equal(qualifyLine([{ kind: "LoRA", need: 3, used: 1, unknown: 1 }]),
               "Required LoRAs: 1 of 3 used, 1 unchecked");
  assert.equal(qualifyLine([{ kind: "model", need: 1, used: 0, unknown: 1 }]), "Required model: couldn't check");
  assert.equal(qualifyLine([{ kind: "recipe", need: 1, used: 0, unknown: 1 }]), "Required recipe: not recorded here");
  assert.equal(qualifyLine([{ kind: "LoRA", need: 1, used: 1, unknown: 0 },
                            { kind: "recipe", need: 1, used: 0, unknown: 1 }]),
               "Required LoRA: used ✓ · Required recipe: not recorded here");
});

test("a contest that requires nothing has no line", () => {
  for (const s of [undefined, null, [], [{ kind: "LoRA", need: 0 }], ["x"]]) assert.equal(qualifyLine(s), null);
});

test("both card surfaces draw the line in their existing card-line styles", () => {
  const read = (f) => readFileSync(new URL("../../gallery/src/components/" + f, import.meta.url), "utf8");
  const desk = read("ContestsOverlay.jsx");
  assert.equal((desk.match(/<div className="mgct-dates">\{qualifyFor\(c\)\}<\/div>/g) || []).length, 2);
  assert.match(desk, /<span className="mgct-dates dim">\{qualifyFor\(featured\)\}<\/span>/);
  const phone = read("ContestsMobile.jsx");
  assert.match(phone, /<span className="cmb-cardmeta">\{qualifyFor\(c\)\}<\/span>/);
  assert.match(phone, /<span className="cmb-herometa">\{qualifyFor\(featured\)\}<\/span>/);
});
