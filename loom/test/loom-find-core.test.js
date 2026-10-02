import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { flat } from "../src/loom-core.js";
import {
  FIND_STATUSES, FIND_MODES, codeForms, findFields, emptyFind, findActive, findMatches, findChips, chipOn, toggleChip,
  currentIndex, stepIndex, findCountText,
} from "../src/loom-find-core.js";

/* FIND IN STORYBOARD (Session P, NOTES P8; the page's find pill, chips and reel rings). The
   app's runFind / stepFind / clearFind only hold this state and select a shot; the matching is
   all here. */

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = readFileSync(path.join(here, "fixtures", "board-legacy.json"), "utf8");

function board() {
  const p = JSON.parse(FIXTURE);
  const c = (id) => p.acts.flatMap((a) => a.cards).find((x) => x.id === id);
  c("c1").title = "Moonwell reveal, slow push in";
  c("c1").prompt = "moonwell, mist, slow push";
  c("c2").notes = "keep the lantern on camera-left";
  c("c4").promptOverride = true;
  c("c4").promptOverrideText = "Maera steps into the glade";
  c("c4").prompt = "maera at the well";
  // c5 takes its open frame from c4's close... anchored to c1, whose ★ has since moved on.
  c("c5").anchor = { shot: "c1", take: 7, at: null, frame: "", via: "splice" };
  return p;
}
const ids = (p, q, f, o) => findMatches(flat(p), p, q, f, o);

describe("the query: code, title, prompt, @tags, notes; one case-insensitive substring", () => {
  test("a shot code in every written form", () => {
    assert.deepEqual(codeForms("A·01"), ["a·01", "a01", "a1"]);
    assert.deepEqual(codeForms("C·12"), ["c·12", "c12"]);
    const p = board();
    for (const q of ["A·01", "a·01", "A01", "a01", "a1", "A1"]) assert.deepEqual(ids(p, q), ["c1"], q);
    assert.deepEqual(ids(p, "B·02"), ["c3b"]);
    assert.deepEqual(ids(p, "c01"), ["c4"]);
    assert.deepEqual(ids(p, "a02"), ["c2"], "A·02 only -- never A·20-something");
  });
  test("title, prompt (the text it sends AND the base prompt under an override), @tags and notes", () => {
    const p = board();
    assert.deepEqual(ids(p, "MOONWELL"), ["c1"], "title and prompt, case-insensitive");
    assert.deepEqual(ids(p, "maera steps"), ["c4"], "the override text it sends");
    assert.deepEqual(ids(p, "at the well"), ["c4"], "the base prompt under the override");
    assert.deepEqual(ids(p, "lantern"), ["c2"], "notes");
    assert.deepEqual(ids(p, "@image2"), ["c4"], "a cast member's @tag (as2 is cast on c4 only)");
    assert.deepEqual(ids(p, "@image1"), ["c1", "c4"]);
    assert.deepEqual(ids(p, "  @IMAGE1 "), ["c1", "c4"], "trimmed, any case");
    assert.deepEqual(ids(p, "nothing like this"), []);
  });
  test("an empty query matches every shot, in board order", () => {
    const p = board();
    assert.deepEqual(ids(p, ""), ["c1", "c2", "c3", "c3b", "c4", "c5"]);
  });
  test("findFields reads the board and writes nothing", () => {
    const p = board();
    const before = JSON.stringify(p);
    flat(p).forEach((e) => findFields(e, p));
    ids(p, "a1", { warn: true, statuses: ["done"], modes: ["I2V"] });
    findChips(flat(p));
    assert.equal(JSON.stringify(p), before);
  });
});

describe("the filters: ⚠ only · status · mode", () => {
  test("⚠ only keeps a stale anchor (P2) and whatever ⚠ the card itself shows (opts.warn)", () => {
    const p = board();
    assert.deepEqual(ids(p, "", { warn: true }), ["c5"], "c5's anchor names take 7 of c1; c1's ★ is another take");
    assert.deepEqual(ids(p, "", { warn: true }, { warn: (e) => e.c.id === "c2" }), ["c2", "c5"]);
  });
  test("chips in one group are OR; groups and the query are AND", () => {
    const p = board();
    assert.deepEqual(ids(p, "", { statuses: ["todo", "error"] }), ["c4", "c5"]);
    assert.deepEqual(ids(p, "", { modes: ["FLF"] }), ["c3", "c3b"]);
    assert.deepEqual(ids(p, "", { statuses: ["done"], modes: ["I2V"] }), ["c1", "c2"]);
    assert.deepEqual(ids(p, "moonwell", { statuses: ["todo"] }), []);
  });
  test("the status is the card's own unless the caller says better (a paused poll)", () => {
    const p = board();
    assert.deepEqual(ids(p, "", { statuses: ["paused"] }, { statusOf: (c) => (c.id === "c3" ? "paused" : c.status) }), ["c3"]);
  });
  test("`only` restricts to exactly those shots (the ribbon's pair), in board order", () => {
    const p = board();
    assert.deepEqual(ids(p, "", { only: ["c3b", "c3"] }), ["c3", "c3b"]);
    assert.deepEqual(ids(p, "split", { only: ["c3", "c1"] }), ["c3"]);
  });
});

describe("chips, stepping and the count", () => {
  test("⚠ only, then only the statuses and modes that occur on this board, in canonical order", () => {
    const p = board();
    assert.deepEqual(FIND_STATUSES, ["todo", "wip", "done", "paused", "error"]);
    assert.deepEqual(FIND_MODES, ["I2V", "R2V", "FLF", "V2V"]);
    assert.deepEqual(findChips(flat(p)).map((c) => c.label), ["⚠ only", "todo", "done", "error", "I2V", "R2V", "FLF"]);
  });
  test("toggling a chip flips only it and sends the current match back to the first", () => {
    let f = { ...emptyFind(), q: "x", cur: 3 };
    const todo = { kind: "status", key: "todo" }, i2v = { kind: "mode", key: "I2V" }, warn = { kind: "warn", key: "warn" };
    f = toggleChip(f, todo);
    assert.deepEqual([f.statuses, f.cur, f.q], [["todo"], 0, "x"]);
    assert.equal(chipOn(f, todo), true);
    f = toggleChip(toggleChip(f, i2v), warn);
    assert.deepEqual([f.modes, f.warn], [["I2V"], true]);
    f = toggleChip(f, todo);
    assert.deepEqual(f.statuses, []);
    assert.equal(chipOn(f, todo), false);
  });
  test("stepping wraps both ways; the count reads 'N of M'", () => {
    assert.equal(stepIndex(0, 3, 1), 1);
    assert.equal(stepIndex(2, 3, 1), 0, "past the last wraps to the first");
    assert.equal(stepIndex(0, 3, -1), 2, "before the first wraps to the last");
    assert.equal(stepIndex(5, 0, 1), 0);
    assert.equal(currentIndex(-1, 4), 3);
    assert.equal(currentIndex(0, 0), -1);
    assert.equal(findCountText({ ...emptyFind(), q: "a", cur: 1 }, 5), "2 of 5");
    assert.equal(findCountText({ ...emptyFind(), q: "a" }, 0), "0");
    assert.equal(findCountText(emptyFind(), 6), "", "nothing looked for, nothing shown");
  });
  test("find is active only when something is looked for", () => {
    assert.equal(findActive(emptyFind()), false);
    assert.equal(findActive({ ...emptyFind(), q: "   " }), false);
    assert.equal(findActive({ ...emptyFind(), q: "a" }), true);
    assert.equal(findActive({ ...emptyFind(), warn: true }), true);
    assert.equal(findActive({ ...emptyFind(), modes: ["I2V"] }), true);
    assert.equal(findActive({ ...emptyFind(), only: ["c1", "c2"] }), true);
  });
});
