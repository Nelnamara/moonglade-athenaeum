import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* Train a LoRA -- the two rules both train panels share with the server (SCOPE_2026-09-26 E7,
   review fixes). normalizeTrigger is the same five steps as core.normalize_trigger_words
   (tests/test_training_parity.py holds the Python side with these same cases), and the
   counter shows its `length`: UTF-16 code units, the unit PixAI's own 256 / 30 rule counts.
   acceptCostField is what the confirm sends: the AMOUNT the ticked box named, which the
   server refuses (409) once it is no longer the run's price. */

import { acceptCostField, normalizeTrigger } from "../../gallery/src/gen/trainCore.js";

describe("trigger words, as PixAI tidies and counts them", () => {
  const cases = [
    ["  nel   druid  ", "nel druid"],
    ["Nel\r\nDruid", "nel, druid"],
    ["A\n\n\nB", "a, b"],
    ["a,, ,b", "a, b"],
    [",, x ,,", "x"],
    ["Hatsune Miku,  , Aqua Hair\n", "hatsune miku, aqua hair"],
    ["\t tab\tand  space ", "tab and space"],
    [null, ""],
    [undefined, ""],
  ];
  for (const [raw, want] of cases) {
    test(JSON.stringify(raw) + " -> " + JSON.stringify(want), () => {
      assert.equal(normalizeTrigger(raw), want);
    });
  }

  test("the counter's number is the tidied length, an emoji counting 2", () => {
    assert.equal(normalizeTrigger("   " + "y".repeat(25) + "   \n\n  ").length, 25);
    assert.equal(normalizeTrigger("\u{1F319}".repeat(15)).length, 30);
  });
});

describe("the confirm's accept_credit_cost", () => {
  test("nothing for a free run", () => {
    assert.deepEqual(acceptCostField({ is_free: true, price: 25000 }, true), {});
    assert.deepEqual(acceptCostField(null, true), {});
  });

  test("the amount the box named, true only when none could be quoted", () => {
    assert.deepEqual(acceptCostField({ is_free: false, price: 25000 }, true),
      { accept_credit_cost: 25000 });
    assert.deepEqual(acceptCostField({ is_free: false, price: null }, true),
      { accept_credit_cost: true });
    assert.deepEqual(acceptCostField({ is_free: false, price: 25000 }, false),
      { accept_credit_cost: false });
  });
});

/* Session J (Training Handoff, 2026-09-28): the rules the desktop overlay and the phone screen
   share. The server re-checks everything that touches money; these decide what is drawn and
   enabled. */
import {
  GOALS, MAX_IMAGES, addTag, archTabs, basicFooterCost, captionCounts, captionState,
  datasetFits, defaultBase, etaLeftText, etaText, imageProblem, mergeImages, publishTicks,
  removeTag, replaceIn, reuseCandidate, roomLeft, runMatches, runStatus, triggerCheck,
} from "../../gallery/src/gen/trainCore.js";

const img = (id, source) => ({ media_id: String(id), source });

describe("the one grid", () => {
  test("de-duplicated by id, first source kept, never past 100", () => {
    const a = mergeImages([], [img(1), img(2), img(1)], "history");
    assert.equal(a.items.length, 2);
    assert.equal(a.dup, 1);
    const b = mergeImages(a.items, [img(2), img(3)], "upload");
    assert.deepEqual(b.items.map((x) => x.source), ["history", "history", "upload"]);
    const many = Array.from({ length: 120 }, (_, i) => img(i));
    const c = mergeImages([], many, "dataset");
    assert.equal(c.items.length, MAX_IMAGES);
    assert.equal(c.full, 20);
    assert.equal(roomLeft(c.items), 0);
  });
  test("a set that won't fit what's left is dimmed", () => {
    const items = Array.from({ length: 70 }, (_, i) => img(i, "history"));
    assert.equal(datasetFits({ media_ids: Array.from({ length: 30 }, (_, i) => String(100 + i)) }, items), true);
    assert.equal(datasetFits({ media_ids: Array.from({ length: 31 }, (_, i) => String(100 + i)) }, items), false);
    // images already in the grid don't need room
    assert.equal(datasetFits({ media_ids: Array.from({ length: 40 }, (_, i) => String(i + 40)) }, items), true);
  });
  test("a reuse is exactly one whole earlier set", () => {
    const ds = [{ task_id: 501, media_ids: ["1", "2", "3"] }];
    assert.equal(reuseCandidate([img(3, "dataset"), img(1, "dataset"), img(2, "dataset")], ds), "501");
    assert.equal(reuseCandidate([img(1, "dataset"), img(2, "dataset")], ds), "");               // one removed
    assert.equal(reuseCandidate([img(1, "dataset"), img(2, "dataset"), img(3, "history")], ds), ""); // not all from it
    assert.equal(reuseCandidate([img(1, "dataset"), img(2, "dataset"), img(3, "dataset"), img(4, "dataset")], ds), "");
    assert.equal(reuseCandidate([], ds), "");
  });
  test("PixAI's image rule on an upload's own size", () => {
    assert.equal(imageProblem(1024, 1024), null);
    assert.equal(imageProblem(511, 1024), "smaller than 512×512");
    assert.equal(imageProblem(1600, 512), "longer than 3:1");
    assert.equal(imageProblem(1536, 512), null);                        // exactly 3:1 passes
    assert.equal(imageProblem(0, 0), "its size couldn't be read");
  });
});

describe("trigger words and time", () => {
  test("counted tidied, 30 on DiT.2 / DiT.3, 256 at most", () => {
    assert.equal(triggerCheck("nelna druid", true).problem, "needs at least 30 characters on this base");
    assert.equal(triggerCheck("nelna druid", false).ok, true);
    assert.equal(triggerCheck("  ", false).problem, "required");
    assert.equal(triggerCheck("x".repeat(257), false).problem, "too long: 256 characters at most");
    assert.equal(triggerCheck(" a  b", false).spacing, true);
    assert.equal(triggerCheck("a b", false).spacing, false);
  });
  test("PixAI's own estimate reads as minutes; time left rounds", () => {
    assert.equal(etaText({ min: 27, max: 35 }), "about 27–35 minutes");
    assert.equal(etaLeftText(12 * 60000 + 20000), "~12 min");
    assert.equal(etaLeftText(0), "");
  });
});

describe("runs: one pill and one action per row", () => {
  test("the handoff's grammar", () => {
    assert.deepEqual(runStatus({ status: "draft", step: "descriptions" }),
      { label: "Draft · descriptions", tone: "peach", action: "continue", actionLabel: "Continue" });
    assert.equal(runStatus({ status: "waiting" }).label, "Queued");
    assert.equal(runStatus({ status: "running", progress: 62.9 }).label, "Training · 62%");
    assert.equal(runStatus({ status: "failed", mode: "advanced" }).action, "retry");
    assert.equal(runStatus({ status: "failed", mode: "basic" }).action, null);   // no retry route
    assert.equal(runStatus({ status: "done" }).action, "publish");
    const pub = runStatus({ status: "done", model_id: "9", visibility: "public", rebate: true });
    assert.deepEqual([pub.label, pub.action], ["Public · rebates", "use"]);
  });
  test("a retried failure offers no second retry", () => {
    const r = runStatus({ status: "failed", mode: "advanced", retry: { state: "done", new_id: "9" } });
    assert.equal(r.action, null);
    assert.equal(r.label, "Failed · retried");
    const u = runStatus({ status: "failed", mode: "advanced", retry: { state: "ambiguous" } });
    assert.equal(u.action, null);
  });
  test("filters", () => {
    assert.ok(runMatches({ status: "captionReady" }, "draft"));
    assert.ok(!runMatches({ status: "running" }, "draft"));
    assert.ok(runMatches({ status: "done" }, "done"));
    assert.ok(runMatches({ status: "failed" }, "all"));
  });
});

describe("publish ticks", () => {
  test("private one line, public two, the keys the server wants", () => {
    assert.deepEqual(publishTicks("private").map((t) => t.key), ["no_delete"]);
    assert.deepEqual(publishTicks("public").map((t) => t.key), ["no_delete", "no_private"]);
  });
});

describe("descriptions", () => {
  const caps = {
    a: { source: "machine", text: "night elf", machine_text: "night elf" },
    b: { source: "user", text: "my words", machine_text: "machine words" },
    c: { source: "user", text: "same", machine_text: "same" },
  };
  test("PixAI's filters: auto, edited, not described yet", () => {
    assert.equal(captionState("a", caps), "auto");
    assert.equal(captionState("b", caps), "edited");
    assert.equal(captionState("c", caps), "auto");                 // restored = automatic again
    assert.equal(captionState("z", caps), "none");
    assert.deepEqual(captionCounts(["a", "b", "c", "z"], caps), { all: 4, auto: 2, edited: 1, none: 1 });
  });
  test("find / replace and the tag tools stay inside 1,000 characters", () => {
    assert.equal(replaceIn("night elf, night sky", "night", "moon"), "moon elf, moon sky");
    assert.equal(replaceIn("abc", "z", "y"), null);
    assert.equal(replaceIn("x".repeat(600), "x", "yy"), null);        // would pass 1,000
    assert.equal(addTag("a, b", "c"), "a, b, c");
    assert.equal(addTag("a, b", "B"), null);                          // already there
    assert.equal(addTag("x".repeat(999), "yy"), null);
    assert.equal(removeTag("a, b, c", "b"), "a, c");
    assert.equal(removeTag("a", "a"), null);                          // never empties it
  });
});

describe("the base picker and the footer", () => {
  const groups = [
    { arch: "SDXL_MODEL", label: "SDXL", models: [{ version_id: "s1" }], price: 25000, reuse: 12500 },
    { arch: "MMDIT26B_MODEL", label: "DiT.3", recommended: true, models: [{ version_id: "t3" }], price: 100000, reuse: 70000 },
  ];
  test("Recommended first, and the server's default selected", () => {
    assert.deepEqual(archTabs(groups).map((t) => t.arch), ["MMDIT26B_MODEL", "SDXL_MODEL"]);
    assert.deepEqual(defaultBase(groups, "t3"), { tab: 0, base: "t3" });
    assert.deepEqual(defaultBase(groups, "s1"), { tab: 1, base: "s1" });
  });
  test("free trainings strike the price; a reuse names itself; a card is never promised", () => {
    const t3 = archTabs(groups)[0];
    assert.deepEqual(basicFooterCost({ quota: 10, tab: t3, reuse: false }),
      { free: true, price: 0, struck: 100000, badge: "10 times free", reason: "" });
    assert.deepEqual(basicFooterCost({ quota: 0, tab: t3, reuse: true }),
      { free: false, price: 70000, struck: null, badge: "", reason: "reusing a dataset" });
  });
  test("the four goals are PixAI's values", () => {
    assert.deepEqual(GOALS.map((g) => g.value), ["character", "style", "clothing", "other"]);
  });
});

/* Stage A of the desktop build: rejected tiles, the chooser's Runs row, Use, the one confirm. */
import {
  countedItems, loraForDock, markRejected, runsSummary, startLabel,
} from "../../gallery/src/gen/trainCore.js";

describe("a rejected tile stays, peach, and isn't counted", () => {
  test("marked by the server's list, left out of the count, the room and a reuse", () => {
    const items = [img(1, "dataset"), img(2, "dataset"), img(3, "dataset")];
    const marked = markRejected(items, [{ media_id: "2", why: "smaller than 512x512" }]);
    assert.equal(marked.length, 3);
    assert.equal(marked[1].reject, "smaller than 512x512");
    assert.deepEqual(countedItems(marked).map((x) => x.media_id), ["1", "3"]);
    assert.equal(roomLeft(marked), MAX_IMAGES - 2);
    // the whole earlier set is no longer the grid's counted images, so it is not a reuse
    assert.equal(reuseCandidate(marked, [{ task_id: 9, media_ids: ["1", "2", "3"] }]), "");
    assert.equal(markRejected(items, []), items);
  });
  test("a rejected tile does not take one of the 100 places", () => {
    const full = Array.from({ length: 100 }, (_, i) => img(i, "history"));
    const marked = markRejected(full, [{ media_id: "5", why: "longer than 3:1" }]);
    const res = mergeImages(marked, [img(500)], "upload");
    assert.equal(res.added, 1);
    assert.equal(countedItems(res.items).length, MAX_IMAGES);
    assert.equal(mergeImages(res.items, [img(501)], "upload").full, 1);
  });
});

describe("the chooser, Use and the confirm button", () => {
  test("the Runs row counts what is live and what waits, and leaves out zeros", () => {
    assert.equal(runsSummary([]), "");
    assert.equal(runsSummary([
      { status: "running", progress: 40 }, { status: "waiting" }, { status: "draft", step: "images" },
      { status: "done", mode: "advanced" }, { status: "failed", mode: "advanced" },
      { status: "done", mode: "basic", published: true, model_id: "m", visibility: "private" },
    ]), "2 training · 1 draft · 1 to publish · 1 failed");
  });
  test("Use hands the dock a LoRA only when there is one", () => {
    assert.equal(loraForDock({ status: "done" }), null);
    const l = loraForDock({ model_id: 9, version_id: "v9", title: "Tania v2", cover: "/c.jpg",
      trigger_words: "tania_mg", base_version_id: "t3" }, (v) => (v === "t3" ? "MMDIT26B_MODEL" : ""));
    assert.deepEqual(l, { model_id: "9", version_id: "v9", title: "Tania v2", preview_url: "/c.jpg",
      weight: 0.7, trigger_words: "tania_mg", lora_base_model_type: "MMDIT26B_MODEL" });
  });
  test("the confirm button names the quoted amount, never a config number", () => {
    assert.equal(startLabel({ is_free: false, price: 70000 }), "Start training · 70,000");
    assert.equal(startLabel({ is_free: true, price: 100000 }), "Start training · free");
    assert.equal(startLabel({ is_free: false, price: null }), "Start training");
    assert.equal(startLabel({ is_free: false, price: 100000 }, "Retry"), "Retry · 100,000");
  });
});

/* Stage B: Advanced (decision 3c with the owner's 2026-09-28 corrections, BUILD section 5). */
import {
  ADVANCED_DEFAULTS, CAPTION_FILTERS, LR_RANGE, STEP_RANGE, advancedGates, advancedTriggerLine,
  captionFilter, describeLabel, etaForSteps, focusWindow, perImage, stepFocus, trackPercent,
} from "../../gallery/src/gen/trainCore.js";

describe("Advanced: set up", () => {
  test("the peach line counts the tidied trigger out of 256 and names PixAI's spacing rule", () => {
    const empty = advancedTriggerLine("");
    assert.equal(empty.block, true);
    assert.equal(empty.warn, false);
    const short = advancedTriggerLine("nelna druid");
    assert.equal(short.text, "11 / 256: needs at least 30 characters on this base. No double spaces, and no space at the start or end.");
    assert.deepEqual([short.warn, short.block], [true, true]);
    const ok = advancedTriggerLine("a moonlit night elf druid in the grove");
    assert.deepEqual([ok.warn, ok.block, ok.text], [false, false, "38 / 256"]);
    // double or edge spaces are tidied before sending, so they warn but never block
    const spaced = advancedTriggerLine(" a moonlit night elf  druid in the grove");
    assert.deepEqual([spaced.warn, spaced.block], [true, false]);
    assert.equal(advancedTriggerLine("x".repeat(257)).block, true);
  });
});

describe("Advanced: descriptions", () => {
  const ids = Array.from({ length: 12 }, (_, i) => String(100 + i));
  const all = Object.fromEntries(ids.map((m) => [m, { source: "machine", text: "t" + m, machine_text: "t" + m }]));
  const quote = { image_count: 12, total_price: 1800 };
  test("PixAI describes first: describe is the way in, Next waits for every image", () => {
    const g = advancedGates({ mediaIds: ids, captions: {}, quote, saving: 0, status: "draft", busy: "" });
    assert.equal(g.describe, true);
    assert.equal(g.next, false);
    assert.equal(g.left, 12);
    assert.equal(g.whyNoNext, "12 images aren't described yet.");
    const done = advancedGates({ mediaIds: ids, captions: all, quote: { image_count: 0, total_price: 0 }, saving: 0, status: "captionReady", busy: "" });
    assert.deepEqual([done.describe, done.next, done.left], [false, true, 0]);
    // one image added after describing: it needs describing (at its quote) before Next
    const one = advancedGates({ mediaIds: ids.concat(["999"]), captions: all, quote: { image_count: 1, total_price: 150 }, saving: 0, status: "captionReady", busy: "" });
    assert.deepEqual([one.describe, one.next, one.whyNoNext], [true, false, "1 image isn't described yet."]);
  });
  test("describe stays off under 10, while describing, without a quote and while a save is pending", () => {
    const nine = ids.slice(0, 9);
    assert.equal(advancedGates({ mediaIds: nine, captions: {}, quote, status: "draft" }).whyNoDescribe, "Add at least 1 more image first.");
    assert.equal(advancedGates({ mediaIds: ids, captions: {}, quote, status: "captioning" }).describe, false);
    assert.equal(advancedGates({ mediaIds: ids, captions: {}, quote: null, status: "draft" }).describe, false);
    assert.equal(advancedGates({ mediaIds: ids, captions: {}, quote: { image_count: 0, total_price: 0 }, status: "draft" }).describe, false);
    assert.equal(advancedGates({ mediaIds: ids, captions: {}, quote, status: "draft", saving: 1 }).describe, false);
    assert.equal(advancedGates({ mediaIds: ids, captions: all, quote, status: "captionReady", saving: 2 }).next, false);
  });
  test("an unclear describe answer (maybe_started) holds the button off and says check Runs", () => {
    const held = advancedGates({ mediaIds: ids, captions: {}, quote, status: "draft", held: true });
    assert.equal(held.describe, false);
    assert.match(held.whyNoDescribe, /may have started; check Runs/);
    // PixAI's own status still wins once it has moved on
    assert.equal(advancedGates({ mediaIds: ids, captions: {}, quote, status: "captioning", held: true }).whyNoDescribe,
      "PixAI is describing them now.");
  });
  test("the button's count and total come only from PixAI's quote", () => {
    assert.equal(describeLabel(quote), "Describe automatically (12 images) · 1,800");
    assert.equal(describeLabel({ image_count: 1, total_price: 150 }), "Describe automatically (1 image) · 150");
    assert.equal(describeLabel(null), "Describe automatically");
    assert.equal(perImage(quote), 150);
    assert.equal(perImage({ image_count: 0, total_price: 0 }), null);
  });
  test("PixAI's filters, in its order", () => {
    assert.deepEqual(CAPTION_FILTERS.map((f) => f.label), ["All", "Auto", "Edited", "Not described yet"]);
    const caps = { a: { source: "machine", text: "x", machine_text: "x" }, b: { source: "user", text: "y", machine_text: "x" } };
    assert.deepEqual(captionFilter(["a", "b", "c"], caps, "all"), ["a", "b", "c"]);
    assert.deepEqual(captionFilter(["a", "b", "c"], caps, "auto"), ["a"]);
    assert.deepEqual(captionFilter(["a", "b", "c"], caps, "edited"), ["b"]);
    assert.deepEqual(captionFilter(["a", "b", "c"], caps, "none"), ["c"]);
  });
  test("the focus view moves within the set and its strip keeps the image in view", () => {
    assert.equal(stepFocus(0, 38, -1), 0);
    assert.equal(stepFocus(37, 38, 1), 37);
    assert.equal(stepFocus(13, 38, 1), 14);
    assert.equal(stepFocus(3, 0, 1), 0);
    assert.deepEqual(focusWindow(0, 38), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    assert.ok(focusWindow(13, 38).includes(13));
    assert.deepEqual(focusWindow(37, 38).slice(-1), [37]);
    assert.deepEqual(focusWindow(1, 3), [0, 1, 2]);
  });
});

describe("Advanced: parameters", () => {
  test("PixAI's defaults, locked, and its own estimate", () => {
    assert.deepEqual({ ...ADVANCED_DEFAULTS }, { steps: 325, learningRate: 0.0006, rank: 64, gradAccum: 2 });
    assert.deepEqual(etaForSteps(325), { min: 27, max: 35 });
    assert.deepEqual(etaForSteps(50), { min: 4, max: 5 });
    assert.deepEqual(etaForSteps(1), { min: 1, max: 1 });
    assert.deepEqual(etaForSteps(800), { min: 66, max: 86 });
  });
  test("the locked tracks sit where the defaults are", () => {
    assert.equal(trackPercent(325, STEP_RANGE), 37);
    assert.equal(trackPercent(0.0006, LR_RANGE), 58);
    assert.equal(trackPercent(9999, STEP_RANGE), 100);
    assert.equal(trackPercent("x", STEP_RANGE), 0);
  });
});

import { sentence } from "../../gallery/src/gen/trainCore.js";

describe("the estimate as a sentence", () => {
  test("capitalised with one full stop; nothing stays nothing", () => {
    assert.equal(sentence("about 27–35 minutes"), "About 27–35 minutes.");
    assert.equal(sentence("Done."), "Done.");
    assert.equal(sentence(""), "");
  });
});
