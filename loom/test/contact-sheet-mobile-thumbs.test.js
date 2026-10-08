import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// THE PHONE CONTACT SHEET SHOWS THE PICTURES. Each card drew a gradient box where the frame's
// thumbnail belongs, on the strength of a 2026-08-03 reading of the design's drift report ("placeholder
// thumbnails only"). That reading was wrong, and the owner reversed it on 2026-10-02: the list is
// useless without the pictures, the desktop sheet shows them, and the 60 px well was already drawn at
// thumbnail size. The well is filled with the frame's own thumbnail, sized by Data saver like every other
// phone thumbnail, lazy because a collection sheet can hold hundreds of frames; the gradient stays
// behind it as the fallback while a picture loads and if it fails.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const sheet = src("gallery/src/components/ContactSheetMobile.jsx");
const css = src("gallery/src/styles/contact-sheet-mobile.css");

describe("the card's thumbnail well holds the frame's picture", () => {
  test("an <img> inside .csm-thumb, fed by thumbSrc(f.thumb_url, saver), lazy and async", () => {
    assert.match(sheet, /<div className="csm-thumb" aria-hidden="true">\s*<img src=\{thumbSrc\(f\.thumb_url, saver\)\} alt="" loading="lazy" decoding="async"/);
  });

  test("Data saver is read the way every other phone surface reads it", () => {
    assert.match(sheet, /import useDataSaver from "\.\.\/hooks\/usePhonePrefs\.js";/);
    assert.match(sheet, /import \{ thumbSrc \} from "\.\.\/lib\/phoneCore\.js";/);
    assert.match(sheet, /const saver = useDataSaver\(\)\.active;/);
  });

  test("a failed picture steps aside so the gradient behind it shows", () => {
    assert.match(sheet, /onError=\{\(e\) => \{ e\.currentTarget\.style\.visibility = "hidden"; \}\}/);
  });

  test("the empty well is gone", () => {
    assert.doesNotMatch(sheet, /<div className="csm-thumb" aria-hidden="true" \/>/);
  });
});

describe("the well is styled to hold a picture, with the gradient kept behind it", () => {
  test("the image fills the 60 px well and crops to cover it", () => {
    assert.match(css, /\.csm-thumb img \{[^}]*width: 100%;[^}]*height: 100%;[^}]*object-fit: cover;[^}]*display: block;/);
  });

  test("the gradient is still the well's own background, and the well still clips", () => {
    const well = css.match(/\.csm-thumb \{[^}]*\}/);
    assert.ok(well, "the .csm-thumb rule exists");
    assert.match(well[0], /width: 60px; height: 60px;/);
    assert.match(well[0], /overflow: hidden;/);
    assert.match(well[0], /linear-gradient\(135deg/);
  });
});

describe("the 'deliberate, locked' comments are rewritten, not left to contradict the code", () => {
  test("the component's header no longer says the thumbnails are placeholders or unused", () => {
    assert.doesNotMatch(sheet, /PLACEHOLDER-QUALITY/);
    assert.doesNotMatch(sheet, /deliberately unused data/);
    assert.doesNotMatch(sheet, /NOT loaded/);
    assert.doesNotMatch(sheet, /placeholder-thumbnail DOM/);
    assert.match(sheet, /2026-10-02/);
  });

  test("the stylesheet no longer calls the well a locked placeholder", () => {
    assert.doesNotMatch(css, /deliberate, locked/);
    assert.doesNotMatch(css, /Placeholder-quality thumbnail/);
    assert.doesNotMatch(css, /Placeholder thumbnails only/);
    assert.match(css, /2026-10-02/);
  });
});
