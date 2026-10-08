import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  TAG_MAX_LEN, TAGS_MAX, NOTE_MAX, UNDO_MS,
  normalizeTag, checkTag, clampNote, pictures, curateSummary, addedSummary, undoSecondsLeft,
  applyAfter, ratingFromKey, isTypingTarget, pickHotkeyTargets, flashText,
  mergePlan, tickTitle, deleteBody, checkRename, canSaveSmart, smartQueryLine, composeSmartQuery,
} from "../../gallery/src/curation/curationCore.js";

/* Session N (Curation), the pure half: the personal layer's rules, the honest toast words,
   the rating hotkeys' targeting and the collections manager's plans. The server owns the
   truth (dev/tests/test_curation.py); these pin what the screen decides before it asks. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").split("\r\n").join("\n");

describe("tags", () => {
  test("stored form: lowercase, hyphenated, letters and digits only", () => {
    assert.equal(normalizeTag("Pose Study"), "pose-study");
    assert.equal(normalizeTag("  Pose__Study!! "), "pose-study");
    assert.equal(normalizeTag("a--b"), "a-b");
    assert.equal(normalizeTag("--x--"), "x");
    assert.equal(normalizeTag("!!!"), "");
    assert.equal(normalizeTag(null), "");
    assert.equal(normalizeTag("ポーズ"), "ポーズ".replace(/[^\p{L}\p{N}-]/gu, ""));
  });
  test("the caps are the handoff's: 32 characters a tag, 32 tags a picture, 500 for a note", () => {
    assert.equal(TAG_MAX_LEN, 32);
    assert.equal(TAGS_MAX, 32);
    assert.equal(NOTE_MAX, 500);
    assert.equal(UNDO_MS, 10000);
  });
  test("checkTag says no in words, and calls a repeat a no-op rather than an error", () => {
    assert.deepEqual(checkTag("Pose Study", []), { ok: true, tag: "pose-study" });
    assert.equal(checkTag("!!", []).ok, false);
    assert.match(checkTag("x".repeat(33), []).error, /32 characters/);
    assert.equal(checkTag("x".repeat(32), []).ok, true);
    assert.deepEqual(checkTag("pose-study", ["pose-study"]), { ok: true, tag: "pose-study", dupe: true });
    const full = Array.from({ length: 32 }, (_, i) => "t" + i);
    assert.match(checkTag("one-more", full).error, /at most 32 tags/);
    assert.equal(checkTag("t3", full).dupe, true, "a tag it already holds is fine even at the cap");
  });
  test("a note is clamped to 500", () => {
    assert.equal(clampNote("n".repeat(600)).length, 500);
    assert.equal(clampNote(null), "");
  });
});

describe("the toast counts only what really changed (N4)", () => {
  test("rating", () => {
    assert.equal(curateSummary({ rating: 4 }, 3), "Rated 3 pictures ★4");
    assert.equal(curateSummary({ rating: 4 }, 1), "Rated 1 picture ★4");
    assert.equal(curateSummary({ rating: 0 }, 2), "Cleared the rating on 2 pictures");
  });
  test("nothing changed is said plainly, never counted as a success", () => {
    assert.equal(curateSummary({ rating: 4 }, 0), "Nothing changed: they already have ★4.");
    assert.equal(curateSummary({ mark: "keeper" }, 0), "Nothing changed: they are already keepers.");
    assert.equal(curateSummary({ add_tag: "Pose Study" }, 0), "Nothing changed: already tagged “pose-study”.");
  });
  test("tags and marks", () => {
    assert.equal(curateSummary({ add_tag: "Pose Study" }, 5), "Tagged 5 pictures “pose-study”");
    assert.equal(curateSummary({ mark: "keeper" }, 2), "Marked 2 as keepers");
    assert.equal(curateSummary({ mark: "reject" }, 1), "Marked 1 as a reject");
    assert.equal(curateSummary({ mark: "" }, 3), "Cleared the mark on 3 pictures");
  });
  test("a refusal at the tag cap rides along", () => {
    assert.match(curateSummary({ add_tag: "x" }, 2, 3), /3 already hold 32 tags$/);
    assert.match(curateSummary({ add_tag: "x" }, 2, 1), /1 already holds 32 tags$/);
  });
  test("adding to a collection counts the pictures that really joined", () => {
    assert.equal(addedSummary(3, "Faves", 3), "Added 3 to “Faves”");
    assert.equal(addedSummary(2, "Faves", 5), "Added 2 to “Faves” · 3 already in it");
    assert.equal(addedSummary(0, "Faves", 4), "Nothing added: they are already in “Faves”.");
    assert.equal(addedSummary(0, "Faves", 1), "Nothing added: it is already in “Faves”.");
  });
  test("plural and the undo clock", () => {
    assert.equal(pictures(1), "1 picture");
    assert.equal(pictures(2), "2 pictures");
    assert.equal(undoSecondsLeft(10000, 0), 10);
    assert.equal(undoSecondsLeft(10000, 8500), 2);
    assert.equal(undoSecondsLeft(10000, 10001), 0);
    assert.equal(undoSecondsLeft(10000, 99999), 0, "never negative");
  });
});

describe("keeping the loaded page honest", () => {
  const items = [
    { media_id: "1", rating: 0, mark: "", tags: [] },
    { media_id: "2", rating: 3, mark: "", tags: [] },
  ];
  test("patches the pictures the server changed, leaves the rest alone", () => {
    const next = applyAfter(items, { 2: { rating: 5, mark: "keeper", tags: ["a"], note: "" } });
    assert.deepEqual(next[1], { media_id: "2", rating: 5, mark: "keeper", tags: ["a"] });
    assert.equal(next[0], items[0]);
  });
  test("returns the SAME array when nothing on the page was touched", () => {
    assert.equal(applyAfter(items, { 9: { rating: 1 } }), items);
    assert.equal(applyAfter(items, {}), items);
    assert.equal(applyAfter(items, null), items);
  });
  test("an undo is the same patch: it writes the previous state back", () => {
    const changed = applyAfter(items, { 2: { rating: 5, mark: "reject", tags: [], note: "" } });
    const back = applyAfter(changed, { 2: { rating: 3, mark: "", tags: [], note: "" } });
    assert.equal(back[1].rating, 3);
    assert.equal(back[1].mark, "");
  });
});

describe("the rating hotkeys (N5)", () => {
  const key = (k, mods = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, ...mods });
  test("0 to 5 with no chord", () => {
    for (const n of [0, 1, 2, 3, 4, 5]) assert.equal(ratingFromKey(key(String(n))), n);
    assert.equal(ratingFromKey(key("6")), null);
    assert.equal(ratingFromKey(key("a")), null);
    assert.equal(ratingFromKey(key("3", { ctrlKey: true })), null);
    assert.equal(ratingFromKey(key("3", { metaKey: true })), null);
    assert.equal(ratingFromKey(key("3", { altKey: true })), null);
    assert.equal(ratingFromKey(key("3", { isComposing: true })), null);
    assert.equal(ratingFromKey(null), null);
  });
  test("ignored inside a field", () => {
    const el = (hit) => ({ closest: () => hit });
    assert.equal(isTypingTarget(el({})), true);
    assert.equal(isTypingTarget(el(null)), false);
    assert.equal(isTypingTarget(null), false);
    assert.equal(isTypingTarget({}), false);
  });
  test("the target is the selection, then the open Lightbox, then the record, then the hovered picture", () => {
    assert.deepEqual(pickHotkeyTargets({ selected: new Set(["a", "b"]), lightboxId: "l", detailsId: "d", hoverId: "h" }),
      { ids: ["a", "b"], from: "selection" });
    assert.deepEqual(pickHotkeyTargets({ selected: new Set(), lightboxId: "l", detailsId: "d", hoverId: "h" }),
      { ids: ["l"], from: "lightbox" });
    assert.deepEqual(pickHotkeyTargets({ selected: [], lightboxId: null, detailsId: "d", hoverId: "h" }),
      { ids: ["d"], from: "details" });
    assert.deepEqual(pickHotkeyTargets({ selected: null, lightboxId: null, detailsId: null, hoverId: "h" }),
      { ids: ["h"], from: "hover" });
    assert.deepEqual(pickHotkeyTargets({}), { ids: [], from: "none" });
  });
  test("the flash says the stars given, or that the rating was cleared", () => {
    assert.equal(flashText(3), "★★★");
    assert.equal(flashText(0), "☆ cleared");
  });
});

describe("the collections manager's plans (N2)", () => {
  const all = [
    { name: "A", kind: "hand", count: 3 },
    { name: "B", kind: "hand", count: 2 },
    { name: "S", kind: "smart", count: 9, query: "keeper" },
  ];
  test("merge needs two hand-picked; the first ticked is the target; smart ones do not count", () => {
    assert.equal(mergePlan([], all).can, false);
    assert.equal(mergePlan(["A"], all).can, false);
    assert.equal(mergePlan(["A", "S"], all).can, false, "a smart collection cannot be merged");
    const p = mergePlan(["B", "S", "A"], all);
    assert.equal(p.can, true);
    assert.equal(p.target, "B");
    assert.deepEqual(p.hand, ["B", "A"]);
    assert.equal(p.label, "Merge 2 into “B”");
    assert.match(p.note, /never deleted/);
    assert.match(mergePlan([], all).note, /two or more hand-picked/);
  });
  test("a smart collection's tick box says why it is off", () => {
    assert.match(tickTitle(all[2]), /can’t merge/);
    assert.equal(tickTitle(all[0]), "Tick to merge");
  });
  test("delete says how many pictures stay in the library", () => {
    assert.equal(deleteBody(all[0]), "The collection goes. Its 3 pictures stay in your library.");
    assert.equal(deleteBody({ kind: "hand", count: 1 }), "The collection goes. Its 1 picture stays in your library.");
    assert.equal(deleteBody(all[2]), "Only the saved query goes. The 9 matching pictures stay in your library.");
  });
  test("rename is trimmed and unique without regard to case", () => {
    assert.deepEqual(checkRename("  New   name ", "A", all), { ok: true, name: "New name" });
    assert.deepEqual(checkRename("A", "A", all), { ok: true, name: "A", unchanged: true });
    assert.equal(checkRename("a", "A", all).ok, true, "its own name in another case is its own");
    assert.match(checkRename("b", "A", all).error, /already exists/);
    assert.match(checkRename("s", "A", all).error, /already exists/, "a smart collection's name is taken too");
    assert.match(checkRename("   ", "A", all).error, /needs a name/);
    assert.equal(checkRename("a,b", "A", all).name, "a b", "commas are the store's separator");
  });
  test("saving a search needs a search", () => {
    assert.equal(canSaveSmart("  "), false);
    assert.equal(canSaveSmart(""), false);
    assert.equal(canSaveSmart(null), false);
    assert.equal(canSaveSmart("ar:tall keeper"), true);
    assert.equal(smartQueryLine("keeper"), "⟳ keeper");
  });
});

describe("the search a smart collection saves", () => {
  test("the field's text alone is the search when nothing else narrows the view", () => {
    assert.equal(composeSmartQuery({ q: "  keeper   night*  ", media: "", shelf: "", adv: {} }), "keeper night*");
    assert.equal(composeSmartQuery({ q: "", media: "", shelf: "", adv: {} }), "");
    assert.equal(composeSmartQuery({ q: "x" }), "x");
  });
  test("every chip and flyout filter with an operator is written out, so the saved search is the whole view", () => {
    const q = composeSmartQuery({
      q: "night*", media: "image", shelf: "Druid of Azeroth",
      adv: { ratingMin: 4, model: "Tsubaki.3", lora: "moon light", source: "api", tag: "elf",
        publishedOnly: true, dateFrom: "2026-01", dateTo: "2026-07", sort: "oldest", batch: "b", series: "s" },
    });
    assert.equal(q, 'night* collection:"Druid of Azeroth" video:0 ★4+ model:Tsubaki.3 lora:"moon light" ' +
      "source:api art_tags:elf published:1 created:>=2026-01 created:<=2026-07");
  });
  test("videos, and what has no operator (sort, batch, series) is left out", () => {
    assert.equal(composeSmartQuery({ media: "video", adv: { sort: "oldest", batch: "b", series: "s" } }), "video:1");
  });
  test("a quote inside a value can never break out of the token", () => {
    assert.equal(composeSmartQuery({ adv: { model: 'a"b c' } }), 'model:"ab c"');
  });
});

describe("source guards", () => {
  test("the rating keys are ignored in fields and under every layer that owns the keyboard", () => {
    const app = src("App.jsx");
    assert.match(app, /isTypingTarget\(e\.target\) \|\| isTypingTarget\(document\.activeElement\)/);
    for (const layer of ["isPickerOpen()", "isRecipesOpen()", "isMomentUp()", "isHelpUp()", "st.blocked"]) {
      assert.ok(app.includes(layer), "the hotkeys ignore " + layer);
    }
    assert.match(app, /blocked: !!\(overlay \|\| ctxMenu \|\| stackFor \|\| claimModal\.open \|\| palette\.active \|\| palette\.sheetActive\)/);
  });
  test("the hover target is read off the DOM, so the memoized grid takes no pointer props", () => {
    assert.match(src("App.jsx"), /document\.querySelector\("\.mgg-card:hover"\)/);
  });
  test("the flash is static under reduced motion (it still appears)", () => {
    const css = src("styles/curation.css");
    const rm = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    assert.match(rm, /\.mgcu-flash \{ animation: none; opacity: 1;/);
  });
  test("the manager keeps the slot Session P hosts its manual order in", () => {
    const mgr = src("components/CollectionsManager.jsx");
    assert.match(mgr, /data-slot=\{smart \? undefined : "collection-order"\}/);
    assert.match(mgr, /renderRowSlot/);
    assert.match(src("styles/curation.css"), /\.mgcu-mslot:empty \{ display: none; \}/);
  });
  test("every curation POST carries the session's CSRF token in its body", () => {
    const api = src("api.js");
    assert.match(api, /apiPost\("\/api\/curate", \{ csrf, media_ids: mediaIds, op \}\)/);
    assert.match(api, /apiPost\("\/api\/curate\/restore", \{ csrf, prev \}\)/);
    assert.match(api, /apiPost\("\/api\/collections\/manage", \{ \.\.\.body, csrf \}\)/);
  });
  test("the palette lists Rate 1–5 under Do, and the cheat sheet lists the keys", () => {
    assert.match(src("App.jsx"), /id: "do\.rate", group: "Do"[^}]*label: "Rate 1\\u20135"/s);
    assert.match(src("components/CommandPalette.jsx"), /\["1–5", "", "", "★ Rate the picture · 0 clears"\]/);
  });
  test("a smart collection is never offered as somewhere to add pictures", () => {
    const bar = src("components/CurationBar.jsx");
    assert.match(bar, /handCollections\.map/);
    const app = src("App.jsx");
    assert.match(app, /<CurationBar count=\{selected\.size\} handCollections=\{collections\}/);
    assert.match(src("components/FiltersPanel.jsx"), /shelf=\{curation && curation\.smartShelf \? "" : shelf\}/);
  });
});
