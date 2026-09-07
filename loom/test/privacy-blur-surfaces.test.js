import { test, describe, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  PRIVACY_BLUR_KEY, PRIVACY_BLUR_CLASS, isPrivacyBlurOn, setPrivacyBlurOn, privacyBlurClass,
} from "../../gallery/src/lib/privacyBlur.js";

/* THE PRIVACY BLUR REACHES EVERY THUMBNAIL SURFACE (2026-09-07).

   The eye toggle frosts the library grid and always has, through .mgg-blur on the gridwrap.
   The gallery picker and the generate drawer's reference slots had blur rules of their own
   -- but keyed on `body.privacy-blur`, and nothing in this app has ever set a class on
   <body>. So those two rules could not match, on either shell: you could turn the blur on,
   see the grid frost, then open the picker and have the same flagged thumbnails render
   sharp. That is the bug this file guards.

   Two halves, tested two ways, following blur-pref.test.js next door. The STORAGE logic is
   a real import -- privacyBlur.js takes no React and no DOM, exactly so it can run here.
   The WIRING (who reads it, and what class they put where) is a source guard, the
   established pattern for this suite, since there is no React harness in this runner.

   NOTE the deliberate difference from blurPref.js: that module stores blur OFF (mg_noblur,
   inverted, because popup blur is the historical default). This one stores blur ON --
   privacy blur is off until you ask for it. Do not "make them consistent". */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

function fakeStorage() {
  const map = new Map();
  return {
    throws: false,
    getItem(k) { if (this.throws) throw new Error("blocked"); return map.has(k) ? map.get(k) : null; },
    setItem(k, v) { if (this.throws) throw new Error("blocked"); map.set(k, String(v)); },
    raw: map,
  };
}

describe("privacyBlur -- the stored preference", () => {
  afterEach(() => { delete globalThis.localStorage; });

  test("the key is the classic gallery's, unchanged -- an existing install keeps its setting", () => {
    assert.equal(PRIVACY_BLUR_KEY, "gallery_privacy_blur");
  });

  test("no stored value means the blur is OFF -- the opposite of blurPref, on purpose", () => {
    globalThis.localStorage = fakeStorage();
    assert.equal(isPrivacyBlurOn(), false);
  });

  test('only an explicit "1" turns the blur on', () => {
    const ls = fakeStorage();
    globalThis.localStorage = ls;
    ls.raw.set(PRIVACY_BLUR_KEY, "1");
    assert.equal(isPrivacyBlurOn(), true);
    for (const junk of ["", "0", "true", "yes"]) {
      ls.raw.set(PRIVACY_BLUR_KEY, junk);
      assert.equal(isPrivacyBlurOn(), false, junk);
    }
  });

  test("storage that THROWS reads as no preference, not as a crash", () => {
    const ls = fakeStorage();
    ls.throws = true;
    globalThis.localStorage = ls;
    assert.equal(isPrivacyBlurOn(), false);
    assert.doesNotThrow(() => setPrivacyBlurOn(true));
  });

  test("no localStorage global at all is the same -- blur off, no throw", () => {
    assert.equal(isPrivacyBlurOn(), false);
  });

  test('on writes "1", off writes the empty string, and a round trip survives', () => {
    const ls = fakeStorage();
    globalThis.localStorage = ls;
    setPrivacyBlurOn(true);
    assert.equal(ls.raw.get(PRIVACY_BLUR_KEY), "1");
    assert.equal(isPrivacyBlurOn(), true);
    setPrivacyBlurOn(false);
    assert.equal(ls.raw.get(PRIVACY_BLUR_KEY), "");
    assert.equal(isPrivacyBlurOn(), false);
  });

  test("privacyBlurClass emits a LEADING space so it concatenates onto a class string", () => {
    assert.equal(privacyBlurClass(true), " " + PRIVACY_BLUR_CLASS);
    assert.equal(privacyBlurClass(false), "");
    assert.equal(PRIVACY_BLUR_CLASS, "mg-blur");
  });
});

/* ---------------------------------------------------------------------------------------
   THE WIRING. Source guards: nothing below fails loudly at runtime -- the app keeps
   working, the blur just stops reaching a surface, silently, which is the whole bug. ----*/

const app = src("App.jsx");
const picker = src("components/GalleryPicker.jsx");
const drawer = src("components/VideoDrawer.jsx");
const grid = src("components/Grid.jsx");
const pickerCss = src("styles/gallery-picker.css");
const drawerCss = src("styles/gen-drawer.css");
const gridCss = src("styles/grid.css");

describe("one store, not three", () => {
  test("App.jsx reads and writes the preference through the module, not a raw key", () => {
    assert.match(app, /import \{ isPrivacyBlurOn, setPrivacyBlurOn \} from "\.\/lib\/privacyBlur\.js";/);
    assert.match(app, /useState\(isPrivacyBlurOn\)/);
    assert.match(app, /setPrivacyBlurOn\(v\);/);
  });

  test("no surface spells the storage key itself any more", () => {
    // A second literal is how the picker and the drawer drifted from the grid in the first
    // place. The key belongs to privacyBlur.js and to nothing else.
    for (const [name, text] of [["App.jsx", app], ["GalleryPicker.jsx", picker],
                                ["VideoDrawer.jsx", drawer], ["Grid.jsx", grid]]) {
      assert.ok(!text.includes('"gallery_privacy_blur"'),
        name + " hard-codes the privacy-blur storage key; import privacyBlur.js instead");
    }
  });
});

describe("every thumbnail surface carries the class", () => {
  test("the grid still blurs the way it always has", () => {
    assert.match(grid, /"gridwrap" \+ \(blur \? " mgg-blur" : ""\)/);
    assert.match(gridCss, /\.mgg-blur \.mgg-card\.nsfw \.mgg-art/);
  });

  test("the gallery picker reads the SAME preference and puts .mg-blur on its own root", () => {
    assert.match(picker, /import \{ isPrivacyBlurOn, privacyBlurClass \} from "\.\.\/lib\/privacyBlur\.js";/);
    assert.match(picker, /privacyBlurClass\(isPrivacyBlurOn\(\)\)/);
    // ...and it must land on the same string that becomes the root's className.
    const cls = picker.slice(picker.indexOf('const cls = "mg-gallery-picker"'));
    assert.match(cls.slice(0, 300), /privacyBlurClass\(isPrivacyBlurOn\(\)\)/,
      "the class is computed but not on the picker's root");
  });

  test("the generate drawer does the same on .gen-drawer", () => {
    assert.match(drawer, /import \{ isPrivacyBlurOn, privacyBlurClass \} from "\.\.\/lib\/privacyBlur\.js";/);
    const root = drawer.slice(drawer.indexOf('className={"gen-drawer"'));
    assert.match(root.slice(0, 400), /privacyBlurClass\(isPrivacyBlurOn\(\)\)/,
      "the drawer root does not carry the privacy-blur class");
  });

  test("it is read at RENDER time, not frozen into state at mount", () => {
    // useState(isPrivacyBlurOn) in either of these would go stale: the drawer stays mounted
    // across a toggle flip, and the Loom's picker has no App state behind it at all.
    assert.doesNotMatch(picker, /useState\(isPrivacyBlurOn/);
    assert.doesNotMatch(drawer, /useState\(isPrivacyBlurOn/);
  });
});

describe("the stylesheets answer the class the components set", () => {
  test("nothing is keyed on <body> any more -- that selector never matched", () => {
    assert.ok(!pickerCss.includes("body.privacy-blur .mg-gallery-picker"),
      "gallery-picker.css is body-scoped again; nothing sets a class on <body>");
    assert.ok(!drawerCss.includes("body.privacy-blur .gen-drawer"),
      "gen-drawer.css is body-scoped again; nothing sets a class on <body>");
  });

  test("the picker's three rules are scoped to its own root", () => {
    assert.match(pickerCss, /\.mg-gallery-picker\.mg-blur \.mg-pk-cell img\{/);
    assert.match(pickerCss, /\.mg-gallery-picker\.mg-blur \.mg-pk-cell\[data-nsfw="1"\] img\{/);
    assert.match(pickerCss, /\.mg-gallery-picker\.mg-blur \.mg-pk-cell:hover img\{/);
  });

  test("the drawer's three rules are scoped to its own root", () => {
    assert.match(drawerCss, /\.gen-drawer\.mg-blur \.mgd-slot img\{/);
    assert.match(drawerCss, /\.gen-drawer\.mg-blur \.mgd-slot\[data-nsfw="1"\] img\{/);
    assert.match(drawerCss, /\.gen-drawer\.mg-blur \.mgd-slot:hover img\{/);
  });

  test("all three surfaces keep the classic 16px / 28px-flagged / hover-reveals semantics", () => {
    for (const [name, css, sel] of [
      ["picker", pickerCss, ".mg-gallery-picker.mg-blur"],
      ["drawer", drawerCss, ".gen-drawer.mg-blur"],
    ]) {
      const block = css.slice(css.indexOf(sel));
      assert.match(block, /blur\(16px\)/, name + " lost the 16px base blur");
      assert.match(block, /blur\(28px\)/, name + " lost the heavier flagged blur");
      assert.match(block, /filter:none/, name + " lost hover-reveals");
    }
    assert.match(gridCss, /\.mgg-blur \.mgg-art \{ filter: blur\(16px\); \}/);
    assert.match(gridCss, /\.mgg-blur \.mgg-card\.nsfw \.mgg-art \{ filter: blur\(28px\); \}/);
  });
});
