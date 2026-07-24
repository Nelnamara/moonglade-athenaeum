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

  test("Footage's 'Browse library' still opens video-first", () => {
    assert.match(storyboardSrc, /\}\), "video", true\)\}>&#8981; Browse library<\/button>/,
      "browse-the-library is the footage flow; it opens on Videos (now honestly " +
      "labeled, per the select-sync fix) with the type dropdown available to widen");
  });

  test("a picked video lands as a kind:'video' asset exactly like images land", () => {
    // Both add-from-picker callbacks derive kind/tag from is_video -- pin the derivation
    // so a future refactor can't quietly hardcode kind:"image" again.
    const derivations = storyboardSrc.match(/const k = isVideo \? "video" : "image", pre = isVideo \? "@video" : "@image";/g) || [];
    assert.ok(derivations.length >= 2,
      "both left-rail pick callbacks (Cast '+ add from gallery' and Footage 'Browse " +
      "library') must derive the asset kind/tag from the picked item's is_video flag; " +
      "found " + derivations.length + " derivation site(s)");
  });

  test("detailed Cast rows show a video asset's poster, not a bare film emoji", () => {
    assert.match(storyboardSrc, /as\.kind === "video" && src \? <img src=\{src\}/,
      "video assets resolve a /thumbs/<mid>.jpg poster via frameSrc just like images -- " +
      "rendering only a film emoji made a successful video import invisible in the " +
      "default (detailed) tray view");
  });
});
