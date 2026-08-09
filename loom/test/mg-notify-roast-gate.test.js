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
//
// Port note 2026-08-08 (no-vanilla campaign): static/mg-notify.js is gone. Of the three vanilla
// surfaces this file pinned, only the unlock celebration survived the port -- it lives in
// gallery/src/notify/ach.js, where _mkMoment builds the toast for BOTH real unlocks and the
// Folio's replay, so ONE line pick is now the only place the engine chooses between the roast
// and its uncensored twin. The Folio-card and carousel assertions are retired below, not moved.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/notify/ach.js"), "utf8");

test("the celebration's roast pick consults the unleash toggle", () => {
  // Ported 2026-08-08 from "three surfaces print a roast, and all three consult the unleash
  // toggle" -- the >= 3 count is meaningless against one file, so the sharper form is: the one
  // surviving pick is gated, and NO roast_nsfw read exists outside it.
  assert.match(src,
    /\(unleashed\(\)\s*&&\s*a\.roast_nsfw\)\s*\?\s*a\.roast_nsfw\s*:\s*\(a\.roast\s*\|\|\s*a\.desc/,
    "the celebration line must select roast_nsfw only when unleashed(), falling back tame " +
    "(roast, then desc). A pick that skips the gate fails silently -- wrong line, forever, " +
    "and nobody notices until someone toggles and watches closely.");
  const ungated = (src
    .replace(/\(unleashed\(\)\s*&&\s*a\.roast_nsfw\)\s*\?\s*a\.roast_nsfw/g, "")
    .match(/roast_nsfw/g) || []).length;
  assert.equal(ungated, 0,
    "found " + ungated + " roast_nsfw read(s) outside the unleashed() pick -- a second, " +
    "ungated selection is exactly the surface-by-surface drift the owner caught in 2026-07.");
});

// RETIRED 2026-08-08 (no-vanilla campaign) -- two tests deleted, not ported:
//
//   "the carousel is earned-gated, so an unearned tier is not spoiled"
//   "the carousel reuses the Folio card's roast style rather than copying it"
//
// Both pinned the vanilla #ach-modal Trophy Hall machinery (renderCarousel and the
// .hall-card/.hall-carousel CSS). That machinery was deliberately DROPPED in the port, not
// rewritten: no served page carries the #ach-modal skeleton -- the React Folio of Honors
// (gallery/src/components/FolioOverlay.jsx + gallery/src/hooks/useFolio.js) replaced it -- so
// every carousel path was guarded dead code on both hosts. The intents behind them still stand
// (never spoil an unearned tier's roast; one roast style, not two copies drifting apart) but
// they now belong to the Folio's own tests on the gallery side, not to a loom file grepping a
// script that no longer exists.
