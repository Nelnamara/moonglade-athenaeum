import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  CASTLIB_KEY, MEMBER_SYNC_FIELDS, emptyLibrary, parseLibrary, memberFromAsset, assetFromMember, tagOnBoard,
  shotsUsing, boardLibIds, usageOf, libraryRows, rowMeta, untickQuestion, tickMember, untickAsset, withLibId,
  syncPatch, addMember, editMember, editCopies, ticks, handoffCast, newMemberAsset,
} from "../src/loom-cast-library.js";
import { stripInFlight } from "../src/loom-takes-core.js";

/* THE CAST LIBRARY (Session P, NOTES P7; the Loom Handoff page's "👤 CAST LIBRARY · tick = in
   this storyboard" panel). Pure views and patches -- the app's library hook does the reads and
   the compare-and-swap writes around them. */

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = readFileSync(path.join(here, "fixtures", "board-legacy.json"), "utf8");
const legacy = () => JSON.parse(FIXTURE);

const libWith = (...members) => ({ v: 1, members });
const member = (libId, extra = {}) => ({ libId, name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "555", thumbId: "", source: "", lock: true, ...extra });

describe("the library value", () => {
  test("one account-side key; a missing key is an empty library; junk is unreadable (never written over)", () => {
    assert.equal(CASTLIB_KEY, "storyboard:v2:castlib");
    assert.deepEqual(parseLibrary(null), emptyLibrary());
    assert.deepEqual(parseLibrary(JSON.stringify({ v: 1, members: [member("L1")] })).members.map((m) => m.libId), ["L1"]);
    assert.equal(parseLibrary("{not json"), null);
    assert.equal(parseLibrary(JSON.stringify({ v: 1 })), null, "no members array");
    assert.equal(parseLibrary(JSON.stringify([1, 2])), null);
    assert.deepEqual(parseLibrary(JSON.stringify({ v: 1, members: [null, { name: "no id" }, member("L2")] })).members.map((m) => m.libId), ["L2"],
      "a member with no libId is not a member");
  });
});

describe("a legacy board: its assets are board-only rows, and no view writes anything", () => {
  test("every asset shows as a ticked, this-storyboard-only row; the board is byte-identical after every view", () => {
    const p = legacy();
    const rows = libraryRows(emptyLibrary(), p, []);
    assert.deepEqual(rows.map((r) => [r.key, r.boardOnly, r.ticked, r.boards]),
      [["board:as1", true, true, 1], ["board:as2", true, true, 1], ["board:as3", true, true, 1]]);
    assert.deepEqual(rows[0].usedBy.map((u) => u.code), ["A·01", "C·01"], "Lead is cast in c1 (A·01) and c4 (C·01)");
    assert.equal(rowMeta(rows[0]), "@image1 · this storyboard only · A·01 C·01");
    assert.equal(rowMeta(rows[2]), "@audio1 · this storyboard only");
    libraryRows(libWith(member("L9")), p, [{ id: "b2", project: legacy() }]);
    shotsUsing(p, "as1"); boardLibIds(p); usageOf([{ id: "x", project: p }]); rowMeta(rows[0]); untickQuestion(rows[0]);
    ticks(p, "L9"); tagOnBoard(p.assets, member("L9"));
    assert.equal(JSON.stringify(p), JSON.stringify(JSON.parse(FIXTURE)), "the board must come out of every view byte-identical");
  });
  test("an asset whose libId the library does not hold is still a board-only row (an imported board, a failed write)", () => {
    const p = legacy();
    p.assets[1] = { ...p.assets[1], libId: "Lgone" };
    const rows = libraryRows(emptyLibrary(), p, []);
    assert.equal(rows[1].boardOnly, true);
    assert.equal(rows[1].libId, "Lgone", "acting on it re-adds that member under the same id");
  });
});

describe("library rows: ticks, the meta line and 'in N storyboards'", () => {
  test("members first (ticked or not), then the board's own rows; the tick is a copy carrying the libId", () => {
    const p = legacy();
    p.assets.push({ id: "as9", name: "Nel", kind: "image", tag: "@image3", mediaId: "555", thumbId: "", source: "", lock: true, libId: "L1" });
    p.acts[0].cards[1].cast = ["as9"];
    const lib = libWith(member("L1"), member("L2", { name: "Maera", tag: "@image2" }));
    const others = [{ id: "b2", project: { name: "Ep 2", acts: [], assets: [{ id: "q", libId: "L1" }, { id: "r", libId: "L2" }] } },
      { id: "b3", project: { name: "Ep 3", acts: [], assets: [{ id: "q", libId: "L1" }, { id: "q2", libId: "L1" }] } }];
    const rows = libraryRows(lib, p, others);
    assert.deepEqual(rows.map((r) => r.key), ["lib:L1", "lib:L2", "board:as1", "board:as2", "board:as3"]);
    assert.equal(rows[0].ticked, true);
    assert.equal(rows[0].boards, 3, "this board + b2 + b3 (b3 twice still counts once)");
    assert.equal(rows[0].tag, "@image3", "a ticked member shows this board's tag");
    assert.equal(rowMeta(rows[0]), "@image3 · in 3 storyboards · A·02");
    assert.equal(rows[1].ticked, false);
    assert.equal(rows[1].boards, 1);
    assert.equal(rowMeta(rows[1]), "@image2 · in 1 storyboard");
    assert.equal(libraryRows(lib, p, null)[0].boards, null, "while the other boards are still being read");
    assert.equal(rowMeta(libraryRows(lib, p, null)[0]), "@image3 · in … storyboards · A·02");
  });
  test("usage count", () => {
    const m = usageOf([{ id: "a", project: { assets: [{ libId: "L1" }] } }, { id: "b", project: { assets: [{ libId: "L1" }, { libId: "L2" }] } },
      { id: "c", project: null }, { id: "d", project: { assets: [{}] } }]);
    assert.deepEqual([...m.keys()].sort(), ["L1", "L2"]);
    assert.equal(m.get("L1").length, 2);
    assert.equal(m.get("L2").length, 1);
  });
});

describe("tick: copy the member in, keep its tag when free here", () => {
  test("a free tag is kept; the copy carries every member field, this board's id and the libId", () => {
    const p = { name: "x", acts: [], assets: [{ id: "a1", kind: "image", tag: "@image2" }] };
    const out = tickMember(p, member("L1"), "new1");
    assert.deepEqual(out.assets[1], { libId: "L1", name: "Nelnamara", kind: "image", tag: "@image1", mediaId: "555", thumbId: "", source: "", lock: true, id: "new1" });
    assert.equal(p.assets.length, 1, "the input board is not written");
  });
  test("a tag taken on this board is renamed to the next free tag of the member's kind", () => {
    const p = { acts: [], assets: [{ id: "a1", kind: "image", tag: "@image1" }, { id: "a2", kind: "image", tag: "@image4" }, { id: "a3", kind: "audio", tag: "@audio1" }] };
    assert.equal(tickMember(p, member("L1"), "n").assets[3].tag, "@image5");
    assert.equal(tickMember(p, member("L2", { kind: "audio", tag: "@audio1" }), "n").assets[3].tag, "@audio2");
    assert.equal(tickMember(p, member("L3", { kind: "video", tag: "@image4" }), "n").assets[3].tag, "@video1");
  });
  test("ticking a member already ticked here changes nothing", () => {
    const p = tickMember({ acts: [], assets: [] }, member("L1"), "n1");
    assert.equal(tickMember(p, member("L1"), "n2"), p);
  });
});

describe("untick: remove it here and drop its id from the named shots only", () => {
  test("only the shots that cast it change; the others are the very same objects", () => {
    const p = legacy();
    const before = JSON.parse(JSON.stringify(p));
    const out = untickAsset(p, "as1");
    assert.deepEqual(out.assets.map((a) => a.id), ["as2", "as3"]);
    const c1 = out.acts[0].cards[0], c4 = out.acts[2].cards[0];
    assert.deepEqual(c1.cast, []);
    assert.deepEqual(c4.cast, ["as2"]);
    assert.equal(out.acts[1], p.acts[1], "an act with no shot using it is untouched (same object)");
    assert.equal(out.acts[0].cards[1], p.acts[0].cards[1], "a shot that does not use it is untouched");
    assert.equal(out.acts[2].cards[1], p.acts[2].cards[1]);
    assert.deepEqual(p, before, "the input board is not written");
    assert.deepEqual(shotsUsing(out, "as1"), [], "nothing dangles");
  });
  test("the confirm names the shots, in the page's words; an unused member asks nothing", () => {
    const rows = libraryRows(emptyLibrary(), legacy(), []);
    assert.equal(untickQuestion(rows[0]), "Lead is used by A·01, C·01. Remove from this storyboard anyway?");
    assert.equal(untickQuestion(rows[2]), "");
  });
  test("unticking an asset that is not on the board changes nothing", () => {
    const p = legacy();
    assert.equal(untickAsset(p, "nope"), p);
  });
});

describe("materialise and edit: only that member's copy changes", () => {
  test("a legacy asset becomes a member with every field but its id; the board asset gains the libId", () => {
    const p = legacy();
    const m = memberFromAsset(p.assets[1], "Lnew");
    assert.deepEqual(m, { name: "Set", kind: "image", tag: "@image2", thumbId: "th_set", source: "", lock: false, libId: "Lnew" });
    const out = withLibId(p, "as2", "Lnew");
    assert.equal(out.assets[1].libId, "Lnew");
    assert.equal(out.assets[0], p.assets[0]);
    assert.equal(out.acts, p.acts, "shots are untouched: their cast ids still name the same asset");
    assert.deepEqual(assetFromMember(m, "zz", "@image7"), { ...m, id: "zz", tag: "@image7", libId: "Lnew" });
  });
  test("an edit carries the picture and the lock, never the name, tag or kind", () => {
    assert.deepEqual(MEMBER_SYNC_FIELDS, ["mediaId", "thumbId", "source", "lock"]);
    assert.deepEqual(syncPatch({ name: "x", tag: "@image9", kind: "audio", mediaId: "7", lock: 0 }), { mediaId: "7", lock: false });
  });
  test("editMember patches that member; editCopies patches that member's copy on a board and nothing else", () => {
    const lib = libWith(member("L1"), member("L2"));
    const lib2 = editMember(lib, "L2", { lock: false, mediaId: "777", name: "ignored" });
    assert.equal(lib2.members[0], lib.members[0]);
    assert.deepEqual(lib2.members[1], { ...lib.members[1], lock: false, mediaId: "777" });
    assert.equal(editMember(lib, "L404", { lock: false }), lib);
    const p = legacy();
    p.assets.push({ id: "as9", name: "Nel", kind: "image", tag: "@image3", mediaId: "555", lock: true, libId: "L2" });
    const before = JSON.stringify(p);
    const out = editCopies(p, "L2", { mediaId: "777", lock: false, name: "ignored" });
    assert.deepEqual(out.assets[3], { ...p.assets[3], mediaId: "777", lock: false });
    for (let i = 0; i < 3; i++) assert.equal(out.assets[i], p.assets[i]);
    assert.equal(out.acts, p.acts, "no shot is touched");
    assert.equal(JSON.stringify(p), before);
    assert.equal(editCopies(p, "L1", { lock: false }), p, "a board that does not tick it is returned as it was");
  });
  test("addMember adds once", () => {
    const lib = addMember(emptyLibrary(), member("L1"));
    assert.equal(lib.members.length, 1);
    assert.equal(addMember(lib, member("L1", { name: "dupe" })), lib);
  });
});

describe("⧉ Duplicate copies the ticks", () => {
  test("a duplicated board (stripInFlight of a copy) shows the same ticks and the same rows", () => {
    const p = legacy();
    p.assets.push({ id: "as9", name: "Nel", kind: "image", tag: "@image3", mediaId: "555", lock: true, libId: "L1" });
    const dup = stripInFlight({ ...p, name: p.name + " copy" });
    assert.deepEqual(boardLibIds(dup), ["L1"]);
    const lib = libWith(member("L1"));
    assert.deepEqual(libraryRows(lib, dup, []).map((r) => [r.key, r.ticked]), libraryRows(lib, p, []).map((r) => [r.key, r.ticked]));
    assert.equal(libraryRows(lib, p, [{ id: "dup", project: dup }])[0].boards, 2, "the copy counts as a second storyboard using it");
  });
});

describe("the cast hand-off and + Add make members ticked here", () => {
  test("handoffCast: @image tags continue from the board's highest, locked, each with its own libId", () => {
    let i = 0, j = 0;
    const r = handoffCast(["11", "22"], [{ tag: "@image3" }], () => "a" + (++i), () => "L" + (++j));
    assert.deepEqual(r.assets.map((a) => [a.id, a.tag, a.mediaId, a.lock, a.libId]), [["a1", "@image4", "11", true, "L1"], ["a2", "@image5", "22", true, "L2"]]);
    assert.deepEqual(r.members.map((m) => [m.libId, m.tag, m.mediaId, "id" in m]), [["L1", "@image4", "11", false], ["L2", "@image5", "22", false]]);
  });
  test("newMemberAsset: a picked picture or video", () => {
    assert.deepEqual(newMemberAsset({ mediaId: "9", isVideo: false }, [{ tag: "@image2" }], "x", "L"),
      { id: "x", name: "", kind: "image", tag: "@image3", thumbId: "", source: "", mediaId: "9", lock: false, libId: "L" });
    assert.equal(newMemberAsset({ mediaId: "9", isVideo: true }, [{ tag: "@image2" }], "x", "L").tag, "@video1");
  });
});
