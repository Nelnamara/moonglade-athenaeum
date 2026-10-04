import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  countClauses, savedEmptyLine, savedErrorLine, savedTabLabel, currentSet, goneLine,
  SAVED_BASES, NARROW_PX, SAVED_END_LINE,
} from "../../gallery/src/picker/savedCore.js";

/* The model and LoRA pickers' Saved tab (Session S, Saved Tab Handoff; drift 134-139). Saved
   replaces the frozen Bookmarked tab: PixAI's reserved default model collection, read live,
   with a 112 px rail of named sets beside it (a "Saved ▾" chooser below 640 px). The logic is
   importless (gallery/src/picker/savedCore.js) and pinned directly; the picker's wiring is
   pinned on its source, as the rest of the picker's node tests do (no React harness here).
   The browser proof is tests/test_render_harness.py; the server half tests/test_model_saved.py. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(__dirname, "../../gallery/src", p), "utf8");
const picker = read("components/ModelPicker.jsx");
const tab = read("picker/SavedTab.jsx");
const css = read("styles/saved-tab.css");

test("the header's count leaves out every clause that is zero (S5c)", () => {
  assert.deepEqual(countClauses({ count: 18, old: 4, gone: 2 }).map((c) => c.text),
    ["18", "4 old", "2 not available"]);
  assert.deepEqual(countClauses({ count: 1340, old: 0, gone: 9 }).map((c) => c.text),
    ["1,340", "9 not available"]);
  assert.deepEqual(countClauses({ count: 7 }).map((c) => c.key), ["count"]);
  assert.deepEqual(countClauses({}), []);
});

test("empty points at Market, a keyword miss says so, and a failure is never empty", () => {
  assert.equal(savedEmptyLine("lora", ""), "Nothing saved for LoRAs yet. Use ⊕ Save on any LoRA in Market.");
  assert.equal(savedEmptyLine("base", ""), "Nothing saved for models yet. Use ⊕ Save on any model in Market.");
  assert.equal(savedEmptyLine("lora", "glass"), "No saved LoRAs match “glass”.");
  // a base chip that leaves nothing names the base, rather than claiming nothing is saved
  assert.equal(savedEmptyLine("lora", "", "DiT.1"), "No saved LoRAs for DiT.1.");
  assert.equal(savedEmptyLine("lora", "glass", "SDXL"), "No saved LoRAs match “glass” for SDXL.");
  assert.equal(savedErrorLine("Saved"), "Couldn't load Saved.");
  assert.equal(savedErrorLine("Faces"), "Couldn't load Faces.");
  assert.equal(SAVED_END_LINE, "That's everything");
});

test("the rail folds into a Saved ▾ chooser below 640 px of picker width", () => {
  assert.equal(NARROW_PX, 640);
  assert.equal(savedTabLabel(true), "Saved");
  assert.equal(savedTabLabel(false), "Saved ▾");
  assert.match(picker, /ResizeObserver/);
  assert.match(picker, /clientWidth >= NARROW_PX/);
});

test("the set on screen is Saved unless a named set was picked", () => {
  const sets = [{ id: "d", title: "Saved", reserved: true, count: 3 }, { id: "a", title: "Anime", count: 1 }];
  assert.equal(currentSet(sets, "").id, "d");
  assert.equal(currentSet(sets, "a").id, "a");
  assert.equal(currentSet([], ""), null);
  assert.match(goneLine({ saved_at: "2024-03-05T00:00:00.000Z" }), /saved 2024-03-05$/);
});

test("the base chips send values the collection accepts, one at a time", () => {
  const sent = SAVED_BASES.map(([v]) => v).filter(Boolean);
  // every one is in moonglade_backup.LORA_BASE_MODEL_TYPES (the probe: all 47 enum values 200)
  ["MMDIT26B_MODEL", "MMDIT26A_MODEL", "DIT7_MODEL", "SDXL_MODEL", "SD_V1_MODEL"].forEach((v) =>
    assert.ok(sent.includes(v), v));
  assert.equal(SAVED_BASES[0][1], "All");
  assert.match(picker, /&base=" \+ encodeURIComponent\(savedBase\)/);
  assert.match(picker, /kind === "lora" && savedBase/, "base chips are the LoRA picker's only");
});

test("the source row is Market · Saved · Mine, and Bookmarked is gone", () => {
  assert.match(picker, /\["saved", savedTabLabel\(wide\)\]/);
  assert.doesNotMatch(picker, /"Bookmarked"/);
  assert.doesNotMatch(picker, /"bookmark"/);
  assert.match(picker, /kind === "lora" \? \[\["mine", "Mine"\]\]/, "Mine stays as shipped: LoRAs only");
});

test("Saved pages through the picker's own search, by set, with no market filters", () => {
  assert.match(picker, /if \(src === "saved"\) \{\s*if \(setId\) u \+= "&set=" \+ encodeURIComponent\(setId\);/);
  assert.match(picker, /const filtersHidden = market && src === "saved"/);
  // a re-search fires when the set or the chip changes
  assert.match(picker, /\}, \[kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType, setId, savedBase\]\);/);
});

test("the rail is read once when Saved opens, and nothing is written on open", () => {
  assert.match(picker, /apiGet\("\/api\/model-saved\/sets", \{ kind \}\)/);
  assert.doesNotMatch(tab, /apiPost/);
  assert.doesNotMatch(picker.slice(0, picker.indexOf("export default")), /apiPost/);
});

test("an error is peach with Retry, empty is one line, and the end of the list says so", () => {
  assert.match(picker, /savedErrorLine\(/);
  assert.match(picker, /className="mg-saved-retry"/);
  assert.match(picker, /savedEmptyLine\(kind, qDebounced, /);
  assert.match(picker, /SAVED_END_LINE/);
  assert.match(css, /\.mg-saved-err \{[^}]*var\(--peach\)/);
});

test("the rail is 112 px of mono 10 px at line-height 2, marked with a lavender ▸", () => {
  assert.match(css, /\.mg-rail \{[^}]*width: 112px/);
  assert.match(css, /\.mg-rail \{[^}]*font: 10px\/2 ui-monospace/);
  assert.match(css, /\.mg-rail-mark \{[^}]*color: var\(--lavender\)/);
  assert.match(tab, /"▸"/);
  // the header's count is mono 9.5 px in overlay0
  assert.match(css, /\.mg-saved-count \{[^}]*font: 9\.5px\/1\.45 ui-monospace[^}]*color: var\(--overlay0\)/);
});

/* ---- S2c: the old bookmarks, merged into Saved after its own rows ---- */

import { mergeOld, OLD_PREF } from "../../gallery/src/picker/savedCore.js";
import { prefKeyProblem } from "../../gallery/src/hooks/accountPrefsStore.js";

test("old bookmarks merge after the live rows, minus anything already live, tagged old", () => {
  const live = [{ model_id: "1", title: "Moonwell v3" }];
  const old = [{ model_id: "1", title: "Moonwell v3" }, { model_id: "2", title: "Glasswing", lora_base_model_type: "SDXL_MODEL" },
    { model_id: "3", title: "Kurone Ink", lora_base_model_type: "MMDIT26B_MODEL", description: "inky lines" }];
  assert.deepEqual(mergeOld(live, old).map((r) => [r.model_id, r.old]), [["2", true], ["3", true]]);
  // the search box and the base chip narrow them as they narrow the live list
  assert.deepEqual(mergeOld(live, old, { q: "ink" }).map((r) => r.model_id), ["3"]);
  assert.deepEqual(mergeOld(live, old, { q: "inky LINES" }).map((r) => r.model_id), ["3"]);
  assert.deepEqual(mergeOld(live, old, { base: "SDXL_MODEL" }).map((r) => r.model_id), ["2"]);
  assert.deepEqual(mergeOld(live, null), []);
});

test("Show old bookmarks is a per-account preference, on unless turned off", () => {
  assert.equal(OLD_PREF, "picker.old_bookmarks");
  assert.equal(prefKeyProblem(OLD_PREF), "");
  assert.match(picker, /import useAccountPrefs from "\.\.\/hooks\/useAccountPrefs\.js";/);
  assert.match(picker, /prefs\.get\(OLD_PREF, true\) !== false/);
  assert.match(picker, /prefs\.set\(OLD_PREF, !showOld\)/);
  assert.match(tab, /Show old bookmarks/);
});

test("the merge is read only on Saved itself, and only while the toggle is on", () => {
  assert.match(picker, /apiGet\("\/api\/model-saved\/old", \{ kind \}\)/);
  assert.match(picker, /savedOn && !setId && showOld/);
  // after the live list's end, never before it
  assert.match(picker, /const oldShown = savedOn && !setId && showOld && atEnd && !err/);
  assert.match(picker, /const listRows = oldShown\.length \? rows\.concat\(oldShown\) : rows;/);
  assert.match(picker, /\{listRows\.map\(\(m, i\) => \{/);
});

test("an old row saved here joins the list untagged, and is old again if taken back out", () => {
  assert.match(picker, /oldAsideRef\.current\.set\(id, m\);/);
  assert.match(picker, /const back = !setId && oldAsideRef\.current\.get\(id\);/);
  assert.match(picker, /setOldRows\(\(o\) => \(o \|\| \[\]\)\.concat\(back\)\);/);
});

test("an old row carries a mono old tag, 8.5 px and neutral", () => {
  assert.match(read("picker/KeepControls.jsx"), /m\.old \? <span className="mg-old">old<\/span>/);
  assert.match(css, /\.mg-old \{[^}]*font: 700 8\.5px\/1\.3 ui-monospace[^}]*color: var\(--overlay0\)/);
});

/* ---- S3b + S4c: the split control and the "Keep this model" menu ---- */

import { afterWrite, createSavedStore, isTransportError, keepTitle, READ_ONLY_LINE, SAVED_NOTE } from "../../gallery/src/picker/savedCore.js";

const keepSrc = read("picker/KeepControls.jsx");
const apiSrc = read("picker/savedApi.js");
const menuSrc = read("recipes/RecipeSetsMenu.jsx");
const powerCss = read("styles/power.css");

test("the read-back decides the card: saved only when PixAI says so", () => {
  assert.deepEqual(afterWrite({ saved: false, item_id: "" }, { contains: true, item_id: "i1" }, true),
    { saved: true, item_id: "i1", error: "", ok: true });
  // a refusal the check confirms: back to ⊕ Save, the plain words shown
  assert.deepEqual(afterWrite({ saved: false, item_id: "" }, { contains: false, item_id: "", error: "This model is private, so PixAI won't save it" }, true),
    { saved: false, item_id: "", error: "This model is private, so PixAI won't save it", ok: false });
  // nothing known (the check failed too): the card keeps what it showed, and says so
  const unknown = afterWrite({ saved: false, item_id: "" }, { contains: null, error: "unclear" }, true);
  assert.equal(unknown.saved, false); assert.equal(unknown.ok, false); assert.equal(unknown.error, "unclear");
  assert.equal(afterWrite({ saved: true, item_id: "i1" }, { error: "network error: x" }, false).saved, true);
  assert.ok(isTransportError({ error: "network error: Failed to fetch" }));
  assert.ok(!isTransportError({ error: "READ_ONLY is set in config.json -- refusing" }));
  assert.equal(SAVED_NOTE, "Saved · read back from PixAI.");
  assert.equal(READ_ONLY_LINE, "Read-only mode is on, so saving to PixAI is off.");
  assert.equal(keepTitle("base"), "Keep this model");
  assert.equal(keepTitle("lora"), "Keep this LoRA");
});

test("the saved-state store tells every card at once", () => {
  const st = createSavedStore();
  let calls = 0;
  const off = st.subscribe(() => { calls++; });
  const v0 = st.version();
  st.set("1", { saved: true, item_id: "i1" });
  st.setMany([["2", { saved: true, item_id: "i2" }], ["3", { saved: false, item_id: "" }]]);
  assert.equal(calls, 2);
  assert.ok(st.version() > v0);
  assert.deepEqual(st.get(1), { saved: true, item_id: "i1" });
  off(); st.set("1", { saved: false, item_id: "" });
  assert.equal(calls, 2);
});

test("the card's ☆ is retired: ★ shows state only, and quick-pick moves into the menu", () => {
  assert.doesNotMatch(picker, /mg-fav/);
  assert.doesNotMatch(powerCss, /\.mg-fav/);
  assert.match(keepSrc, /className="mg-star"/);
  assert.match(keepSrc, /label: "★ Quick-pick", tag: "this app"/);
  assert.match(picker, /onQuick=\{onFav \? \(\) => onFav\(keep\.m\) : null\}/);
});

test("the split control: one save write per tap, ✓ Saved opens the menu and never unsaves", () => {
  assert.match(keepSrc, /saved \? "✓ Saved" : "⊕ Save"/);
  assert.match(keepSrc, /if \(saved\) \{ onMenu\(e\.currentTarget\.parentNode\); return; \}/);
  assert.match(picker, /const d0 = await savedApi\.save\(id\);/);
  assert.equal((picker.match(/savedApi\.save\(/g) || []).length, 1, "one write, never re-sent");
  // an answer that never reached the page is read back, never re-sent
  assert.match(picker, /if \(isTransportError\(d0\)\) \{[\s\S]{0,200}savedApi\.state\(id\)/);
  // one write in flight per card
  assert.match(picker, /if \(readOnly \|\| busyRef\.current\.has\(id\)\) return;/);
  // where: picker cards in the dock and the phone sheet (the market mounts), always visible
  assert.match(picker, /\{market \? \(\s*<KeepRow/);
});

test("READ_ONLY is known before a tap: the search answers it, the body dims and says why", () => {
  assert.match(picker, /if \(d && typeof d\.read_only === "boolean"\) setReadOnly\(d\.read_only\);/);
  assert.match(keepSrc, /title=\{readOnly && !saved \? READ_ONLY_LINE/);
  assert.match(keepSrc, /"mg-split-body" \+ \(readOnly && !saved \? " dim" : ""\)/);
});

test("the menu is the recipe Sets menu, titled Keep this model, quick-pick first", () => {
  assert.match(keepSrc, /import RecipeSetsMenu from "\.\.\/recipes\/RecipeSetsMenu\.jsx";/);
  assert.match(keepSrc, /variant="keep"/);
  assert.match(keepSrc, /heading=\{keepTitle\(kind\)\}/);
  assert.match(keepSrc, /tag="PixAI"/);
  assert.match(keepSrc, /label: "Open on PixAI ↗", href: "https:\/\/pixai\.art\/model\/"/);
  // the local row, then a divider, then PixAI's sets
  const i = menuSrc.indexOf("local.label"), j = menuSrc.indexOf('className="rcp-keep-div"'), k = menuSrc.indexOf("(sets || []).map");
  assert.ok(i > 0 && j > i && k > j, "quick-pick, divider, sets -- in that order");
  // under READ_ONLY the PixAI rows are disabled with the reason; quick-pick is not
  assert.match(menuSrc, /disabled=\{!!readOnly \|\| busy === s\.id\} title=\{readOnly \|\| undefined\}/);
  // the recipe menu itself is unchanged by default
  assert.match(menuSrc, /heading = "SAVE TO A RECIPE SET"/);
  assert.match(menuSrc, /variant = "sets"/);
});

test("a tick's answer decides the row, a failed one reverts, an unreached one is read back", () => {
  assert.match(menuSrc, /if \(d && typeof d\.contains === "boolean"\) \{/);
  assert.match(menuSrc, /apply\(before, true\);/);
  // only an answer moves the list behind the menu: the at-once display is not PixAI's word
  assert.match(keepSrc, /onChanged=\{\(_, __, sets, settled\) => settled && onSets && onSets\(sets\)\}/);
  assert.match(menuSrc, /if \(api\.reread && d && \/\^network error\/i\.test\(String\(d\.error \|\| ""\)\)\) load\(\);/);
});

test("the menu floats over the dock's palette in the overlay band, and is a sheet on the phone", () => {
  assert.match(keepSrc, /createPortal\(/);
  assert.match(css, /\.mg-keep-layer \.rcp-sets \{[^}]*z-index: 420/);
  assert.match(keepSrc, /<div className="rcp-m mg-keep-sheet" data-keeps-dock="">/);
  // a click in the menu never closes the dock behind it (App.jsx's outside-click closer)
  assert.match(keepSrc, /<div className="mg-keep-layer" data-keeps-dock="">/);
});

test("the writes ride the model-saved routes with the session's CSRF token", () => {
  assert.match(apiSrc, /await accountPrefs\(\)\.ensureLoaded\(\);/);
  assert.match(apiSrc, /csrf: accountCsrf\(\)/);
  ["/api/model-saved/save", "/api/model-saved/tick", "/api/model-saved/remove", "/api/model-saved/sets/create",
    "/api/model-saved/state"].forEach((r) => assert.ok(apiSrc.includes('"' + r + '"'), r));
});

test("the split control matches the handoff: 10 px, lavender once saved", () => {
  assert.match(css, /\.mg-split-body \{[^}]*font-size: 10px[^}]*padding: 4px 8px[^}]*border-radius: 6px 0 0 6px/);
  assert.match(css, /\.mg-split\.saved \.mg-split-body \{[^}]*color: var\(--lavender\)/);
  assert.match(css, /\.mg-split-menu \{[^}]*padding: 4px 6px[^}]*border-radius: 0 6px 6px 0[^}]*border-left: 0/);
  assert.match(css, /\.mg-star \{[^}]*font-size: 12px[^}]*color: var\(--lavender\)/);
});

/* ---- S6a: the phone's Model/LoRA sheet ---- */

const flyout = read("components/ModelFlyout.jsx");

test("the phone sheet tells its pickers they are on the phone", () => {
  assert.equal((flyout.match(/phone=\{phone\}/g) || []).length, 2, "both the model and the LoRA picker");
});

test("Market | Saved ▾ | Mine, and Saved ▾ tapped again opens the sets as a sheet", () => {
  // the phone is never wide, so its segment reads Saved ▾ and a second tap opens the chooser
  assert.match(picker, /setWide\(!phone && el\.clientWidth >= NARROW_PX\)/);
  assert.match(picker, /phone \? \(\s*<SavedSetsSheet/);
  assert.match(tab, /export function SavedSetsSheet\(/);
  assert.match(tab, /<div className="rcp-m mg-sets-sheet" data-keeps-dock="">/);
  // picking one closes it (pickSet clears the chooser)
  assert.match(picker, /const pickSet = \(s\) => \{\s*setChooser\(false\);/);
});

test("▾ and a long-press open the keep menu as a bottom sheet on the phone", () => {
  assert.match(picker, /<KeepMenu m=\{keep\.m\} kind=\{kind\} rect=\{keep\.rect\} sheet=\{phone\}/);
  assert.match(picker, /longRef\.current\.t = setTimeout\(\(\) => \{[\s\S]{0,120}setKeep\(\{ m, rect: null \}\);[\s\S]{0,40}\}, 500\);/);
  // the tap that ends a long-press does not also pick the model
  assert.match(picker, /const pick = \(m\) => \{\s*if \(longRef\.current\.fired\) \{ longRef\.current\.fired = false; return; \}/);
});

test("rows keep the split control at phone sizes: a 44 x 32 body and a 32 px ▾", () => {
  assert.match(css, /\.model-picker\.phone \.mg-split-body \{[^}]*min-width: 44px[^}]*min-height: 32px/);
  assert.match(css, /\.model-picker\.phone \.mg-split-menu \{[^}]*min-width: 32px[^}]*min-height: 32px/);
});
