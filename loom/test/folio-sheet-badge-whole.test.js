import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE PHONE FOLIO'S DETAIL SHEET SHOWS THE WHOLE BADGE (2026-09-07).

   The owner's screenshot: on the phone, tapping a feat opens the detail sheet and the badge
   -- a round medallion -- sat in a wide box with its top and bottom cut off. The frame was
   right and the fit was wrong. `.fm-sheet-imgwrap` is a 1.6:1 box (the design's, from the
   phone Folio's handoff page) and the badge masters are square 1:1, so `object-fit: cover`
   could only fill that box by cropping the disc.

   This is a CSS guard, not a render one: there is no browser here, and the whole defect is
   one declaration. What it pins is (a) that the fit is never `cover` again, and (b) that the
   frame the design drew survives the fix -- an explicit aspect-ratio, not a box that
   collapsed to whatever the image felt like once `contain` stopped filling it. The pair
   matters together: `contain` with no ratio is a different bug wearing the same fix.

   The 1.6:1 frame itself is deliberate and stays: it is the design's, and it was drawn
   around the mock's WIDE per-ladder cover art, which the real square badge later replaced
   (FolioMobile.jsx's own deviation note 3, refined the same day). */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite: the repo stores LF
// (.gitattributes `* text=auto`) while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const fmCss = src("styles/folio-mobile.css");
const folioMobile = src("components/FolioMobile.jsx");

// Every declaration block whose selector mentions the sheet's image wrap -- read out of the
// stylesheet rather than named one by one, so a NEW `.fm-sheet-imgwrap ...` rule that
// reintroduces the crop is caught by the same assertions. Comments come out first, or a
// rule's "selector" swallows the prose block above it -- including the one that says
// `object-fit: cover` in order to explain why it is gone.
const wrapRules = [...fmCss.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  .map((m) => ({ sel: m[1].trim(), body: m[2] }))
  .filter((r) => /\.fm-sheet-imgwrap\b/.test(r.sel));
const imgRule = wrapRules.find((r) => /\.fm-sheet-imgwrap\s+img$/.test(r.sel));
const boxRule = wrapRules.find((r) => /^\.fm-sheet-imgwrap$/.test(r.sel));

describe("the phone Folio's detail sheet shows the whole badge", () => {
  test("the sheet's badge is NEVER object-fit: cover -- that is the crop itself", () => {
    assert.ok(imgRule, "no `.fm-sheet-imgwrap img` rule in folio-mobile.css at all");
    assert.doesNotMatch(imgRule.body, /object-fit:\s*cover/,
      "`.fm-sheet-imgwrap img` is back on `cover`: a square medallion in a 1.6:1 frame, "
      + "which is exactly the crop the owner photographed on 2026-09-07");
    // ...and no other rule in this group can put it back either
    for (const r of wrapRules) {
      assert.doesNotMatch(r.body, /object-fit:\s*cover/, r.sel + " sets object-fit: cover");
    }
  });

  test("it is shown whole and centred", () => {
    assert.match(imgRule.body, /object-fit:\s*contain/);
    assert.match(imgRule.body, /object-position:\s*center/);
    // the image still fills the frame it is fitted into, or `contain` has nothing to fit to
    assert.match(imgRule.body, /width:\s*100%/);
    assert.match(imgRule.body, /height:\s*100%/);
  });

  test("the frame keeps an EXPLICIT aspect ratio -- the design's box, not the image's", () => {
    assert.ok(boxRule, "no `.fm-sheet-imgwrap` rule in folio-mobile.css at all");
    assert.match(boxRule.body, /aspect-ratio:\s*1\.6\s*\/\s*1/,
      "the sheet's frame lost its explicit ratio; with `contain` the box would then take "
      + "its height from the badge instead of from the design");
    // the rest of the design's frame, untouched by the fit change
    assert.match(boxRule.body, /border-radius:\s*14px/);
    assert.match(boxRule.body, /overflow:\s*hidden/);
    // a dark ground for the letterboxing `contain` now leaves either side of the disc
    assert.match(boxRule.body, /background:\s*var\(--base\)/);
    // and the earned tier-glow is still the frame's
    const earned = wrapRules.find((r) => /\.fm-sheet-imgwrap\.earned$/.test(r.sel));
    assert.ok(earned, "the earned glow rule is gone");
    assert.match(earned.body, /box-shadow: 0 0 20px color-mix\(in srgb, var\(--tc\) 30%, transparent\)/);
  });

  test("the reason is written where the next reader will meet it, with the date", () => {
    assert.match(fmCss, /owner's phone screenshot, 2026-09-07/);
    assert.match(folioMobile, /REFINED 2026-09-07, on the owner's phone screenshot/);
  });

  test("shown at the frame's full height, it asks for the 384 bucket -- and hops on it", () => {
    /* badgeSrc/badgeHop key their ladder on the size they are handed (badgeArt.js), so a
       384 src with a size-less hop would look for a rung that is not on its own list and
       give up -- the badge would simply vanish on the .webp 404 instead of falling back to
       the still. The toast has always passed the pair (notify/ach.js); the sheet is the
       second place that shows an enlarged medallion, so it passes it too. */
    assert.match(folioMobile, /<img src=\{badgeSrc\(sheetAch\.id, 384\)\}/);
    assert.match(folioMobile,
      /onError=\{\(e\) => \{ if \(!badgeHop\(e\.currentTarget, sheetAch\.id, 384\)\) e\.currentTarget\.remove\(\); \}\}/);
    // the grid/rows/hero are NOT enlarged -- they stay on the 256 default
    assert.match(fmCss, /\.fm-row-thumbwrap img \{[^}]*object-fit: cover/);
    assert.doesNotMatch(folioMobile, /badgeSrc\(a\.id, 384\)/);
    assert.doesNotMatch(folioMobile, /badgeSrc\(tier\.id, 384\)/);
  });
});
