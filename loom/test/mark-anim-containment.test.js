import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE MARK ANIMATIONS STAY INSIDE THE MARK (2026-09-04).

   THE BUG THIS EXISTS FOR. The eclipse treatment moved its umbra by translating the
   ::before BOX -- translate(-80%, 10%) <-> (80%, -10%) on a box inset 6% -- which put
   about 62px of dark disc past the mark's right edge. The mark lives at the right end
   of the header, 22px from the window edge, and NOTHING clips it: `.mgx-bnr` is
   deliberately overflow:visible so the halo and the moondust field can spill. So the
   DOCUMENT grew to fit the escaping box and the whole page gained a horizontal
   scrollbar that pumped in and out in time with the orbit. Measured live on the
   owner's install and on the staging build; measured again here in a driven browser
   at 25px of oscillating overflow (0 after the fix).

   WHY A TEST AND NOT JUST THE FIX. Nothing about that failure is loud. Every element
   is where the stylesheet says it is, every animation runs, no assertion in the suite
   moves; the only symptom is a scrollbar the page should not have. The next treatment
   written the same way would ship the same way. So the scan below is structural: it
   walks every rule in mark-anims.css, resolves the keyframes each one names, works out
   how far the animated box actually reaches, and fails if it reaches past the header's
   own right-hand gutter.

   THE BUDGET IS READ, NOT TYPED. `.mgx-mark` is 96px and `.mgx-navcol` pads it 22px
   from the window edge (both out of shell.css, parsed below), so an effect may hang
   22/96 = 22.9% of the mark past its own edge before it starts widening the document.
   Narrow the padding or grow the mark and this test tightens itself. The brief's
   simpler rule -- "no translate past (100% - inset)" -- would have failed `mist`
   (6% out, ~6px, nowhere near the edge) while passing an 80% translate on a box inset
   6%, which is the actual bug: the two numbers are in different units. Extent-versus-
   gutter is the same idea measured properly.

   WHAT IT CANNOT COMPUTE. Two animated children are sized by their CONTENT rather than
   by the stylesheet -- classic's corner spark and twinkle's constellation, both bare
   glyphs. They are listed in KNOWN_UNSIZED with the numbers measured in the browser
   instead, and the last test asserts that list EXACTLY, so a new content-sized animated
   child fails here until somebody measures it too. Moondust's canvas is sized by JS and
   never reaches this scan at all; the note above MOONDUST_OVERHANG_RATIO carries its
   measurement, and one test pins the ratio so a change to it cannot pass unnoticed. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings are normalized on read: the repo stores LF (.gitattributes `* text=auto`)
// while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, " ");

const anims = stripComments(src("styles/mark-anims.css"));
const shell = stripComments(src("styles/shell.css"));

/* ---- the geometry the budget comes from ---------------------------------------- */

/** `.mgx-mark`'s own width, from shell.css. Line-anchored so `.mgx-bnr.slim .mgx-mark`
    (the 56px slim override) cannot be mistaken for it. */
function markWidthPx() {
  const m = shell.match(/(?:^|\n)\.mgx-mark\s*\{([^}]*)\}/);
  assert.ok(m, "shell.css no longer has a bare `.mgx-mark` rule");
  const w = m[1].match(/width:\s*(\d+(?:\.\d+)?)px/);
  assert.ok(w, "`.mgx-mark` no longer states its width in px");
  return parseFloat(w[1]);
}

/** The hero banner's right-hand padding: the only thing between the mark's right edge
    and the window's. `.mgx-navcol { padding: 16px 22px 0; }` -> 22. */
function navcolGutterPx() {
  const m = shell.match(/(?:^|\n)\.mgx-navcol\s*\{([^}]*)\}/);
  assert.ok(m, "shell.css no longer has a bare `.mgx-navcol` rule");
  const p = m[1].match(/padding:\s*([^;]+)/);
  assert.ok(p, "`.mgx-navcol` no longer states a padding shorthand");
  const parts = p[1].trim().split(/\s+/);
  assert.ok(parts.length >= 2, "`.mgx-navcol` padding is not a multi-value shorthand");
  const right = parts[1].match(/^(\d+(?:\.\d+)?)px$/);
  assert.ok(right, "`.mgx-navcol`'s horizontal padding is no longer a px length");
  return parseFloat(right[1]);
}

const MARK_PX = markWidthPx();
const GUTTER_PX = navcolGutterPx();
/** How far, as a percentage of the mark, an effect may hang past the mark's right edge
    before the document itself has to grow. */
const BUDGET_PCT = (GUTTER_PX / MARK_PX) * 100;

/* ---- parsing -------------------------------------------------------------------- */

/** name -> keyframe body. mark-anims.css owns every keyframe its own rules name. */
function keyframesOf(css) {
  const out = new Map();
  const re = /@keyframes\s+([\w-]+)\s*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1, i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    out.set(m[1], css.slice(re.lastIndex, i - 1));
  }
  return out;
}

/** Every `sel { body }` pair. @keyframes and @media wrappers drop out on their own:
    their braces cannot match `[^{}]`, so only innermost rules are yielded. */
function* rules(css) {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const sel = m[1].trim();
    if (!sel || sel.startsWith("@")) continue;
    yield { sel, body: m[2].replace(/\s+/g, " ").trim() };
  }
}

const KF = keyframesOf(anims);

/** The horizontal box of an animated element, in percent of the mark, from its own
    declarations. A pseudo-element that states no geometry inherits the shared
    `.mgx-mark::before, .mgx-mark::after { inset: 0 }` at the top of the file and so
    fills the mark exactly; a real child that states none is sized by its content.
    Returns null when the box is content- or script-sized -- see KNOWN_UNSIZED. */
function boxOf(sel, body) {
  const inset = body.match(/(?:^|[\s;])inset:\s*(-?\d+(?:\.\d+)?)%/);
  if (inset) {
    const i = parseFloat(inset[1]);
    return { left: i, width: 100 - 2 * i };
  }
  if (/(?:^|[\s;])inset:\s*auto/.test(body) || /(?:^|[\s;])(?:left|right|top):/.test(body)) {
    const left = body.match(/(?:^|[\s;])left:\s*(-?\d+(?:\.\d+)?)%/);
    const width = body.match(/(?:^|[\s;])width:\s*(-?\d+(?:\.\d+)?)%/);
    if (left && width) return { left: parseFloat(left[1]), width: parseFloat(width[1]) };
    return null;                               // content-sized: cannot be computed here
  }
  if (/(?:^|[\s;])width:\s*/.test(body) && !/(?:^|[\s;])width:\s*\d+(?:\.\d+)?%/.test(body)) {
    return null;                               // a px/em width: not mark-relative
  }
  if (!/::(?:before|after)\s*$/.test(sel)) return null;   // a content-sized child
  return { left: 0, width: 100 };              // the shared `.mgx-mark::before` default
}

/** The worst rightward reach a keyframe gives a box, in percent of the mark.
    - translate X is a percentage of the ELEMENT's own width (CSS transform semantics),
    - scale grows the element about its centre.
    Rotation is ignored: every rotate on this roster is on a hairline or a glyph, where
    the extra reach is under a pixel. */
function reachOf(box, kfBody) {
  let maxTx = 0, maxScale = 1;
  for (const t of kfBody.match(/transform:\s*([^;}]+)/g) || []) {
    for (const args of t.match(/translate(?:X|3d)?\(([^)]*)\)/g) || []) {
      const first = args.replace(/^translate(?:X|3d)?\(/, "").split(",")[0].trim();
      const pct = first.match(/^(-?\d+(?:\.\d+)?)%$/);
      if (pct) maxTx = Math.max(maxTx, parseFloat(pct[1]));
    }
    for (const s of t.match(/scale\(([^)]*)\)/g) || []) {
      const v = parseFloat(s.replace(/^scale\(/, ""));
      if (Number.isFinite(v)) maxScale = Math.max(maxScale, v);
    }
  }
  const centre = box.left + box.width / 2;
  const halfGrown = (box.width / 2) * maxScale;
  return centre + halfGrown + (maxTx / 100) * box.width;
}

/** Every `.mgx-mark…` rule that runs an animation, with the reach it produces. */
function animatedRules() {
  const out = [];
  for (const r of rules(anims)) {
    if (!/^\.mgx-mark/.test(r.sel)) continue;
    const m = r.body.match(/(?:^|[\s;])animation:\s*([^;]+)/);
    if (!m || /^\s*none/.test(m[1])) continue;
    const names = m[1].split(",").map((item) =>
      item.trim().split(/\s+/).find((tok) => KF.has(tok))).filter(Boolean);
    if (!names.length) continue;
    // A treatment that animates only `filter`, `background-position` or opacity cannot
    // move its box at all, so its geometry never has to be worked out. Only a keyframe
    // that touches `transform` can carry an element out of the mark.
    const movesBox = names.some((n) => /transform:/.test(KF.get(n)));
    const box = boxOf(r.sel, r.body);
    const reach = !movesBox || box == null ? null
      : Math.max(...names.map((n) => reachOf(box, KF.get(n))));
    out.push({ ...r, names, movesBox, box, reach,
               overhang: reach == null ? null : reach - 100 });
  }
  return out;
}

const animated = animatedRules();

/* Animated children of the mark whose box the stylesheet does not state, each with the
   measurement that stands in for the computation. Kept as data, not as silence: the last
   test asserts this list exactly, so a new one fails here until somebody measures it. */
const KNOWN_UNSIZED = new Map([
  [".mgx-mark.mark-anim-classic::after",
   "the corner spark: a content-sized glyph at top/right -2% (font-size .55em), so its " +
   "box hangs about 2px past the mark and mgv2ClassicSpark only scales it to 1. " +
   "Measured 0px of document overflow across a full cycle, hero and slim."],
  [".mgx-mark.mark-anim-twinkle i",
   "three content-sized glyphs (font-size .24-.42em). The furthest, nth-child(4), sits " +
   "at right:-9% -- about 9px past the mark at hero, well inside the 22px gutter. " +
   "Measured 0px of document overflow across a full cycle, hero and slim."],
]);

/* Not an `animation:` rule at all, so the scan above never sees it, but it is the one
   part of the roster that DOES widen the document -- recorded here so the audit is not
   lost. `.mgx-mark-dust` is a canvas MarkDust.jsx sizes at 2.4x the mark and centres on
   it, i.e. 0.7x the mark (67px at hero) past every edge, animated or not. At hero that
   is 30px of permanent horizontal document overflow with the scrollbar gutter reserved,
   ~45px without; at slim (74px of navcol padding) it is 0. Every containment for it --
   clipping the mark, or shrinking the field -- changes what the treatment looks like,
   which is the owner's call, not a test's. Measured 2026-09-04. */
const MOONDUST_OVERHANG_RATIO = 0.7;

describe("the scan sees the roster at all", () => {
  test("every animated treatment rule is found", () => {
    const sels = animated.map((a) => a.sel);
    for (const expected of [
      ".mgx-mark.mark-anim-glow::before",
      ".mgx-mark.mark-anim-shine::before",
      ".mgx-mark.mark-anim-aurora::before",
      ".mgx-mark.mark-anim-mist::before",
      ".mgx-mark.mark-anim-mist::after",
      ".mgx-mark.mark-anim-classic::before",
      ".mgx-mark.mark-anim-classic::after",
      ".mgx-mark.mark-anim-shoot::before",
      ".mgx-mark.mark-anim-eclipse::before",
      ".mgx-mark.mark-anim-twinkle i",
    ]) assert.ok(sels.includes(expected), "the scan missed " + expected);
  });

  test("the keyframes those rules name all resolve", () => {
    for (const a of animated) {
      assert.ok(a.names.length, a.sel + " runs an animation no keyframe backs");
      for (const n of a.names) assert.ok(KF.has(n), n + " is not defined in mark-anims.css");
    }
  });

  test("the budget is read out of shell.css, not typed in here", () => {
    assert.equal(MARK_PX, 96);                 // the marks workshop's hero size
    assert.equal(GUTTER_PX, 22);               // .mgx-navcol's right padding
    assert.ok(BUDGET_PCT > 22 && BUDGET_PCT < 23, "budget drifted: " + BUDGET_PCT);
  });
});

describe("no mark animation carries its box out past the header's gutter", () => {
  for (const a of animated.filter((x) => x.movesBox && x.box != null)) {
    test(a.sel + " stays within the mark + gutter", () => {
      assert.ok(
        a.overhang <= BUDGET_PCT,
        a.sel + " reaches " + a.reach.toFixed(1) + "% of the mark (" +
        a.overhang.toFixed(1) + "% past its right edge) via " + a.names.join(" + ") +
        ". The budget is " + BUDGET_PCT.toFixed(1) + "% -- past that, the banner row is " +
        "overflow:visible and the DOCUMENT grows a horizontal scrollbar. Contain the " +
        "travel inside the box (the eclipse treatment does it with background-position) " +
        "rather than moving the box out of the mark.");
    });
  }

  test("the check is not passing vacuously -- it computes real boxes", () => {
    const computed = animated.filter((a) => a.movesBox && a.box != null);
    assert.ok(computed.length >= 4, "only " + computed.length + " boxes computed");
    // glow's bloom is the closest any treatment comes to the edge; if the parser has
    // stopped reading insets it will read 0 here instead of ~19.
    const glow = computed.find((a) => a.sel === ".mgx-mark.mark-anim-glow::before");
    assert.ok(glow.overhang > 10, "glow's -14% inset + 1.08 bloom no longer computes");
  });

  test("the shape that caused the bug fails the check", () => {
    // The pre-fix eclipse, verbatim, run through the same maths.
    const box = boxOf(".mgx-mark.mark-anim-eclipse::before",
                      "inset: 6%; border-radius: 50%;");
    const reach = reachOf(box, "0%, 100% { transform: translate(-80%, 10%); } " +
                               "50% { transform: translate(80%, -10%); }");
    assert.ok(reach - 100 > BUDGET_PCT,
      "the old eclipse would now pass -- the guard has stopped guarding");
  });
});

describe("the eclipse umbra travels as paint, not as a moving box", () => {
  test("mgv2Eclipse animates background-position and no transform", () => {
    const kf = KF.get("mgv2Eclipse");
    assert.ok(kf, "mgv2Eclipse is gone");
    assert.match(kf, /background-position:/);
    assert.doesNotMatch(kf, /transform:/,
      "the umbra is moving its box again -- that is the bug that made the page scroll " +
      "sideways; move the paint instead");
  });

  test("the umbra box is still inset inside the mark", () => {
    const r = animated.find((a) => a.sel === ".mgx-mark.mark-anim-eclipse::before");
    assert.ok(/inset:\s*6%/.test(r.body));
    assert.ok(/background-repeat:\s*no-repeat/.test(r.body),
      "without no-repeat the gradient tiles and the sweep stops being a sweep");
  });

  test("it still rides --anim-speed like the rest of the roster", () => {
    const r = animated.find((a) => a.sel === ".mgx-mark.mark-anim-eclipse::before");
    assert.match(r.body, /animation:\s*mgv2Eclipse\s+calc\(5s\s*\/\s*var\(--anim-speed\)\)/);
  });
});

describe("the reduced-motion contract still covers every animated part", () => {
  const block = anims.match(
    /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/);

  test("the block is there", () => assert.ok(block));

  test("it silences both pseudo-elements, the constellation and the tilt/sheen/art", () => {
    const b = block[1];
    for (const sel of [".mgx-mark .mgx-mark-tilt", ".mgx-mark .mgx-mark-sheen",
                       ".mgx-mark .mgx-mark-tilt img", ".mgx-mark i",
                       ".mgx-mark::before", ".mgx-mark::after"]) {
      assert.ok(b.includes(sel), "reduced motion no longer covers " + sel);
    }
    assert.match(b, /animation:\s*none\s*!important/);
  });
});

describe("the animated children this file cannot measure are known ones", () => {
  test("KNOWN_UNSIZED is exactly the set of unmeasurable animated rules", () => {
    const found = animated.filter((a) => a.movesBox && a.box == null)
      .map((a) => a.sel).sort();
    assert.deepEqual(found, [...KNOWN_UNSIZED.keys()].sort(),
      "a mark animation now runs on a box this test cannot compute. Measure its " +
      "document overflow in a browser at hero and slim, then add it to KNOWN_UNSIZED " +
      "with the numbers -- do not delete the entry that fails.");
  });

  test("moondust's canvas overhang is still the documented one", () => {
    // MarkDust.jsx sizes the canvas; the ratio is the audit's single recorded number.
    const dust = readFileSync(
      path.resolve(__dirname, "../../gallery/src/components/MarkDust.jsx"), "utf8");
    const m = dust.match(/const box = Math\.round\(size \* ([\d.]+)\)/);
    assert.ok(m, "MarkDust no longer sizes its canvas as a multiple of the mark");
    const ratio = (parseFloat(m[1]) - 1) / 2;
    assert.equal(ratio.toFixed(2), MOONDUST_OVERHANG_RATIO.toFixed(2),
      "the moondust canvas changed size. It is the one treatment that widens the " +
      "document (measured 30px at hero); re-measure and update the note above.");
  });
});
