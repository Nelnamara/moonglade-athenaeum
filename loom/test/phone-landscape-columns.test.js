import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { anchorScrollTop, pickAnchor } from "../../gallery/src/lib/phoneCore.js";

/* #73: sideways, the gallery's columns stack like the upright two. The Phone Handoff drew lined-up rows
   (every row as tall as its tallest picture, so most of a short sideways screen was holes); the owner
   picked stacks on 2026-10-28. These pin the source shape, and the one thing a lane-major DOM order could
   break: the scroll anchor still finds the picture at the top of the view. */

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.join(here, "..", "..", "gallery", "src", rel), "utf8").split("\r\n").join("\n");

describe("the sideways run is dealt into stacked columns", () => {
  const src = read("components/GalleryGridMobile.jsx");
  const branch = src.slice(src.indexOf("if (cols > 2) {"), src.indexOf("const left = list.filter"));

  test("the cols > 2 branch deals round-robin into `cols` lanes", () => {
    assert.ok(branch.length > 40, "the cols > 2 branch was found");
    assert.match(branch, /Array\.from\(\{ length: cols \}, \(\) => \[\]\)/);
    assert.match(branch, /list\.forEach\(\(it, i\) => lanes\[i % cols\]\.push\(it\)\)/);
  });

  test("each lane is a glm-col inside the same glm-grid-rows container, with no stagger", () => {
    assert.match(branch, /className=\{"glm-grid glm-grid-rows"/);
    assert.match(branch, /gridTemplateColumns: "repeat\(" \+ cols \+ ", minmax\(0, 1fr\)\)"/);
    assert.match(branch, /<div key=\{n\} className="glm-col">\{lane\.map\(tile\)\}<\/div>/);
    assert.doesNotMatch(branch, /glm-col-off/, "Q4 draws no stagger");
  });

  test("the lanes' gap is the page's 6 px, and the upright backstop still keys on glm-grid-rows", () => {
    const css = read("styles/gallery-mobile.css");
    assert.match(css, /\.glm-grid-rows > \.glm-col \{ gap: 6px; \}/);
    assert.match(css, /\.glm-grid\.glm-grid-rows \{ grid-template-columns: repeat\(2, minmax\(0, 1fr\)\) !important; \}/);
  });
});

describe("a lane-major DOM order does not move the turn anchor", () => {
  // 4 lanes of 3: ids are reading order (a..l), laid out round-robin, so lane 0 holds a, e, i, ...
  // Pictures differ in height, so the lanes' tops drift apart. The DOM lists lane 0, lane 1, lane 2, lane 3.
  const lanes = [
    [{ id: "a", top: -300, bottom: -10 }, { id: "e", top: -4, bottom: 250 }, { id: "i", top: 256, bottom: 500 }],
    [{ id: "b", top: -120, bottom: 90 }, { id: "f", top: 96, bottom: 400 }, { id: "j", top: 406, bottom: 700 }],
    [{ id: "c", top: -40, bottom: 330 }, { id: "g", top: 336, bottom: 520 }, { id: "k", top: 526, bottom: 800 }],
    [{ id: "d", top: 10, bottom: 200 }, { id: "h", top: 206, bottom: 480 }, { id: "l", top: 486, bottom: 690 }],
  ];
  const domOrder = lanes.flat();
  const readingOrder = [...domOrder].sort((p, q) => p.id.localeCompare(q.id));

  test("the highest picture still in view is the same in either order", () => {
    assert.deepEqual(pickAnchor(domOrder, 0), pickAnchor(readingOrder, 0));
    assert.deepEqual(pickAnchor(domOrder, 0), { id: "b", offset: -120 }, "b is the highest picture still showing");
    assert.deepEqual(pickAnchor(domOrder, 100), { id: "c", offset: -140 });
  });

  test("and putting it back lands it at the same place", () => {
    const n = pickAnchor(domOrder, 0);
    // after the turn b sits at 700 while the view starts at 0: the scroller moves down by 700 - offset
    assert.equal(anchorScrollTop(500, 700, 0, n.offset), 500 + 700 + 120);
  });

  test("the anchor hook reads every [data-mid] under the scroller, not a row-major grid", () => {
    const h = read("hooks/useScrollAnchor.js");
    assert.match(h, /const TILE = "\[data-mid\]";/);
    assert.match(h, /host\.querySelectorAll\(TILE\)/);
    assert.doesNotMatch(h, /glm-grid|nth-child|children\[/, "nothing in the anchor depends on the grid's structure");
  });
});
