// gallery/src/notify/badgeArt.js -- the badge <img>'s webp-first source ladder.
//
// An animated medallion is a `<id>.webp` dropped beside the stills; the server serves it
// through untouched and 404s when there isn't one. That 404 is the whole fallback
// mechanism, so this module is the client half of the contract the Python side
// (tests/test_badge_anim.py) proves from the route end:
//
//   * animated master FIRST, still thumb second -- nothing else in the ladder;
//   * the size bucket rides the STILL only (the animation is served whole, unresized,
//     so a ?size= on it would just fragment its cache entry);
//   * a miss is REMEMBERED. This is the one thing the module adds over the inline chain
//     the toast mascot uses: the mascot renders once per celebration, badges render by
//     the dozen in the Folio and re-render on every tab/search/ladder click, so without
//     the memo a still-only badge would re-pay its 404 on every mount;
//   * an exhausted (or off-ladder) src reports false, and the CALLER decides what the
//     hole looks like -- the Folio removes the element, the toast swaps in the emoji.
//     A masked card's mystery art is deliberately off-ladder and must stay that way.
import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  badgeSources, badgeSrc, badgeHop, _resetBadgeMemo,
} from "../../gallery/src/notify/badgeArt.js";

// The module touches exactly two things on the element: getAttribute("src") to read, and
// .src to write. That is the whole DOM surface, so this stands in for an <img>.
function fakeImg(src) {
  return {
    src,
    getAttribute(name) { return name === "src" ? this.src : null; },
  };
}

beforeEach(() => { _resetBadgeMemo(); });

describe("badgeSources -- the ladder", () => {
  test("animated master first, still thumb second, nothing else", () => {
    assert.deepEqual(badgeSources("loremaster"), [
      "/badge-thumb/loremaster.webp",
      "/badge-thumb/loremaster.png",
    ]);
  });

  test("the size bucket rides the STILL only", () => {
    // 384 is the toast's crisper thumb; the animation is served whole either way.
    assert.deepEqual(badgeSources("loremaster", 384), [
      "/badge-thumb/loremaster.webp",
      "/badge-thumb/loremaster.png?size=384",
    ]);
    // Anything that is not the 384 bucket is the 256 default -- no ?size= at all.
    assert.deepEqual(badgeSources("loremaster", 256), badgeSources("loremaster"));
    assert.deepEqual(badgeSources("loremaster", 999), badgeSources("loremaster"));
  });

  test("the id is URL-encoded, both rungs", () => {
    const [anim, still] = badgeSources("a b/c?d");
    assert.equal(anim, "/badge-thumb/a%20b%2Fc%3Fd.webp");
    assert.equal(still, "/badge-thumb/a%20b%2Fc%3Fd.png");
  });
});

describe("badgeSrc / badgeHop -- walking it", () => {
  test("a badge starts on the animated master", () => {
    assert.equal(badgeSrc("loremaster"), "/badge-thumb/loremaster.webp");
    assert.equal(badgeSrc("loremaster", 384), "/badge-thumb/loremaster.webp");
  });

  test("the webp's 404 hops to the still and reports that it handled it", () => {
    const img = fakeImg("/badge-thumb/loremaster.webp");
    assert.equal(badgeHop(img, "loremaster"), true);
    assert.equal(img.src, "/badge-thumb/loremaster.png");
  });

  test("the still's 404 exhausts the ladder -- the caller takes it from there", () => {
    const img = fakeImg("/badge-thumb/loremaster.png");
    assert.equal(badgeHop(img, "loremaster"), false);
    assert.equal(img.src, "/badge-thumb/loremaster.png", "no further hop is invented");
  });

  test("the toast's 384 bucket hops to the 384 still, not the 256 one", () => {
    const img = fakeImg("/badge-thumb/loremaster.webp");
    assert.equal(badgeHop(img, "loremaster", 384), true);
    assert.equal(img.src, "/badge-thumb/loremaster.png?size=384");
  });

  test("an off-ladder src (a masked card's mystery art) is not hopped", () => {
    const img = fakeImg("/branding/mystery/secret_feat.png");
    assert.equal(badgeHop(img, "masked-42"), false);
    assert.equal(img.src, "/branding/mystery/secret_feat.png");
  });

  test("a null element is a no-op, not a throw", () => {
    assert.equal(badgeHop(null, "loremaster"), false);
  });
});

describe("the memo -- a miss is paid once", () => {
  test("after one miss, later mounts of that id start on the still", () => {
    assert.equal(badgeSrc("loremaster"), "/badge-thumb/loremaster.webp");
    badgeHop(fakeImg("/badge-thumb/loremaster.webp"), "loremaster");
    assert.equal(badgeSrc("loremaster"), "/badge-thumb/loremaster.png");
    assert.equal(badgeSrc("loremaster", 384), "/badge-thumb/loremaster.png?size=384");
  });

  test("the memo is PER ID -- one still-only badge does not condemn the rest", () => {
    badgeHop(fakeImg("/badge-thumb/loremaster.webp"), "loremaster");
    assert.equal(badgeSrc("first-light"), "/badge-thumb/first-light.webp");
  });

  test("it only ever moves forward: a still's 404 cannot rewind it to the webp", () => {
    badgeHop(fakeImg("/badge-thumb/loremaster.webp"), "loremaster");
    badgeHop(fakeImg("/badge-thumb/loremaster.png"), "loremaster");   // ladder spent
    assert.equal(badgeSrc("loremaster"), "/badge-thumb/loremaster.png");
  });

  test("a fresh page starts clean -- a dropped-in animation is picked up on reload", () => {
    badgeHop(fakeImg("/badge-thumb/loremaster.webp"), "loremaster");
    _resetBadgeMemo();
    assert.equal(badgeSrc("loremaster"), "/badge-thumb/loremaster.webp");
  });
});
