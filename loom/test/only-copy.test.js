import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  ONLY_COPY_TIERS, onlyCopyMembers, onlyCopyNote, onlyCopyShort, trashOnlyCopyNote,
} from "../../gallery/src/lib/onlyCopy.js";

/* #66, the owner's ruling on the 2026-10-03 walk: archive-only pictures (PixAI no longer has them)
   are WARNED about, not kept back. The bulk "Delete locally" and Duplicate Review take them with the
   rest; the confirm names them first. The server half is dev/tests/test_archive_only_guard.py, which also
   proves what the wording promises: the Trash's Restore brings back the picture and its catalog row,
   and Duplicate Review's Undo does the same. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

describe("the warning's words", () => {
  test("the owner's sentence, then what really happens", () => {
    assert.equal(onlyCopyNote(3, 5),
      "3 of these are the only copy — PixAI no longer has them. They go to the Trash with the rest, "
      + "and the Trash can restore them.");
    assert.equal(onlyCopyNote(1, 5),
      "1 of these is the only copy — PixAI no longer has it. It goes to the Trash with the rest, "
      + "and the Trash can restore it.");
  });
  test("one picture, or all of them, has no 'rest'", () => {
    assert.equal(onlyCopyNote(1, 1),
      "This is the only copy — PixAI no longer has it. It goes to the Trash, and the Trash can restore it.");
    assert.equal(onlyCopyNote(2, 2),
      "2 of these are the only copy — PixAI no longer has them. They go to the Trash, and the Trash can "
      + "restore them.");
  });
  test("Duplicate Review's road is _duplicates/ and its Undo", () => {
    assert.equal(onlyCopyNote(2, 3, "duplicates"),
      "2 of these are the only copy — PixAI no longer has them. They go to _duplicates/ with the rest, "
      + "and Undo puts them back.");
  });
  test("nothing to say when none is an only copy", () => {
    assert.equal(onlyCopyNote(0, 4), "");
    assert.equal(onlyCopyNote(undefined, 4), "");
    assert.equal(onlyCopyShort(0), "");
    assert.equal(onlyCopyShort(1), "1 is the only copy");
    assert.equal(onlyCopyShort(3), "3 are only copies");
  });
});

describe("which members of a duplicate group are only copies", () => {
  const g = (matchType, flags) => ({
    matchType,
    members: flags.map((a, i) => ({ path: "p" + i, media_id: String(i), archive_only: a })),
  });
  test("an archive-only member other than the keeper, in the tiers of different pictures", () => {
    assert.deepEqual(onlyCopyMembers(g("same_seed", [false, true, true]), "p0").map((m) => m.path), ["p1", "p2"]);
    assert.deepEqual(onlyCopyMembers(g("near_duplicate", [false, true]), "p0").map((m) => m.path), ["p1"]);
    assert.deepEqual(onlyCopyMembers(g("same_seed", [true, false]), "p0"), [], "the keeper stays");
  });
  test("never in the byte-identical tiers: the keeper holds the same bytes", () => {
    assert.deepEqual(onlyCopyMembers(g("same_media", [false, true]), "p0"), []);
    assert.deepEqual(onlyCopyMembers(g("identical_file", [false, true]), "p0"), []);
    assert.deepEqual(Object.keys(ONLY_COPY_TIERS).sort(), ["near_duplicate", "same_seed"]);
  });
});

describe("the screens warn and do not block", () => {
  const walk = (dir) => readdirSync(dir).flatMap((n) => {
    const p = path.join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : /\.(jsx?|mjs)$/.test(n) ? [p] : [];
  });
  test("nothing in the gallery keeps an only copy back any more", () => {
    for (const f of walk(SRC)) {
      const t = readFileSync(f, "utf8");
      for (const word of ["kept_archive_only", "include_archive_only", "keptBack", "PROTECTS_ARCHIVE"]) {
        assert.ok(!t.includes(word), path.relative(SRC, f) + " still says " + word);
      }
    }
  });
  test("the bulk Delete locally asks the route how many are only copies, BEFORE its confirm", () => {
    const a = src("components/ActionsMenu.jsx");
    const at = a.indexOf("const deleteLocal = run(async () => {");
    const body = a.slice(at, a.indexOf("\n  });", at));
    const preview = body.indexOf("preview: true");
    const ask = body.indexOf("window.confirm(");
    const send = body.indexOf('apiPost("/api/delete-local", { media_ids: ids })');
    assert.ok(at >= 0 && preview > 0 && ask > preview && send > ask, "preview, then confirm, then delete");
    assert.match(body, /onlyCopyNote\(/);
  });
  test("Duplicate Review resolves every member but the keeper", () => {
    const h = src("hooks/useDuplicateReview.js");
    const at = h.indexOf("const buildResolution = (g) => {");
    const body = h.slice(at, h.indexOf("\n  };", at));
    assert.match(body, /\.filter\(\(m\) => m\.path !== keeperPath\)/);
    assert.doesNotMatch(body, /archive_only|onlyCopy/);
  });
  test("its confirms name the only copies", () => {
    const desk = src("components/DuplicateReviewOverlay.jsx");
    const phone = src("components/DuplicateReviewMobile.jsx");
    assert.match(desk, /onlyCopyNote\(autoOnlyCopyCount, autoFileCount, "duplicates"\)/);
    assert.match(desk, /onlyCopyShort\(/);
    assert.match(phone, /onlyCopyNote\(autoOnlyCopyCount, autoFileCount, "duplicates"\)/);
    assert.match(phone, /onlyCopyNote\(confirmOnlyCopies, confirmRemoveCount, "duplicates"\)/);
  });
  test("the single picture's own confirm still names it the last copy", () => {
    const d = src("hooks/useImageDetails.js");
    assert.match(d, /last copy of it anywhere/);
    assert.match(d, /apiPost\("\/api\/delete-local", \{ media_ids: \[mediaId\] \}\)/);
  });
});

describe("the Trash's Delete forever and Empty trash name the only copies (the last step, #66)", () => {
  test("the owner's sentence is the same one; what follows says nothing can bring them back", () => {
    assert.equal(onlyCopyNote(3, 5, "forever"),
      "3 of these are the only copy — PixAI no longer has them. They are deleted for good, and nothing can "
      + "bring them back.");
    assert.equal(onlyCopyNote(1, 5, "forever"),
      "1 of these is the only copy — PixAI no longer has it. It is deleted for good, and nothing can bring "
      + "it back.");
    assert.equal(onlyCopyNote(1, 1, "forever"),
      "This is the only copy — PixAI no longer has it. It is deleted for good, and nothing can bring it back.");
  });
  test("it never promises a restore the Trash cannot give after this step", () => {
    for (const [k, n] of [[1, 1], [1, 4], [4, 4], [2, 9]]) {
      assert.ok(!/restore|puts .* back|to the Trash/.test(onlyCopyNote(k, n, "forever")), onlyCopyNote(k, n, "forever"));
    }
  });
  test("the head is byte-for-byte the bulk delete's", () => {
    const head = (t) => t.split(" — ")[0];
    for (const [k, n] of [[1, 1], [1, 4], [4, 4], [2, 9]]) {
      assert.equal(head(onlyCopyNote(k, n, "forever")), head(onlyCopyNote(k, n)));
    }
  });

  const flags = new Map([["a", true], ["b", true], ["c", false], ["d", false]]);
  test("Delete forever counts the selected files the list marked, across pages", () => {
    assert.equal(trashOnlyCopyNote("selected", { total: 90, onlyTotal: 7, ids: ["a", "c", "b"], flags }),
      onlyCopyNote(2, 3, "forever"));
    assert.equal(trashOnlyCopyNote("selected", { total: 90, onlyTotal: 7, ids: ["c", "d"], flags }), "");
    assert.equal(trashOnlyCopyNote("selected", { total: 90, onlyTotal: 7, ids: ["a"], flags }),
      onlyCopyNote(1, 1, "forever"));
  });
  test("an id the list never showed is not claimed to be an only copy", () => {
    assert.equal(trashOnlyCopyNote("selected", { total: 3, onlyTotal: 0, ids: ["zzz"], flags }), "");
    assert.equal(trashOnlyCopyNote("selected", { total: 3, onlyTotal: 0, ids: ["a"], flags: undefined }), "");
  });
  test("Empty trash uses the whole trash's count, not the page's", () => {
    assert.equal(trashOnlyCopyNote("all", { total: 12040, onlyTotal: 31, ids: [], flags }),
      onlyCopyNote(31, 12040, "forever"));
    assert.equal(trashOnlyCopyNote("all", { total: 12040, onlyTotal: 0, ids: [], flags }), "");
  });
  test("the Trash overlay reads the list's flags and puts the sentence in front of the typed-DELETE prompt", () => {
    const o = src("components/ControlPanelOverlay.jsx");
    assert.match(o, /import \{ trashOnlyCopyNote \} from "\.\.\/lib\/onlyCopy\.js";/);
    assert.match(o, /d\.archive_only_total/);
    assert.match(o, /onlyFlags\.current\.set\(it\.media_id, !!it\.archive_only\)/);
    const prompt = o.indexOf("{onlyNote ? onlyNote");
    assert.ok(prompt > 0 && prompt < o.indexOf("Type DELETE to permanently", prompt) + 1);
    assert.ok(o.indexOf("Type DELETE to permanently", prompt) - prompt < 40, "the note leads the same prompt");
  });
  test("the phone's Control tab opens this same Trash, so it says the same thing", () => {
    assert.match(src("components/ControlMobile.jsx"), /<TrashSubOverlay /);
  });
});
