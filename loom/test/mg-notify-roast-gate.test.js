import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Owner report 2026-07-26: "the only place it does not change is in the carousel viewed cards."
//
// He was right, and the cause was NOT that the carousel ignored the toggle. It never rendered a
// roast at all -- it printed tier.desc and stopped -- so there was nothing gated to swap. Every
// other surface read the toggle and changed, which is precisely what made it look like a
// carousel-specific bug rather than a missing feature.
//
// The failure mode is silent by nature: a new surface that prints a roast without the gate simply
// shows the tame line forever, and nobody notices until someone toggles and watches closely.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-notify.js"), "utf8");

test("three surfaces print a roast, and all three consult the unleash toggle", () => {
  // The Folio card, the carousel, and the unlock toast.
  const gated = src.match(/unleashed\(\)\s*&&\s*[A-Za-z_]+\.roast_nsfw/g) || [];
  assert.ok(gated.length >= 3,
    "expected at least three gated surfaces (Folio card, carousel, unlock toast); found " +
    gated.length + ". A surface that selects roast_nsfw without unleashed() shows the tame " +
    "line forever and fails silently.");
});

test("the carousel is earned-gated, so an unearned tier is not spoiled", () => {
  assert.match(src, /if\(!tier\.earned\) return/,
    "the carousel must not print a roast for a tier the owner has not earned -- the roast is " +
    "the reward for getting there");
  assert.match(src, /hot\?tier\.roast_nsfw:tier\.roast/,
    "the carousel must swap to the uncensored line when the toggle is on");
});

test("the carousel reuses the Folio card's roast style rather than copying it", () => {
  // Two copies of a style is how the board grew its "written twice and already drifted apart"
  // entries. One selector, one place to change.
  assert.match(src, /\.hall-card \.hcd-roast,\.hall-carousel \.hcd-roast\{/,
    "the shared class must cover both surfaces");
  assert.ok(!/\.hc-roast\{/.test(src),
    "a carousel-specific roast rule would be a second copy to keep in sync");
});
