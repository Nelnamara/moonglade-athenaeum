import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE RESTART CARD VERDICT (owner, 2026-09-07).

   The small workshop off the Restart Card Board closed the question control-panel.css had
   been carrying open since the 2026-09-05 "the mascot does not spin" ruling: what, if
   anything, takes the spin's place. The answer is PULSE + EMBER on one beat, plus a set of
   dials. Record: moonglade-internal/scopes/WORKSHOP_2026-09-07_restart-card-verdict.md.

   tests/test_render_harness.py::test_the_restart_mascot_holds_still_and_the_halo_keeps_
   pulsing reads the pair off a real browser's computed style. This is the cheap guard for
   the NUMBERS, which no browser test asserts: a stylesheet edit that quietly walks the
   period, the reach or the colour back would otherwise be silent. Same readFileSync-over-
   the-stylesheet idiom as blur-pref.test.js. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite: the repo stores LF
// (.gitattributes `* text=auto`) while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const css = src("styles/control-panel.css");
// The comment blocks in this file NAME the removed selectors on purpose, so any "is it
// gone?" check has to read the rules only.
const rules = css.replace(/\/\*[\s\S]*?\*\//g, "");

/** One declaration block, by its selector, from `{` to the first `}`. */
function ruleFor(selector) {
  const i = css.indexOf(selector + " {");
  assert.ok(i >= 0, "no rule for: " + selector);
  return css.slice(i, css.indexOf("}", i) + 1);
}

describe("the halo carries both animations on one beat", () => {
  const busy = ruleFor(".mgcp-pwr-halo.busy");

  test("pulse and ember are both there", () => {
    assert.match(busy, /cpPulse/);
    assert.match(busy, /cpEmber/, "the ember the owner asked for ALONG WITH the pulse");
  });

  test("both run at 1.8s -- one beat, not two", () => {
    const periods = busy.match(/cp(?:Pulse|Ember) ([\d.]+m?s)/g) || [];
    assert.equal(periods.length, 2, "expected exactly two animations: " + busy);
    for (const p of periods) assert.match(p, /1\.8s$/, p);
    assert.doesNotMatch(busy, /2\.2s/, "2.2s was the old period");
  });

  test("both ease-in-out and both infinite", () => {
    assert.equal((busy.match(/ease-in-out/g) || []).length, 2);
    assert.equal((busy.match(/infinite/g) || []).length, 2);
  });
});

describe("the dials the owner set", () => {
  test("cpPulse rings cyan, not emerald", () => {
    const kf = css.slice(css.indexOf("@keyframes cpPulse"));
    const body = kf.slice(0, kf.indexOf("\n@") >= 0 ? kf.indexOf("\n@") : kf.length);
    assert.match(body, /rgba\(71,203,195,\.5\)/, "the Loom cyan --loomc");
    assert.doesNotMatch(body, /79,201,154/, "emerald was the pre-verdict colour");
  });

  test("the ring reaches 12px", () => {
    const kf = css.slice(css.indexOf("@keyframes cpPulse"));
    assert.match(kf.slice(0, 400), /box-shadow: 0 0 0 12px rgba\(71,203,195,0\)/);
  });

  test("cpEmber brightens and swells at the midpoint, and settles at both ends", () => {
    const i = css.indexOf("@keyframes cpEmber");
    assert.ok(i >= 0, "cpEmber is not defined");
    const kf = css.slice(i, css.indexOf("\n}", i) + 2);
    assert.match(kf, /0%, 100% \{ opacity: \.55; transform: scale\(1\); filter: brightness\(1\); \}/);
    assert.match(kf, /50% \{ opacity: 1; transform: scale\(1\.07\); filter: brightness\(1\.25\); \}/);
  });

  test("the mascot is 128px and the halo sits 18px beyond it", () => {
    assert.match(ruleFor(".mgcp-pwr-mascotwrap"), /width: 128px; height: 128px/);
    assert.match(ruleFor(".mgcp-pwr-halo"), /inset: -18px/);
  });

  test("128 + 2x18 of halo still fits the card on a 360px phone", () => {
    // .mgcp-pwr-card is width: min(420px, calc(100vw - 48px)), box-sizing: border-box,
    // padding 28px 26px 22px. The narrowest real phone the app supports is 360px.
    const card = ruleFor(".mgcp-pwr-card");
    assert.match(card, /width: min\(420px, calc\(100vw - 48px\)\)/);
    assert.match(card, /box-sizing: border-box/);
    assert.match(card, /padding: 28px 26px 22px/);
    const inner = Math.min(420, 360 - 48) - 26 * 2;   // 312 - 52 = 260
    assert.ok(inner >= 128 + 18 * 2, `${inner}px of card for 164px of halo`);
  });
});

describe("what the verdict did NOT change", () => {
  test("the mascot still has no animation of its own", () => {
    assert.doesNotMatch(rules, /\.mgcp-pwr-mascot\.spin/,
      "the 2026-09-05 no-spin ruling stands; the ember is on the HALO");
  });

  test("reduced motion still silences the busy halo", () => {
    const rm = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    assert.match(rm.slice(0, 600), /\.mgcp-pwr-halo\.busy/,
      "one selector covers both animations -- animation: none kills the shorthand whole");
  });

  test("the comment block records the verdict and points at its record", () => {
    assert.match(css, /2026-09-07/);
    assert.match(css, /WORKSHOP_2026-09-07_restart-card-verdict\.md/);
    assert.doesNotMatch(css, /deliberately unanswered here/,
      "the open question is closed; the sentence saying otherwise must go");
  });
});
