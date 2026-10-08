import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  SHOT_TITLE_MAX, SHOT_SECONDS, FROM_SELECTION,
  trimTitle, actNonce, hasShotsAct, shotsActName, shotsFromPictures, appendShotsAct,
} from "../src/loom-shots-core.js";
import { newCardShape, isCatalogMediaId, shotPayload } from "../src/loom-core.js";
import { parseCastIdsFromSearch } from "../src/loom-mutations.js";
import { takesOf, selectedTakeOf, inFlight, needsRender, anchorInfo, unsendableRefs } from "../src/loom-takes-core.js";
import { SHOTS_HANDOFF_CAP, readShotsMeta } from "../src/loom-url.js";

/* A COLLECTION AS ORDERED SHOTS (Session P, P5; BUILD-w5-p §5.3; rulings 4, 9, 10; review N4).
   One act of image-to-video shots, one per picture, in order: open frame = the picture, 5 s,
   titled from its prompt, status todo -- and NOTHING rendered: no result, no takes, no
   pending marker, no anchor. The act carries the hand-off's nonce so a reload or a second tab
   never adds it twice. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(path.join(here, "../master-storyboard.jsx"), "utf8").replace(/\r\n/g, "\n");
const ids = (() => { let k = 0; return (kind) => kind + "-" + (++k); })();
const PICS = [
  { id: "733917871331404290", prompt: "1girl, solo, moonwell at night, glowing water, looking at viewer, long silver hair, detailed" },
  { id: "733917871331404291", prompt: "Owl on the lectern.\nsecond line is ignored" },
  { id: "local_0123456789ab", prompt: "" },
];

describe("trimTitle", () => {
  test("first line, cut at a word boundary to <= 60, trailing punctuation stripped", () => {
    const t = trimTitle(PICS[0].prompt, 1);
    assert.ok(t.length <= SHOT_TITLE_MAX, t);
    assert.equal(t, "1girl, solo, moonwell at night, glowing water, looking at");
    assert.equal(trimTitle(PICS[1].prompt, 2), "Owl on the lectern");
  });
  test("edge cases", () => {
    assert.equal(trimTitle("", 3), "Picture 3");
    assert.equal(trimTitle(null, 1), "Picture 1");
    assert.equal(trimTitle("   \n\n  ", 7), "Picture 7");
    assert.equal(trimTitle("...!!!", 2), "Picture 2", "punctuation alone is nothing");
    assert.equal(trimTitle("\n\nlater first line", 1), "later first line", "the first line with words");
    assert.equal(trimTitle("x".repeat(80), 1), "x".repeat(60), "one long word is cut hard at 60");
    assert.equal(trimTitle("a b c,", 1), "a b c");
    assert.equal(trimTitle("portrait (close up)", 1), "portrait (close up)", "a closing bracket is kept");
    assert.equal(trimTitle("  lots   of    space  ", 1), "lots of space");
    const exact = "y".repeat(60);
    assert.equal(trimTitle(exact, 1), exact);
    assert.equal(trimTitle("word ".repeat(12) + "tail", 1).length <= 60, true);
  });
});

describe("shotsFromPictures", () => {
  const act = shotsFromPictures(PICS, { actNumber: 4, name: "Loom stills", nonce: "n1a2b3", idFor: ids });
  test("one act, named for its collection, carrying the nonce", () => {
    assert.equal(act.name, "Act 4 — from ❖ Loom stills");
    assert.deepEqual(act.source, { kind: "collection", name: "Loom stills", nonce: "n1a2b3" });
    assert.equal(act.collapsed, false);
    assert.ok(act.id.startsWith("act-"));
    assert.equal(act.cards.length, 3);
  });
  test("each shot: I2V, 5 s, todo, open frame = the picture, titled from its prompt", () => {
    act.cards.forEach((c, i) => {
      assert.equal(c.mode, "I2V");
      assert.equal(c.duration, SHOT_SECONDS);
      assert.equal(SHOT_SECONDS, 5);
      assert.equal(c.status, "todo");
      assert.deepEqual(c.openFrame, { mediaId: PICS[i].id, thumbId: "", source: "", desc: "", tag: "" });
    });
    assert.deepEqual(act.cards.map((c) => c.title),
      ["1girl, solo, moonwell at night, glowing water, looking at", "Owl on the lectern", "Picture 3"]);
    assert.equal(new Set(act.cards.map((c) => c.id)).size, 3, "fresh ids from idFor");
  });
  test("newCard-shaped: every default field of a new shot, and nothing else set", () => {
    const c = act.cards[0];
    const blank = newCardShape(c.id, {});
    assert.deepEqual(Object.keys(c).sort(), Object.keys(blank).sort());
    for (const k of Object.keys(blank)) {
      if (["mode", "duration", "status", "title", "openFrame"].includes(k)) continue;
      assert.deepEqual(c[k], blank[k], k);
    }
  });
  test("NOTHING RENDERED: no result, no takes, no pending marker, no anchor", () => {
    for (const c of act.cards) {
      for (const k of ["resultMid", "takes", "selectedTake", "takeSeq", "pendingTaskId", "pendingSubmitId",
        "pendingSettings", "pendingAnchor", "pendingBoard", "pendingQuote", "genStartedAt", "anchor",
        "anchorKept", "attempts", "actualDur", "imported"]) {
        assert.ok(!(k in c), k + " must not be on a shot made from a picture");
      }
      assert.deepEqual(takesOf(c), []);
      assert.equal(selectedTakeOf(c), null);
      assert.equal(inFlight(c), false);
      assert.equal(needsRender(c), true, "it waits for the owner's own Render");
      assert.equal(anchorInfo(c, new Map()).state, "none");
    }
  });
  test("a local_ picture becomes a shot the render path refuses before pricing (ruling 4)", () => {
    const c = act.cards[2];
    const project = { assets: [], draft: false, acts: [act] };
    const payload = shotPayload({ c, code: "D·03", ai: 3, ci: 2 }, project, () => null);
    assert.deepEqual(unsendableRefs(payload), ["local_0123456789ab"]);
    const ok = shotPayload({ c: act.cards[0], code: "D·01", ai: 3, ci: 0 }, project, () => null);
    assert.deepEqual(unsendableRefs(ok), []);
    // the card mark the board draws for it is the ruling's words
    assert.match(SRC, /imported picture — can't be sent to PixAI yet/);
  });
  test("a plain selection is named as one, without the collection mark", () => {
    const a = shotsFromPictures([PICS[0]], { actNumber: 2, name: FROM_SELECTION, nonce: "x", idFor: ids });
    assert.equal(a.name, "Act 2 — from your selection");
    assert.equal(shotsActName(3, ""), "Act 3 — from your selection");
    assert.equal(shotsFromPictures([], { actNumber: 1, name: "C", nonce: "n" }).cards.length, 0);
  });
});

describe("the nonce: one act per hand-off, however often it is read", () => {
  const act = shotsFromPictures(PICS, { actNumber: 2, name: "Loom stills", nonce: "abc123", idFor: ids });
  const board = { name: "b", assets: [], acts: [{ id: "a1", name: "Act 1", cards: [] }] };
  test("the first read appends; a reload or a second tab adds nothing", () => {
    const one = appendShotsAct(board, act);
    assert.equal(one.added, true);
    assert.equal(one.project.acts.length, 2);
    assert.equal(actNonce(one.project.acts[1]), "abc123");
    assert.equal(hasShotsAct(one.project, "abc123"), true);
    const again = appendShotsAct(one.project, shotsFromPictures(PICS, { actNumber: 3, name: "Loom stills", nonce: "abc123", idFor: ids }));
    assert.equal(again.added, false);
    assert.equal(again.project, one.project, "the very same board, untouched");
  });
  test("a different nonce is a different hand-off; a hand-made act has none", () => {
    assert.equal(hasShotsAct(board, "abc123"), false);
    assert.equal(hasShotsAct(board, ""), false);
    assert.equal(actNonce({ name: "Act 1" }), "");
    const before = JSON.stringify(board);
    appendShotsAct(board, act);
    assert.equal(JSON.stringify(board), before, "appending never mutates the board it was given");
  });
});

describe("the link: sanitised, grammar-checked and capped (review N4, ruling 10)", () => {
  test("the ids ride the cast hand-off's own sanitiser and grammar, in order", () => {
    const search = "?board=b1&shots=733917871331404290,local_0123456789ab,..%2Fx,99a,local_ZZ&from=Loom%20stills&n=abc";
    const got = parseCastIdsFromSearch(search, "shots").filter(isCatalogMediaId);
    assert.deepEqual(got, ["733917871331404290", "local_0123456789ab"]);
    assert.deepEqual(parseCastIdsFromSearch(search), [], "the cast key is untouched by a shots link");
  });
  test("from and nonce", () => {
    assert.deepEqual(readShotsMeta("?shots=1&from=Loom%20stills&n=abc_12-Z"), { from: "Loom stills", nonce: "abc_12-Z" });
    assert.deepEqual(readShotsMeta("?from=%0Abad%07name&n=has%20space"), { from: "badname", nonce: "" });
    assert.equal(readShotsMeta("?from=" + "x".repeat(200)).from.length, 64);
    assert.deepEqual(readShotsMeta(""), { from: "", nonce: "" });
  });
  test("the cap is ruling 10's one number", () => {
    assert.equal(SHOTS_HANDOFF_CAP, 60);
  });
  test("adoptShotsHandoff: read once, sanitised, capped, confirmed, idempotent, cleared", () => {
    const m = SRC.match(/const adoptShotsHandoff = async \(project\) => \{[\s\S]*?\n  \};/);
    assert.ok(m, "adoptShotsHandoff is a named function the mount effect calls");
    const body = m[0];
    assert.match(body, /parseCastIdsFromSearch\(location\.search, "shots"\)\.filter\(isCatalogMediaId\)/);
    assert.match(body, /SHOTS_HANDOFF_CAP/);
    assert.match(body, /window\.confirm\(/, "one confirm names the collection and the count before anything is appended");
    assert.match(body, /hasShotsAct\(/);
    assert.match(body, /appendShotsAct\(/);
    assert.match(body, /buildLoomUrl\(\{ shots: null, from: null, n: null \}, location\.search, location\.pathname\)/);
    assert.match(body, /\/api\/loom\/prompts\?ids=/, "titles come from the read-only local lookup");
    assert.ok(body.indexOf("window.confirm(") < body.indexOf("appendShotsAct("), "confirm before appending");
    assert.match(SRC, /useEffect\(\(\) => \{ adoptShotsHandoff\(project\); \}, \[project\]\);/);
  });
});
