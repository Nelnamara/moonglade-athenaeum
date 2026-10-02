import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  EDL_FPS, EDL_CLIP_FILE_RE, EDL_BED_NAME_RE, CSV_HEADER,
  codeAscii, asciiText, boardSlug, framesOf, timecode, assignReels, csvField, bedZipName, edlPlan,
} from "../src/loom-edl-core.js";
import { splitCardAt } from "../src/loom-mutations.js";

/* THE EDITOR HANDOFF EXPORT (Session P, P4; BUILD-w5-p §5.1; rulings 6, 7, 8; review F9, N2).
   CMX3600 at 24 fps NON-DROP; source from 00:00:00:00, record from 01:00:00:00, sequential;
   frames rounded ONCE per boundary so records never drift; each shot's ★ take through
   selectedTakeView (its trims; a split half is its own event and file); unrendered shots
   skipped in a comment; the bed as one A event; a CSV with RFC-4180 quoting. */

const SHA = "0123456789abcdef0123456789abcdef01234567";
const card = (id, extra = {}) => ({ id, title: "Shot " + id, status: "done", mode: "I2V", duration: 5, trimIn: 0,
  trimOut: null, resultMid: "7" + id.replace(/\D/g, "").padStart(3, "0"), actualDur: 5, cast: [], refs: [],
  prompt: "prompt " + id, ...extra });
const board = (acts, extra = {}) => ({ name: "Moonwell · ep 1", assets: [],
  acts: acts.map((cards, i) => ({ id: "a" + i, name: "Act " + (i + 1), cards })), ...extra });
const eventLines = (edl) => edl.split("\r\n").filter((l) => /^\d{3}  /.test(l));
const fields = (line) => line.trim().split(/\s+/);

describe("timecode, frames and names", () => {
  test("24 fps non-drop at the boundaries", () => {
    assert.equal(EDL_FPS, 24);
    assert.equal(timecode(23), "00:00:00:23");
    assert.equal(timecode(24), "00:00:01:00");
    assert.equal(timecode(59 * 24), "00:00:59:00");
    assert.equal(timecode(60 * 24), "00:01:00:00");
    assert.equal(timecode(3600 * 24), "01:00:00:00");
    assert.equal(timecode(3600 * 24 + 59 * 24 + 23), "01:00:59:23");
  });
  test("seconds round to the nearest frame, once", () => {
    assert.equal(framesOf(0.4), 10);        // 9.6
    assert.equal(framesOf(1.02), 24);       // 24.48
    assert.equal(framesOf(1.03), 25);       // 24.72
    assert.equal(framesOf(-1), 0);
  });
  test("ASCII names: the code without its dot, titles folded", () => {
    assert.equal(codeAscii("A·01"), "A01");
    assert.equal(codeAscii("A26·03"), "A2603");
    assert.equal(asciiText("Crème brûlée — ☾ night"), "Creme brulee night");
    assert.equal(boardSlug("Moonwell · ep 1"), "moonwell-ep-1");
    assert.equal(boardSlug("☾☾☾"), "storyboard");
  });
  test("reels: {code}_T{take} when it fits and is unique; R001… otherwise (N2)", () => {
    assert.deepEqual(assignReels([{ ascii: "A01", n: 2 }, { ascii: "A02", n: 1 }]), ["A01_T2", "A02_T1"]);
    // the review's own collision: truncating both to 8 characters would make them one reel
    const r = assignReels([{ ascii: "AA100", n: 12 }, { ascii: "AA100", n: 1 }]);
    assert.deepEqual(r, ["R001", "AA100_T1"]);
    assert.equal(new Set(r).size, 2);
    // the same reel asked for twice: both fall back, never share
    const d = assignReels([{ ascii: "A01", n: 1 }, { ascii: "A01", n: 1 }, { ascii: "B01", n: 1 }]);
    assert.deepEqual(d, ["R001", "R002", "B01_T1"]);
    for (const x of d.concat(r)) assert.ok(x.length <= 8, x);
  });
  test("the zip names the route accepts", () => {
    assert.ok(EDL_CLIP_FILE_RE.test("A01_t2.mp4"));
    assert.ok(EDL_CLIP_FILE_RE.test("R001_t12.mp4"));
    assert.ok(!EDL_CLIP_FILE_RE.test("../A01_t2.mp4"));
    assert.ok(!EDL_CLIP_FILE_RE.test("A0123456789_t2.mp4"));
    assert.equal(bedZipName({ file: SHA + ".mp3", name: "Elune — theme (final).mp3" }), "Elune_theme_final.mp3");
    assert.equal(bedZipName({ file: SHA + ".wav", name: "☾☾" }), "music_bed.wav");
    assert.equal(bedZipName({ file: SHA + ".ogg", name: "../../etc/passwd" }), "etcpasswd.ogg");
    assert.ok(EDL_BED_NAME_RE.test("Elune_theme_final.mp3"));
    assert.ok(!EDL_BED_NAME_RE.test(".hidden.mp3"));
  });
  test("CSV fields are RFC 4180", () => {
    assert.equal(csvField("plain"), "plain");
    assert.equal(csvField("a, b"), '"a, b"');
    assert.equal(csvField('say "hi"'), '"say ""hi"""');
    assert.equal(csvField("two\nlines"), '"two\nlines"');
    assert.equal(csvField("cr\rlf"), '"cr\rlf"');
    assert.equal(csvField(3), "3");
    assert.equal(csvField(null), "");
  });
});

describe("edlPlan", () => {
  test("board order; sequential records from 01:00:00:00; source from 00:00:00:00; trims", () => {
    const p = board([[card("c1", { trimIn: 0.4, trimOut: 3.2 }), card("c2")]]);
    const plan = edlPlan(p, {});
    const lines = plan.edl.split("\r\n");
    assert.equal(lines[0], "TITLE: MOONWELL EP 1");
    assert.equal(lines[1], "FCM: NON-DROP FRAME");
    const ev = eventLines(plan.edl).map(fields);
    assert.deepEqual(ev[0], ["001", "A01_T1", "V", "C", "00:00:00:10", "00:00:03:05", "01:00:00:00", "01:00:02:19"]);
    assert.deepEqual(ev[1], ["002", "A02_T1", "V", "C", "00:00:00:00", "00:00:05:00", "01:00:02:19", "01:00:07:19"]);
    assert.ok(plan.edl.includes("* FROM CLIP NAME: A01_t1.mp4\r\n* COMMENT: SHOT C1\r\n"));
    assert.deepEqual(plan.clips, [{ mid: "7001", file: "A01_t1.mp4" }, { mid: "7002", file: "A02_t1.mp4" }]);
    assert.equal(plan.slug, "moonwell-ep-1");
    // the event line's exact columns (the page's own spacing)
    assert.equal(eventLines(plan.edl)[0], "001  A01_T1   V     C        00:00:00:10 00:00:03:05 01:00:00:00 01:00:02:19");
  });
  test("the ★ take is read through selectedTakeView: an Edit Bay trim on the card wins (F9)", () => {
    const takes = [{ id: "t1", n: 1, mid: "7101", trimIn: 0, trimOut: null, dur: 5 },
      { id: "t2", n: 2, mid: "7102", trimIn: 0, trimOut: null, dur: 6, settings: { mode: "FLF", sentPrompt: "sent words" } }];
    const c = card("c1", { resultMid: "7102", actualDur: 6, takes, selectedTake: 2, takeSeq: 2, trimIn: 1, trimOut: 2.5 });
    const plan = edlPlan(board([[c]]), {});
    const ev = fields(eventLines(plan.edl)[0]);
    assert.equal(ev[1], "A01_T2");
    assert.equal(ev[4], "00:00:01:00");
    assert.equal(ev[5], "00:00:02:12");
    assert.deepEqual(plan.clips, [{ mid: "7102", file: "A01_t2.mp4" }]);
    const row = plan.csv.split("\r\n")[1];
    assert.equal(row, "1,A·01,Shot c1,2,A01_t2.mp4,1.000,2.500,1.500,FLF,sent words");
  });
  test("a split's halves are two events and two files of the same clip", () => {
    const p0 = board([[card("c1", { actualDur: 8, duration: 8 })]]);
    const p = splitCardAt(p0, "a0", "c1", 3, "c1b");
    const plan = edlPlan(p, {});
    const ev = eventLines(plan.edl).map(fields);
    assert.equal(ev.length, 2);
    assert.deepEqual(ev.map((e) => [e[1], e[4], e[5], e[6], e[7]]), [
      ["A01_T1", "00:00:00:00", "00:00:03:00", "01:00:00:00", "01:00:03:00"],
      ["A02_T1", "00:00:03:00", "00:00:08:00", "01:00:03:00", "01:00:08:00"],
    ]);
    assert.deepEqual(plan.clips, [{ mid: "7001", file: "A01_t1.mp4" }, { mid: "7001", file: "A02_t1.mp4" }]);
  });
  test("unrendered shots are skipped and listed, by the codes the app shows", () => {
    const p = board([[card("c1"), card("c2", { resultMid: "", status: "todo" }), card("c3", { resultMid: "", status: "todo" })],
      [card("c4", { resultMid: "" })]]);
    const plan = edlPlan(p, {});
    assert.deepEqual(plan.skipped, ["A·02", "A·03", "B·01"]);
    assert.ok(plan.edl.includes("* SKIPPED (no render): A·02 A·03 B·01\r\n"));
    assert.equal(eventLines(plan.edl).length, 1);
    assert.equal(plan.csv.split("\r\n").filter(Boolean).length, 2);
    assert.ok(!edlPlan(board([[card("c1")]]), {}).edl.includes("SKIPPED"));
  });
  test("no cumulative drift over 40 shots: each record in is the previous record out", () => {
    const cards = Array.from({ length: 40 }, (_, i) => card("c" + (i + 1), { actualDur: 1.03, duration: 1.03 }));
    const plan = edlPlan(board([cards]), {});
    const ev = eventLines(plan.edl).map(fields);
    assert.equal(ev.length, 40);
    const tcF = (tc) => { const [h, m, s, f] = tc.split(":").map(Number); return ((h * 60 + m) * 60 + s) * 24 + f; };
    for (let i = 1; i < ev.length; i++) assert.equal(ev[i][6], ev[i - 1][7], "event " + (i + 1));
    // 1.03 s is 24.72 frames, rounded ONCE to 25 per shot: the record track is exactly 40 × 25
    assert.equal(tcF(ev[39][7]) - tcF("01:00:00:00"), 40 * 25);
    assert.equal(plan.cutFrames, 1000);
    for (const e of ev) assert.equal(tcF(e[7]) - tcF(e[6]), tcF(e[5]) - tcF(e[4]), "record length == source length");
  });
  test("the bed is ONE A event over the cut, with its level and its file", () => {
    const p = board([[card("c1"), card("c2")]]);
    const plan = edlPlan(p, { bed: { file: SHA + ".mp3", name: "elune-theme.mp3", dur: 102, db: -8 } });
    const ev = eventLines(plan.edl).map(fields);
    assert.deepEqual(ev[2], ["003", "BED", "A", "C", "00:00:00:00", "00:00:10:00", "01:00:00:00", "01:00:10:00"]);
    assert.ok(plan.edl.includes("* FROM CLIP NAME: elune-theme.mp3\r\n* LEVEL -8 DB\r\n"));
    assert.equal(plan.bedName, "elune-theme.mp3");
    // a bed shorter than the cut ends where it ends
    const short = edlPlan(p, { bed: { file: SHA + ".wav", name: "short", dur: 4, db: -3 } });
    const b = fields(eventLines(short.edl)[2]);
    assert.deepEqual([b[5], b[7]], ["00:00:04:00", "01:00:04:00"]);
    assert.ok(short.edl.includes("* LEVEL -3 DB"));
    // no bed, no A event; no cut, no A event either
    assert.equal(eventLines(edlPlan(p, {}).edl).length, 2);
    assert.equal(edlPlan(board([[card("c1", { resultMid: "" })]]), { bed: { file: SHA + ".mp3", dur: 3, db: -8 } }).bedName, "");
  });
  test("CSV: the exact header and RFC 4180 quoting of titles and prompts", () => {
    const c = card("c1", { title: 'Nel, "the druid"', prompt: "line one\nline two, with a comma" });
    const plan = edlPlan(board([[c]]), {});
    const [head, row] = plan.csv.split("\r\n");
    assert.equal(head, CSV_HEADER);
    assert.equal(head, "order,code,title,take,file,in,out,duration,mode,prompt");
    assert.ok(plan.csv.startsWith(CSV_HEADER + "\r\n"));
    assert.equal(plan.csv.split("\r\n").length, 3, "header, ONE row, the final line end: the quoted newline stays inside its field");
    assert.ok(plan.csv.includes('1,A·01,"Nel, ""the druid""",1,A01_t1.mp4,0.000,5.000,5.000,I2V,"line one\nline two, with a comma"\r\n'));
  });
  test("the card's effective prompt when the take recorded no settings", () => {
    const c = card("c1", { promptOverride: true, promptOverrideText: "hand-edited" });
    assert.ok(edlPlan(board([[c]]), {}).csv.endsWith(",I2V,hand-edited\r\n"));
  });
  test("every name is ASCII; every clip file passes the route's pattern", () => {
    const cards = [card("c1", { title: "Crème — ☾" }), card("c2")];
    const plan = edlPlan(board([cards], { name: "Été ☾ board" }), { bed: { file: SHA + ".flac", name: "Élune.flac", dur: 9, db: -8 } });
    for (const c of plan.clips) assert.ok(EDL_CLIP_FILE_RE.test(c.file), c.file);
    assert.ok(EDL_BED_NAME_RE.test(plan.bedName), plan.bedName);
    // every EDL line but the SKIPPED comment (which uses the app's own codes) is ASCII
    for (const l of plan.edl.split("\r\n")) assert.match(l, /^[\x20-\x7E]*$/, l);
  });
  test("a long code falls back to its reel for the file name, still unique", () => {
    // 27 acts: act 27's letter is "A26", so its 100th shot's code is A26·100 -> "A26100" (6)
    // and a take number in the thousands makes a 12-character reel: the fallback takes over.
    const takes = [{ id: "t1234", n: 1234, mid: "7999", trimIn: 0, trimOut: null, dur: 5 }];
    const acts = Array.from({ length: 27 }, (_, i) => (i === 26
      ? Array.from({ length: 100 }, (_, k) => card("x" + k, k === 99 ? { resultMid: "7999", takes, selectedTake: 1234, takeSeq: 1234 } : { resultMid: "" }))
      : []));
    const plan = edlPlan(board(acts), {});
    assert.equal(fields(eventLines(plan.edl)[0])[1], "R001");
    assert.deepEqual(plan.clips, [{ mid: "7999", file: "A26100_t1234.mp4" }]);
    assert.ok(EDL_CLIP_FILE_RE.test(plan.clips[0].file));
  });
  test("planning never writes the board", () => {
    const p = board([[card("c1", { trimIn: 1 }), card("c2", { resultMid: "" })]], { bed: { file: SHA + ".mp3", dur: 3, db: -8 } });
    const before = JSON.stringify(p);
    edlPlan(p, { bed: p.bed });
    assert.equal(JSON.stringify(p), before);
  });
});
