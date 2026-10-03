import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { lightboxCount, pageOffset, positionLabel } from "../../gallery/src/lib/phoneCore.js";

// #64: THE PHONE'S "k of N" COUNTED ONE LOADED PAGE. The picture record said "14 of 100" when the
// filter matched thousands, and the Lightbox's "k OF N" had the same flaw, while Prev and Next walk
// the whole filtered set. The detail route now answers with the picture's place in that walk
// (`position`) and the walk's length (`nav_total`); the record prints them like the pager does, and
// the Lightbox adds the page it is standing on to its own place in the page.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const details = src("gallery/src/components/ImageDetailsMobile.jsx");
const lightbox = src("gallery/src/components/LightboxMobile.jsx");
const shell = src("gallery/src/components/AppMobile.jsx");

describe("positionLabel: the record's 'k of N', formatted like the pager", () => {
  test("a real position in a long walk reads with the pager's thousands separator", () => {
    assert.equal(positionLabel(14, 3240), "14 of " + (3240).toLocaleString());
    assert.match(positionLabel(14, 3240), /^14 of 3\D?240$/);
    assert.equal(positionLabel(1, 1), "1 of 1");
  });

  test("a missing or unusable number gives no label, never 'null of 5' or '0 of 0'", () => {
    for (const [p, t] of [[null, 5], [undefined, 5], [3, null], [3, undefined], [null, null],
      ["", 5], [3, ""], [0, 5], [3, 0], [-1, 5], ["x", 5], [3, NaN]]) {
      assert.equal(positionLabel(p, t), "", JSON.stringify([p, t]));
    }
  });

  test("numbers that arrive as strings still format", () => {
    assert.equal(positionLabel("3", "5"), "3 of 5");
  });
});

describe("pageOffset: how many pictures come before the loaded page", () => {
  test("page one starts at zero and each later page adds a full page", () => {
    assert.equal(pageOffset(1, 100), 0);
    assert.equal(pageOffset(2, 100), 100);
    assert.equal(pageOffset(5, 60), 240);
  });

  test("the server clamps a page to 200, so the offset does too", () => {
    assert.equal(pageOffset(3, 500), 400);
  });

  test("a missing page or size falls back to the front page and the default hundred", () => {
    assert.equal(pageOffset(undefined, 100), 0);
    assert.equal(pageOffset(0, 100), 0);
    assert.equal(pageOffset(2, undefined), 100);
    assert.equal(pageOffset(2, 0), 100);
  });
});

describe("lightboxCount: the viewer's big number and its 'OF N'", () => {
  test("page two of a long walk counts from the whole walk, not the page", () => {
    const c = lightboxCount(0, 100, 3240, 100);
    assert.equal(c.at, "101");
    assert.equal(c.of, (3240).toLocaleString());
  });

  test("the last picture of a page lands on the page's last place in the walk", () => {
    assert.equal(lightboxCount(99, 100, 3240, 100).at, "200");
  });

  test("with no total yet the viewer falls back to the page it holds, as it always did", () => {
    const c = lightboxCount(4, 0, null, 30);
    assert.deepEqual(c, { at: "5", of: "30" });
  });

  test("a total the page has outgrown (pictures deleted since) never reads 'k of fewer than k'", () => {
    const c = lightboxCount(9, 0, 5, 10);
    assert.equal(c.at, "10");
    assert.equal(c.of, "10");
  });
});

describe("source: neither label counts the loaded page any more", () => {
  test("the record reads the route's position and walk total", () => {
    assert.match(details, /positionLabel\(state\.data\.position, state\.data\.nav_total\)/);
    assert.match(details, /import \{[^}]*\bpositionLabel\b[^}]*\} from "\.\.\/lib\/phoneCore\.js"/);
    assert.doesNotMatch(details, /items\.length/);
    assert.doesNotMatch(details, /items\.findIndex/);
    assert.doesNotMatch(details, /scoped to\s+whichever page is currently loaded/);
  });

  test("the record no longer takes the loaded page as a prop", () => {
    assert.doesNotMatch(details, /advParams, items,/);
    assert.doesNotMatch(shell, /advParams=\{detailsAdvParams\} items=\{lib\.items\}/);
  });

  test("the viewer prints the walk's count, from the page offset and the total it is handed", () => {
    assert.match(lightbox, /lightboxCount\(index, offset, total, items\.length\)/);
    assert.match(lightbox, /<span className="lbm-index">\{count\.at\}<\/span>/);
    assert.match(lightbox, /<span className="lbm-total">OF \{count\.of\}<\/span>/);
    assert.doesNotMatch(lightbox, /OF \{items\.length\}/);
    assert.doesNotMatch(lightbox, /<span className="lbm-index">\{index \+ 1\}<\/span>/);
  });

  test("the shell hands the viewer the page offset and the total", () => {
    assert.match(shell, /offset=\{pageOffset\(lib\.page, lib\.perPage\)\} total=\{lib\.total\}/);
    assert.match(shell, /import \{[^}]*\bpageOffset\b[^}]*\} from "\.\.\/lib\/phoneCore\.js"/);
  });

  test("the detail route returns both numbers", () => {
    const py = src("moonglade_gallery.py");
    assert.match(py, /"position": position, "nav_total": len\(nav_ids\)/);
  });
});
