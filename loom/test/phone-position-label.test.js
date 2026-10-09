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
});

// The desktop record had the same flaw (its header said "14 of 100" the same way), and it reads the same
// two numbers from the same route.
describe("source: the desktop record counts the whole walk too", () => {
  const desktop = src("gallery/src/components/DetailsView.jsx");
  const app = src("gallery/src/App.jsx");

  test("the header label comes from the route's position and walk total", () => {
    assert.match(desktop, /positionLabel\(state\.data\.position, state\.data\.nav_total\)/);
    assert.match(desktop, /import \{ positionLabel \} from "\.\.\/lib\/phoneCore\.js";/);
    assert.match(desktop, /\{indexLabel \? <span className="detail-index">\{indexLabel\}<\/span> : null\}/);
  });

  test("it no longer counts inside the loaded page", () => {
    assert.doesNotMatch(desktop, /items\.length/);
    assert.doesNotMatch(desktop, /items\.findIndex/);
    assert.doesNotMatch(desktop, /detailIdx/);
  });

  test("it no longer takes the loaded page as a prop, and App no longer hands it over", () => {
    assert.doesNotMatch(desktop, /\n\s*items, onOpenLightbox/);
    const call = app.slice(app.indexOf("<DetailsView"), app.indexOf("onOpenLightbox={(mid)", app.indexOf("<DetailsView")));
    assert.ok(call.length > 0, "found the DetailsView call site");
    assert.doesNotMatch(call, /items=\{items\}/);
    // the Lightbox hand-off still reads the loaded page: that is its job
    assert.match(app, /onOpenLightbox=\{\(mid\) => \{\s*const i = items\.findIndex\(\(it\) => it\.media_id === mid\);/);
  });
});

// #74, the owner's walk of 2026-10-03: the desktop Lightbox's bar read "{k} / {page size}" and then
// "OF {page size}" beside it -- counted within the loaded page, and the total twice. It now shows the
// picture's true place in the walk and the walk's length once, with the phone viewer's helpers: the
// pictures before the loaded page (pageOffset) plus its place in the page, over the library total.
describe("source: the desktop Lightbox counts the whole walk, once (#74)", () => {
  const lbx = src("gallery/src/components/Lightbox.jsx");
  const app = src("gallery/src/App.jsx");

  test("its bar prints the walk's place and length, once each", () => {
    assert.match(lbx, /const count = lightboxCount\(index, offset, total, items\.length\);/);
    assert.match(lbx, /<b>\{count\.at\}<\/b>\s*<span>OF \{count\.of\}<\/span>/);
    assert.match(lbx, /import \{ lightboxCount \} from "\.\.\/lib\/phoneCore\.js";/);
  });

  test("it no longer counts inside the loaded page, or says the total twice", () => {
    assert.doesNotMatch(lbx, /\{index \+ 1\} \/ \{items\.length\}/);
    assert.doesNotMatch(lbx, /OF \{items\.length\}/);
  });

  test("App hands it the page offset and the library total, as the phone shell does", () => {
    const call = app.slice(app.indexOf("<Lightbox"), app.indexOf("/>", app.indexOf("<Lightbox")));
    assert.match(call, /offset=\{pageOffset\(page, perPage\)\} total=\{total\}/);
    assert.match(app, /import \{[^}]*\bpageOffset\b[^}]*\} from "\.\/lib\/phoneCore\.js"/);
  });
});
