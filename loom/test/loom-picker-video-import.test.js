import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Regression guard for GitHub issue #3 (P1): "Loom asset picker on left side does not
// import already rendered videos when selected." The pick->asset chain itself was fine;
// the failure was reachability -- three stacked gaps kept a rendered video from ever
// being visible (and visibly imported) through the left rail's picker:
//
//   1. <mg-gallery-picker>'s combined type option submitted type='' -- and
//      /api/gallery-images maps an EMPTY type to "image" (deliberate back-compat for the
//      gallery's vanilla Picker, see picker-core.js's own seeding comment). So the one
//      view labeled "Image + video" could never contain a video. The server already
//      understands type=all as "both"; the fix is the combined option saying so.
//   2. The type <select> was never initialized from the resolved default-type, so it
//      always DISPLAYED "Image + video" (first option) whatever the real active filter
//      was -- "Browse library" showed videos under a label claiming both, and any other
//      filter change then re-read the lying select and silently dropped the video filter.
//   3. The Cast tray's "+ add from gallery" opened image-only, so an already-rendered
//      video wasn't in the default view at all; and once imported, a video asset rendered
//      as a bare film emoji in the (default) detailed rows -- no poster, unlike images --
//      so a successful import looked like nothing happened.
//
// A follow-up build (see the "Footage tab" describe block below) covers the actual
// placement/timeline-usability gap found once the above was live-tested: every pick, from
// EITHER left-rail button, landed in Cast & Assets -- a prompt reference -- with no way to
// place an already-rendered clip onto the board as real footage at all.
//
// Same technique as the suite's other guards over plain <script> components and the JSX
// (mg-model-picker-multi-select.test.js, loom-v2-dead-generate-shot-prop.test.js):
// source-presence assertions, no jsdom. The server side of the chain (type='' vs
// type=all vs type=video) is exercised for real in tests/test_web_pick.py.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pickerSrc = readFileSync(path.join(__dirname, "../../static/mg-gallery-picker.js"), "utf8");
const storyboardSrc = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

describe("mg-gallery-picker: videos are reachable through the type filter", () => {
  test("the combined type option submits type=all, not the silently-image empty string", () => {
    assert.match(pickerSrc, /<option value="all">Image \+ video<\/option>/,
      "the 'Image + video' option must carry value=\"all\" -- /api/gallery-images treats " +
      "an empty type as \"image\" (gallery-Picker back-compat), so value=\"\" makes the " +
      "combined view images-only and rendered videos unreachable (issue #3)");
    assert.doesNotMatch(pickerSrc, /<option value="">Image \+ video<\/option>/,
      "the empty-value combined option is exactly the bug: it looks like 'both' but the " +
      "server resolves it to images-only");
  });

  test("default-type=\"all\" resolves to the real 'all' filter, not ''", () => {
    assert.match(pickerSrc, /dt === 'video' \? 'video' : dt === 'all' \? 'all' : 'image'/,
      "the element's internal default type must be 'all' for default-type=\"all\" so the " +
      "first fetch asks the server for both kinds instead of the ''->image fallback");
  });

  test("the type select's DISPLAYED value is initialized from the resolved default", () => {
    assert.match(pickerSrc, /this\._typeEl\.value = this\._type/,
      "without syncing the select to _type, the dropdown always shows the first option " +
      "('Image + video') even when the active filter is image or video -- so 'Browse " +
      "library' lies about what it's showing, and any later filter change re-reads the " +
      "wrong displayed value and silently drops the video filter");
  });
});

describe("Loom left rail: rendered videos import like images do (issue #3)", () => {
  test("Cast's '+ add from gallery' opens the picker showing BOTH kinds", () => {
    assert.match(storyboardSrc, /\}\), "all", true\)\}>\+ add from gallery<\/button>/,
      "the Cast tray's add-from-gallery must open type=all so already-rendered videos " +
      "are in the default view -- opened image-only, a video can never be selected " +
      "without first discovering the type dropdown");
  });

  test("a picked video lands as a kind:'video' Cast asset exactly like images land", () => {
    // Cast's own add-from-picker callback derives kind/tag from is_video -- pin the
    // derivation so a future refactor can't quietly hardcode kind:"image" again. Footage's
    // "Browse library" no longer shares this shape at all (see the describe block below) --
    // it imports a REAL shot, not a Cast asset, so exactly one site should match now.
    const derivations = storyboardSrc.match(/const k = isVideo \? "video" : "image", pre = isVideo \? "@video" : "@image";/g) || [];
    assert.equal(derivations.length, 1,
      "expected exactly one Cast-asset-shaped pick derivation (the '+ add from gallery' " +
      "button); found " + derivations.length + " -- if Footage's 'Browse library' grew " +
      "this shape again it would mean footage import silently regressed back to " +
      "creating Cast references instead of real, placeable shots");
  });

  test("detailed Cast rows show a video asset's poster, not a bare film emoji", () => {
    assert.match(storyboardSrc, /as\.kind === "video" && src \? <img src=\{src\}/,
      "video assets resolve a /thumbs/<mid>.jpg poster via frameSrc just like images -- " +
      "rendering only a film emoji made a successful video import invisible in the " +
      "default (detailed) tray view");
  });
});

// Follow-up to issue #3, filed after live-testing the fix above: the picker-selection
// half was genuinely fixed (a rendered video is reachable and visibly imports), but every
// pick routed into Cast & Assets -- a reusable @tag PROMPT reference, not footage placed
// on the timeline. The Footage tab's own purpose is bringing an already-rendered clip in
// as a real shot; its "Browse library" button now does exactly that instead of sharing
// Cast's reference-adding shape (see the describe block above -- Cast keeps its own,
// separate "+ add from gallery" for the reference use case, video included).
describe("Footage tab: 'Browse library' imports a REAL placeable shot, not a Cast reference", () => {
  test("the button is locked to video (no type dropdown) and no longer builds a Cast asset", () => {
    assert.match(storyboardSrc, /}, "video"\)}>&#8981; Browse library<\/button>/,
      "Browse library must open the picker locked to video (kind=\"video\", no allowType " +
      "arg) -- an imported 'shot' can only ever be a video; offering the image/all switch " +
      "invited picking something that can't become footage");
    // The specific block that opens Browse library's picker -- not Cast's own, separate
    // "+ add from gallery" button (unaffected by this change, still setAssets-shaped;
    // covered by the derivation-count test above).
    const footageBlock = storyboardSrc.slice(
      storyboardSrc.indexOf("const footageList ="), storyboardSrc.indexOf("Browse library"));
    assert.doesNotMatch(footageBlock, /setAssets/,
      "Browse library's own pick callback must not build a Cast asset (setAssets) -- " +
      "that's the exact issue #3 follow-up bug: a pick landing as a prompt reference " +
      "instead of usable timeline footage");
  });

  test("a picked video calls importFootage (landInFirstAct + importedFootagePatch), not setAssets", () => {
    assert.match(storyboardSrc, /importPickedFootage\(mid, duration\)/,
      "Browse library's pick callback should route through importPickedFootage");
    assert.match(storyboardSrc, /setSelShot\(importFootage\(mid, dur\)\)/,
      "importPickedFootage must call importFootage and select the resulting shot");
  });

  test("importFootage lands the card via landInFirstAct + importedFootagePatch (loom-mutations.js)", () => {
    assert.match(storyboardSrc, /const c = newCard\(importedFootagePatch\(mediaId, duration\)\);/,
      "importFootage must build the new card from newCard()'s own defaults (matching a " +
      "freshly-added blank shot's shape) patched with importedFootagePatch's done/" +
      "resultMid/imported fields -- not a hand-rolled, independently-drifting shape");
    assert.match(storyboardSrc, /setProject\(\(p\) => landInFirstAct\(p, c, uid\(\)\)\);/,
      "importFootage must land the card via landInFirstAct -- first act, auto-created if " +
      "the project has none -- reusing the SAME appendCardToAct/appendAct mutators every " +
      "other card-adding path uses, not inventing a new act-picking mechanism");
  });

  test("an imported shot reuses the board's existing 'move to...' dropdown -- no new UI invented", () => {
    // moveCardToAct is the ONE mechanism shot cards use to change acts (rendered shots and
    // imported footage alike); this guards against a future change accidentally forking a
    // second, imported-only relocation control instead of reusing this one.
    assert.match(storyboardSrc, /onChange=\{\(ev\) => ev\.target\.value && moveCardToAct\(act\.id, e\.c, ev\.target\.value\)\}/,
      "expected the board's per-card 'move to...' select, reused as-is for every card " +
      "including imported footage -- see moveCardToAct's own def (loom-mutations.js) and " +
      "its useShotMutations wiring, both untouched by footage import");
  });

  test("imported cards are marked (provenance), not silently indistinguishable from a real render", () => {
    assert.match(storyboardSrc, /e\.c\.imported && <span className="lv-st imported"/,
      "the board card should flag an imported shot -- no PixAI task backs its resultMid, " +
      "unlike every other 'done' card, and that distinction should be visible, not just " +
      "an internal field nobody surfaces");
  });

  test("re-roll on an imported clip is a safe no-op -- live-verified against the REAL per-shot button, not assumed", () => {
    // Investigated, not assumed: generateShot's own !hasInput branch is NOT what protects a
    // per-shot "Generate video" click today -- generateShot has exactly one caller
    // (batchGenerate), whose `todo` filter already excludes status:"done" (which
    // importedFootagePatch always sets) before generateShot is ever reached, and the
    // per-shot Video-tab button lives entirely inside <mg-generate-drawer>'s OWN
    // _generate()/_hasAnyRef() (static/mg-generate-drawer.js), a separate, pre-existing
    // guard. Live-clicked against a real imported shot in a running server: no
    // /api/loom/generate request fired, the drawer showed its own existing
    // "Pick a source image first." with no crash and the footage untouched -- confirming
    // (b) from the brief ("already naturally a no-op/safe, investigate don't assume")
    // without needing a new imported-specific message on the operative path.
    assert.match(readFileSync(path.join(__dirname, "../../static/mg-generate-drawer.js"), "utf8"),
      /_hasAnyRef\(p\)/,
      "the per-shot drawer's own no-reference guard (the thing that actually runs when the " +
      "owner clicks 'Generate video' on an imported shot) must still exist");
    // generateShot's own message stays as a defensive fallback (its docstring-equivalent
    // comment explains exactly why it's currently unreachable for an imported card) in case
    // a future refactor ever re-routes per-shot generation back through it -- this pins that
    // it still exists and is still accurate, without claiming it's the live guard.
    assert.match(storyboardSrc, /const msg = c\.imported\s*\n\s*\? "Imported footage/,
      "generateShot's !hasInput branch should still special-case c.imported defensively");
  });

  test("batchGenerate/cost-estimate treat an imported shot as done -- no accidental resubmit or spend", () => {
    // Both gates key off status !== "done"; importedFootagePatch sets status:"done", so an
    // imported card is excluded from "Generate all" and the standing cost pill by the SAME
    // existing status check every other finished shot already relies on -- no special-
    // casing needed, and this guards that nobody adds an accidental imported-only carve-out
    // (or, worse, an imported-only INCLUSION) later.
    assert.match(storyboardSrc, /const todo = entries\.filter\(\(e\) => e\.c\.status !== "done" && e\.c\.status !== "wip"\);/);
    assert.match(storyboardSrc, /const nd = boardEntries\.filter\(\(e\) => e\.c\.status !== "done"\);/);
  });
});
