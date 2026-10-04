import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  ARCHIVE_TIP, ARCHIVE_WORD, CHIPS, TILE_CHIP, bytesLine, byteFraction, chipOrAll, confirmLines, endToast,
  entrySummary, fixPlan, fmtDay, headerSummary, inChip, lostLine, middleEllipsis, pillFor, problemWords,
  reviewLabel, rowAction, rowsFor, runHeader, shortId, visibleChips,
} from "../../gallery/src/lib/brokenFilesCore.js";

/* Health's Broken files list (Session W; Archive Integrity Handoff, picks W1a-W6a): the words and
   rules the desktop section and the phone screen draw. The server half -- which rows, which pill,
   which action, and the runner that refuses an archive-only row by itself -- is
   tests/test_integrity_broken.py and tests/test_integrity_fix.py. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

const row = (o) => ({ media_id: "2038123456784167", problem: "zero-byte", kind: "zero", path: "images/1gi_8148.webp",
  size: 0, state: "recoverable", action: "redownload", archive_only: false, mark: "", thumb: false, ...o });

const DOC = {
  rows: [
    row({ media_id: "a" }),
    row({ media_id: "b", problem: "no thumbnail", kind: "thumb", action: "rebuild", path: "gallery/thumbs/b.jpg", size: "" }),
    row({ media_id: "c", problem: "suspect: truncated", kind: "suspect", state: "suspect", size: 1468006 }),
    row({ media_id: "d", state: "lost", action: null, archive_only: true, gone_as_of: "2026-10-02" }),
    row({ media_id: "e", problem: "no thumbnail", kind: "thumb", action: "rebuild", archive_only: true }),
  ],
  counts: { all: 5, zero: 2, thumb: 2, suspect: 1, lost: 1 },
  broken: 4, lost: 1,
  fix: { redownload: ["a", "c"], rebuild: ["b"], lost: 1, redownload_bytes: 6000000 },
};

describe("chips", () => {
  test("the handoff's five, in its order", () => {
    assert.deepEqual(CHIPS.map((c) => c.label), ["All", "Zero-byte", "Thumbnail", "Suspect", "Lost"]);
  });
  test("a zero-count chip is hidden; each shown chip carries its count", () => {
    assert.deepEqual(visibleChips({ all: 13, zero: 3, thumb: 9, suspect: 1, lost: 0 }).map((c) => c.label + " " + c.n),
      ["All 13", "Zero-byte 3", "Thumbnail 9", "Suspect 1"]);
    assert.deepEqual(visibleChips({ all: 13, zero: 3, thumb: 9 }, true).map((c) => c.label), ["All", "Zero-byte", "Thumb"]);
  });
  test("Lost cuts across the problem chips", () => {
    const lost = DOC.rows[3];
    assert.ok(inChip(lost, "zero") && inChip(lost, "lost") && inChip(lost, "all"));
    assert.ok(!inChip(DOC.rows[0], "lost"));
    assert.deepEqual(rowsFor(DOC, "thumb").map((r) => r.media_id), ["b", "e"]);
    assert.deepEqual(rowsFor(DOC, "all", { a: true }).map((r) => r.media_id), ["b", "c", "d", "e"]);
  });
  test("a chip a fix run emptied falls back to All", () => {
    const chips = visibleChips({ all: 4, zero: 0, thumb: 4 });
    assert.equal(chipOrAll(chips, "zero"), "all");
    assert.equal(chipOrAll(chips, "thumb"), "thumb");
  });
  test("the problem tiles open the list at their chip", () => {
    assert.deepEqual(TILE_CHIP, { "Zero-byte files": "zero", "Missing thumbs": "thumb" });
  });
});

describe("a row", () => {
  test("the short id and a path cut in the middle", () => {
    assert.equal(shortId("2038123456784167"), "#2038…4167");
    assert.equal(shortId("102"), "#102");
    const p = middleEllipsis("images/some_long_prompt_words_here_1gi_8148.webp", 24);
    assert.equal(p.length, 24);
    assert.ok(p.startsWith("images/") && p.endsWith("8148.webp") && p.includes("…"));
    assert.equal(middleEllipsis("images/a.webp", 24), "images/a.webp");
  });
  test("the problem in words, never 'corrupt'", () => {
    assert.equal(problemWords(DOC.rows[2]), "suspect · ends early");
    assert.equal(problemWords(DOC.rows[1]), "thumbnail missing");
    assert.equal(problemWords(row({ problem: "zero-byte thumbnail" })), "thumbnail empty");
    assert.doesNotMatch(src("lib/brokenFilesCore.js").replace(/never the word "corrupt"|Never the word "corrupt"/gi, ""), /corrupt/i);
  });
  test("pills: RECOVERABLE, SUSPECT peach, LOST dashed, ✓ FIXED emerald", () => {
    assert.deepEqual(pillFor(DOC.rows[0]), { label: "RECOVERABLE", tone: "" });
    assert.deepEqual(pillFor(DOC.rows[2]), { label: "SUSPECT", tone: "peach" });
    assert.deepEqual(pillFor(DOC.rows[3]), { label: "LOST", tone: "lost" });
    assert.deepEqual(pillFor(DOC.rows[0], true), { label: "✓ FIXED", tone: "ok" });
    assert.equal(ARCHIVE_WORD, "ARCHIVE");
    assert.equal(ARCHIVE_TIP, "Deleted on PixAI. This is the only copy.");
  });
  test("only the action that applies; READ_ONLY takes the re-download, never the rebuild", () => {
    assert.equal(rowAction(DOC.rows[0]), "redownload");
    assert.equal(rowAction(DOC.rows[1]), "rebuild");
    assert.equal(rowAction(DOC.rows[3]), null);                // a LOST row never offers one
    assert.equal(rowAction(DOC.rows[0], true), null);
    assert.equal(rowAction(DOC.rows[1], true), "rebuild");
  });
});

describe("LOST (W5a)", () => {
  test("the one line, with the date the flag was last rewritten", () => {
    assert.equal(lostLine(DOC.rows[3]),
      "Broken here, and gone from your PixAI history as of Oct 2. There's no copy left to re-download.");
    assert.equal(lostLine({ ...DOC.rows[3], gone_as_of: null }),
      "Broken here, and gone from your PixAI history. There's no copy left to re-download.");
  });
  test("no line once kept, and none for a row only the owner marked lost", () => {
    assert.equal(lostLine({ ...DOC.rows[3], mark: "kept" }), null);
    assert.equal(lostLine(row({ state: "lost", mark: "lost" })), null);
    assert.equal(lostLine(DOC.rows[0]), null);
  });
  test("a day read by hand, so no time zone can move it", () => {
    assert.equal(fmtDay("2026-10-02"), "Oct 2");
    assert.equal(fmtDay("2026-01-31T23:59:59Z"), "Jan 31");
    assert.equal(fmtDay(""), "");
  });
});

describe("the header and the Control Panel row", () => {
  test("'12 broken · 1 lost'", () => {
    assert.equal(headerSummary(DOC), "4 broken · 1 lost");
    assert.equal(headerSummary({ broken: 3, lost: 0 }), "3 broken");
  });
  test("the phone's entry row: '12 · 1 lost ›'", () => {
    assert.equal(entrySummary(DOC), "4 · 1 lost ›");
    assert.equal(entrySummary({ broken: 3, lost: 0 }), "3 ›");
  });
  test("'N broken · Review ▸', the lost count when all are lost, nothing when clean", () => {
    assert.equal(reviewLabel(DOC), "4 broken · Review ▸");
    assert.equal(reviewLabel({ counts: { all: 2 }, broken: 0, lost: 2 }), "2 lost · Review ▸");
    assert.equal(reviewLabel({ counts: { all: 0 }, broken: 0, lost: 0 }), "");
    assert.equal(reviewLabel(null), "");
  });
});

describe("Fix all recoverable (W3c)", () => {
  test("zero-byte, suspect and thumbnail rows; never LOST, never archive-only", () => {
    const p = fixPlan(DOC, false);
    assert.deepEqual(p.redownload, ["a", "c"]);
    assert.deepEqual(p.rebuild, ["b"]);
    assert.equal(p.total, 3);
    assert.equal(p.lost, 1);
    assert.equal(p.bytes, 6000000);
  });
  test("READ_ONLY leaves only the rebuilds; a finished row is not counted again", () => {
    assert.deepEqual(fixPlan(DOC, true).ids, ["b"]);
    assert.deepEqual(fixPlan(DOC, false, { a: true }).redownload, ["c"]);
    assert.equal(fixPlan(DOC, false, { a: true }).bytes, 3000000);
  });
  test("the confirm's lines, in the handoff's order", () => {
    const c = confirmLines({ redownload: ["1", "2", "3"], rebuild: Array(9).fill("t"), total: 12, lost: 1, bytes: 9.2 * 1024 * 1024 });
    assert.equal(c.title, "Fix 12 files?");
    assert.deepEqual(c.lines, [
      "3 re-downloads from PixAI (~9.2 MB) · 9 thumbnails rebuilt here.",
      "1 lost file is left as is. Nothing is deleted.",
    ]);
    assert.equal(c.go, "Fix 12");
  });
  test("Data saver's metered line, only when something downloads", () => {
    const c = confirmLines({ redownload: ["1"], rebuild: [], total: 1, lost: 0, bytes: 3 * 1024 * 1024 }, true);
    assert.deepEqual(c.lines, ["1 re-download from PixAI (~3 MB).", "Nothing is deleted.",
      "~3 MB. You're on a metered connection."]);
    assert.equal(confirmLines({ redownload: [], rebuild: ["t"], total: 1, lost: 2, bytes: null }, true).lines.length, 2);
    assert.equal(confirmLines({ redownload: [], rebuild: ["t"], total: 1, lost: 2, bytes: null }).lines[1],
      "2 lost files are left as is. Nothing is deleted.");
  });
});

describe("progress (W4c)", () => {
  test("'n / N fixed' and the end toast's counts", () => {
    assert.equal(runHeader({ done: 5, total: 12 }), "5 / 12 fixed");
    const res = Array.from({ length: 11 }, (_, i) => ({ media_id: "m" + i, ok: true, action: "rebuild" }))
      .concat([{ media_id: "x", ok: false, action: "redownload" }]);
    assert.equal(endToast({ total: 12, results: res }), "Fixed 11 of 12. 1 couldn't be re-downloaded.");
    assert.equal(endToast({ total: 3, results: [{ ok: true }], stopped: true }), "Fixed 1 of 3. Stopped.");
  });
  test("the byte line and the bar's TRUE fraction", () => {
    const mb = 1024 * 1024;
    assert.equal(bytesLine({ bytes: 1.8 * mb, expect: 3 * mb }), "re-downloading… 1.8 / 3.0 MB");
    assert.equal(bytesLine({ bytes: 300 * 1024, expect: 600 * 1024 }), "re-downloading… 300 / 600 KB");
    assert.equal(bytesLine({ bytes: 0, expect: 0 }), "re-downloading…");
    assert.equal(byteFraction({ bytes: 3, expect: 4 }), 0.75);
    assert.equal(byteFraction({ bytes: 3, expect: 0 }), null);   // no total, no gauge
  });
});
