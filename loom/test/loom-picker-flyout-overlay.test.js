import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// picker-parity-round2 (problem 2): the owner's live test of the O12/O13 migration found
// the Loom's Image tab model/LoRA picker rendering CRAMMED INLINE into the ~280px right
// rail -- model result cards, a "hide LoRA picker" toggle sitting in the middle of the
// results, then ANOTHER search box, then more LoRA cards, all stacked in the narrow column.
// Owner's own words: "Loom picker is a cramped mess. it does not have a flyout like the
// gallery." This is the fix: both <mg-model-picker> mounts move out of the tab-conditional
// inline flow and into a floating overlay (.lv-mpick-veil), matching the Gallery's own
// #model-flyout presentation -- a Models/LoRAs segment toggle, one floating panel, not two
// different picker experiences under the hood of the "same" component.
//
// master-storyboard.jsx has no jsdom/React test harness in this runner -- source-presence
// assertions are the established pattern here (see loom-lora-toggle-chrome.test.js,
// loom-image-tab-lora-incompat.test.js); real interaction verification needs a real browser.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("Image tab's Model/LoRA picker is a floating overlay, not inline (problem 2)", () => {
  test("the old inline-mounted pickers and the loraOpen inline-toggle boolean are GONE", () => {
    // Checks the actual STATE/CALL sites, not prose -- a comment explaining the history
    // ("replaces the old loraOpen boolean") is expected and fine; a live declaration or
    // call site is not.
    assert.doesNotMatch(src, /const \[loraOpen, setLoraOpen\]/,
      "the loraOpen useState declaration must be gone -- it drove the exact cramped-inline " +
      "toggle behavior the owner reported");
    assert.doesNotMatch(src, /setLoraOpen\(/, "setLoraOpen must have no remaining call sites");
    assert.doesNotMatch(src, /\{loraOpen \?/, "no remaining conditional reads of loraOpen");
    // the picker must not be a direct, always-inline child of the Image tab's own div --
    // it now lives inside .lv-mpick-body, gated by the overlay's open state.
    assert.doesNotMatch(src, /<label className="lv-lab">Model \{imgModel/,
      "the old 'Model {imgModel...}' inline label must be replaced by the overlay-opening trigger row");
  });

  test("a trigger row opens the overlay pre-selected to Models, mirroring pixai_gallery.py's #gen-selrow", () => {
    assert.match(src, /<button type="button" className="lv-selrow" onClick=\{\(\) => \{ setPickerKind\("base"\); setPickerOpen\(true\); \}\}>/,
      "the Model row must be a clickable trigger that opens the overlay on the base segment");
  });

  test("+ add LoRA opens the SAME overlay pre-selected to LoRAs, not a second inline mount", () => {
    assert.match(src, /<button type="button" className="lv-chip lv-loratoggle" onClick=\{\(\) => \{ setPickerKind\("lora"\); setPickerOpen\(true\); \}\}>/,
      "the LoRA trigger must open the shared overlay on the lora segment, not toggle inline visibility");
  });

  test("pickerOpen/pickerKind state drives ONE floating overlay with a Models/LoRAs segment toggle", () => {
    assert.match(src, /const \[pickerOpen, setPickerOpen\] = useState\(false\);/);
    assert.match(src, /const \[pickerKind, setPickerKind\] = useState\("base"\);/);
    assert.match(src, /className=\{"lv-mpick-veil" \+ \(pickerOpen \? " open" : ""\)\}/,
      "the overlay's visibility must be driven by pickerOpen, matching the Gallery's " +
      "#model-flyout.open toggle pattern");
    assert.match(src, /<div className="lv-mpick-seg">/);
    assert.match(src, /onClick=\{\(\) => setPickerKind\("base"\)\}>Models<\/button>/);
    assert.match(src, /onClick=\{\(\) => setPickerKind\("lora"\)\}>LoRAs<\/button>/);
  });

  test("Escape closes the overlay, matching every other veil in this file (deepFocus, Export, ProjectSwitcher)", () => {
    assert.match(src,
      /if \(!pickerOpen\) return;\s*\n\s*const onKey = \(ev\) => \{ if \(ev\.key === "Escape"\) setPickerOpen\(false\); \};/,
      "the overlay must have its own Escape-to-close effect, not rely on some other veil's");
  });

  test("clicking the backdrop (not the panel) closes the overlay", () => {
    assert.match(src, /onClick=\{\(ev\) => \{ if \(ev\.target === ev\.currentTarget\) setPickerOpen\(false\); \}\}/,
      "a backdrop click must close the overlay without swallowing clicks inside the panel itself");
  });

  test("both pickers are lazy-mounted on first open, then stay mounted (never lose search state on reopen)", () => {
    // Mirrors pixai_gallery.py's ensurePickers() -- "only fetch on first open", not an
    // always-mounted base+LoRA fetch on every Loom load just because the right rail is
    // expanded (the right rail's default tab is Video, not Image).
    assert.match(src, /const \[pickerMounted, setPickerMounted\] = useState\(false\);/);
    assert.match(src, /useEffect\(\(\) => \{ if \(pickerOpen\) setPickerMounted\(true\); \}, \[pickerOpen\]\);/);
    assert.match(src, /\{pickerMounted && \(/,
      "the two <mg-model-picker> mounts must be gated on the lazy-mount flag, not always rendered");
  });

  test("both <mg-model-picker> instances render inside .lv-mpick-body, kind toggled via CSS display not unmount", () => {
    assert.match(src, /<mg-model-picker ref=\{bindPicker\} kind="base"\s*\n\s*style=\{\{ display: pickerKind === "base" \? "flex" : "none" \}\}><\/mg-model-picker>/,
      "the base picker must stay mounted and only be display:none'd when LoRAs is active -- " +
      "unmounting on every segment switch would lose its search results/scroll each time");
    assert.match(src, /<mg-model-picker ref=\{bindLoraPicker\} kind="lora" multi base-type=\{\(imgModel && imgModel\.model_type\) \|\| ""\}\s*\n\s*style=\{\{ display: pickerKind === "lora" \? "flex" : "none" \}\}><\/mg-model-picker>/,
      "the LoRA picker must carry base-type (problem 3 wiring) and use the same " +
      "display-toggle-not-unmount pattern as the base picker");
  });

  test("the overlay lives alongside <mg-generate-drawer>, so it survives Image/Edit/Reference/Video tab switches", () => {
    // Both must be siblings inside the SAME always-rendered .lv-gen block (only unmounted
    // when the whole right rail collapses) -- not nested inside the tab-conditional tabBody,
    // or switching tabs while the picker is open would silently blow away its state.
    const genDrawerIdx = src.indexOf('<mg-generate-drawer ref={bindGenDrawer}');
    const veilIdx = src.indexOf('className={"lv-mpick-veil"');
    assert.ok(genDrawerIdx > 0 && veilIdx > genDrawerIdx,
      "the picker overlay must be declared after <mg-generate-drawer> inside the same " +
      "always-mounted block, not inside one of the tab-specific branches above it");
  });
});
