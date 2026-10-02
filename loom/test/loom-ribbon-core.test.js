import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { flat } from "../src/loom-core.js";
import { selectTake } from "../src/loom-takes-core.js";
import {
  RIBBON_DE_THRESHOLD, RIBBON_GRID, ribbonPairs, frameUrl, rgbToLab, deltaE76, meanDeltaE, colourJump, pairTitle, pairFlagged,
} from "../src/loom-ribbon-core.js";

/* THE CONTINUITY RIBBON (Session P, NOTES P9 -- "compute in Lab, not RGB"; BUILD-w5-p §5.2). */

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = readFileSync(path.join(here, "fixtures", "board-legacy.json"), "utf8");
const legacy = () => JSON.parse(FIXTURE);
const solid = (rgb, n = RIBBON_GRID.w * RIBBON_GRID.h) => {
  const a = new Uint8ClampedArray(n * 4);
  for (let i = 0; i < n; i++) { a[i * 4] = rgb[0]; a[i * 4 + 1] = rgb[1]; a[i * 4 + 2] = rgb[2]; a[i * 4 + 3] = 255; }
  return a;
};
const rgbDistance = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);

describe("ribbonPairs: one pair per cut between rendered shots, through the ★ take", () => {
  test("the legacy board: unrendered shots are skipped; close = trimOut ?? dur, open = trimIn", () => {
    const p = legacy();
    const pairs = ribbonPairs(flat(p));
    assert.deepEqual(pairs.map((x) => [x.a.code, x.b.code]), [["A·01", "A·02"], ["A·02", "B·01"], ["B·01", "B·02"]],
      "C·01 (unrendered) and C·02 (failed, no render) are not in the cut, so they make no pair");
    const c = (id) => flat(p).find((e) => e.c.id === id).c;
    for (const x of pairs) {
      const a = c(x.a.cardId), b = c(x.b.cardId);
      assert.equal(x.a.mid, String(a.resultMid));
      assert.equal(x.a.at, a.trimOut != null ? Number(a.trimOut) : Number(a.actualDur));
      assert.equal(x.b.mid, String(b.resultMid));
      assert.equal(x.b.at, Number(b.trimIn) || 0);
      assert.equal(x.stale, false);
    }
    assert.equal(JSON.stringify(p), JSON.stringify(JSON.parse(FIXTURE)), "reading the board writes nothing");
  });
  test("it reads the ★ take with the card's trims laid over it (F9), and follows a ★ change", () => {
    const p = legacy();
    const a1 = p.acts[0].cards[0];
    a1.trimOut = 3.25;
    const [first] = ribbonPairs(flat(p));
    assert.equal(first.a.at, 3.25, "the card-level trim is authoritative for the selected take");
    const withTakes = selectTake(a1, 1);
    p.acts[0].cards[0] = withTakes;
    assert.equal(ribbonPairs(flat(p))[0].a.mid, String(withTakes.resultMid));
  });
  test("a stale anchor on the incoming shot marks its pair", () => {
    const p = legacy();
    p.acts[0].cards[1].anchor = { shot: p.acts[0].cards[0].id, take: 99, at: null, frame: "", via: "splice" };
    const pairs = ribbonPairs(flat(p));
    assert.equal(pairs[0].stale, true);
    assert.equal(pairs[1].stale, false);
    assert.equal(pairTitle(pairs[0], 0, "ok"), "A·02: anchor changed");
    assert.equal(pairFlagged(pairs[0], null), true, "a stale anchor flags even with no frames to compare");
  });
  test("a take whose clip length was never recorded closes at its planned end, never its first frame", () => {
    // Owner walk 2026-09-30: E·02 opens on exactly E·01's last frame (E·01 at 4.99 s == E·02 at
    // 0 s), yet the E·01 -> E·02 join was flagged "Strong colour jump · mean Lab ΔE 34.9". E·01's
    // take had no recorded length (landTake stores dur null when the task reported none) and
    // Number(null) is 0, so the ribbon compared E·01's FIRST frame with E·02's open. An unknown
    // length now falls through to the planned one; the frame route takes a time at or past the
    // clip's real end as its last frame.
    const p = legacy();
    const [a1, a2] = p.acts[0].cards;
    Object.assign(a1, { actualDur: null, duration: 5, trimOut: null, trimIn: 0 });
    delete a1.takes; delete a1.selectedTake;
    const [first] = ribbonPairs(flat(p));
    assert.equal(first.a.cardId, a1.id);
    assert.equal(first.a.at, 5, "the close is the clip's end, not 0");
    assert.equal(frameUrl(first.a.mid, first.a.at), "/api/loom/frame?mid=" + a1.resultMid + "&at=5.0000");
    for (const blank of [undefined, ""]) {
      a1.actualDur = blank;
      assert.equal(ribbonPairs(flat(p))[0].a.at, 5, "unrecorded (" + JSON.stringify(blank) + ") is unknown too");
    }
    a1.actualDur = null;
    assert.equal(a1.actualDur, null, "reading the board wrote no length onto it");
    // What the ribbon compares: both sides are the shots' RENDERED clips (GET /api/loom/frame), the
    // incoming one at its trimIn -- never the incoming shot's open-frame picture, so a spliced frame
    // with no thumbnail cannot stand in a different picture here.
    assert.equal(first.b.mid, String(a2.resultMid));
    assert.notEqual(first.b.mid, String(a2.openFrame.mediaId));
    assert.equal(frameUrl(first.b.mid, first.b.at), "/api/loom/frame?mid=" + a2.resultMid + "&at=0.0000");
  });
  test("the frame's address quantises the time to a 24 fps frame", () => {
    assert.equal(frameUrl("123", 1.01), "/api/loom/frame?mid=123&at=1.0000");
    assert.equal(frameUrl("123", 1.03), "/api/loom/frame?mid=123&at=1.0417");
    assert.equal(frameUrl("local_0123456789ab", -2), "/api/loom/frame?mid=local_0123456789ab&at=0.0000");
    assert.equal(frameUrl("a&b", 0), "/api/loom/frame?mid=a%26b&at=0.0000");
  });
});

describe("the colour jump: mean CIE76 ΔE in Lab (D65), not an RGB distance", () => {
  test("known colours: white is L 100, black L 0; identical frames are 0; black vs white is 100", () => {
    const w = rgbToLab([255, 255, 255]);
    assert.ok(Math.abs(w[0] - 100) < 1e-3 && Math.abs(w[1]) < 1e-3 && Math.abs(w[2]) < 1e-3, JSON.stringify(w));
    assert.deepEqual(rgbToLab([0, 0, 0]).map((v) => Math.round(v * 1000) / 1000), [0, 0, 0]);
    assert.equal(meanDeltaE(solid([46, 58, 90]), solid([46, 58, 90])), 0);
    assert.ok(Math.abs(meanDeltaE(solid([0, 0, 0]), solid([255, 255, 255])) - 100) < 1e-3);
    assert.equal(colourJump(100), true);
  });
  test("pairs either side of the threshold (25)", () => {
    assert.equal(RIBBON_DE_THRESHOLD, 25);
    const above = meanDeltaE(solid([0, 0, 196]), solid([0, 0, 255]));
    const below = meanDeltaE(solid([0, 0, 198]), solid([0, 0, 255]));
    assert.ok(above > 25 && above < 26, String(above));
    assert.ok(below < 25 && below > 24, String(below));
    assert.equal(colourJump(above), true);
    assert.equal(colourJump(below), false);
    assert.equal(colourJump(null), false, "not measured is never a flag");
  });
  test("RGB distance is NOT the measure: equal RGB distances give different ΔE, and the prototype's RGB rule disagrees", () => {
    const pairs = [[[0, 0, 160], [0, 0, 255]], [[0, 160, 0], [0, 255, 0]], [[160, 0, 0], [255, 0, 0]]];
    const rgb = pairs.map(([p, q]) => rgbDistance(p, q));
    assert.ok(rgb.every((d) => d === rgb[0]), "all three are 95 apart in RGB");
    const de = pairs.map(([p, q]) => deltaE76(rgbToLab(p), rgbToLab(q)));
    assert.ok(new Set(de.map((d) => d.toFixed(2))).size === 3, "...and three different ΔE: " + de.join(", "));
    // The prototype flagged an RGB distance over 60. This yellow pair is 77.8 apart in RGB and
    // under 25 in Lab: the Loom does not flag it.
    const y = meanDeltaE(solid([200, 200, 0]), solid([255, 255, 0]));
    assert.ok(rgbDistance([200, 200, 0], [255, 255, 0]) > 60 && y < 25, String(y));
    assert.equal(colourJump(y), false);
  });
  test("the mean is over the grid, and a transparent pixel is left out", () => {
    const a = solid([0, 0, 0], 4), b = solid([0, 0, 0], 4);
    b.set([255, 255, 255, 255], 0);                 // one pixel of four differs by 100
    assert.ok(Math.abs(meanDeltaE(a, b) - 25) < 1e-3);
    b.set([255, 255, 255, 0], 4);                   // a transparent pixel does not count
    assert.ok(Math.abs(meanDeltaE(a, b) - 100 / 3) < 1e-3);
    assert.equal(meanDeltaE(null, b), null);
  });
  test("titles, in the page's words", () => {
    const pair = { a: { code: "A·01" }, b: { code: "A·02" }, stale: false };
    assert.equal(pairTitle(pair, 3, "ok"), "Matches");
    assert.equal(pairTitle(pair, 40, "ok"), "Strong colour jump (a heuristic, not a verdict)");
    assert.match(pairTitle(pair, null, "missing"), /No frame to compare here/);
    assert.equal(pairFlagged(pair, null), false);
    assert.equal(pairFlagged(pair, 40), true);
  });
});
