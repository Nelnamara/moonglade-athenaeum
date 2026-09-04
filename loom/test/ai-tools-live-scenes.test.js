import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  CURATION, FALLBACK_SCENES, mergeScenes, sceneRows, shapeTally,
} from "../../gallery/src/gen/sceneCatalog.js";

/* ISSUE #36 -- the AI-Tools grid was a hardcoded 28-entry array, so daily-fortune,
   daily-setlog and mini-mart-ad (live on PixAI) had no tile and were unreachable. The grid now
   comes from GET /api/scenes. What these pin is the pair of guarantees that change makes:
   a new scene gets a real tile with no code change, and a FAILED fetch still renders the
   curated 28 rather than an empty modal. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Live rows as /api/scenes serves them (server-normalized listChatEditingScenes).
const LIVE = [
  { sceneId: "plushie", shape: "click", label: "Plushie", detail: "", tier: null,
    thumb: "/api/pixai-cdn/thumb?u=a" },
  { sceneId: "character-style-generator", shape: "lang", label: "Character Style Generator",
    detail: "EN / JP / KR / TC", tier: 1, thumb: "/api/pixai-cdn/thumb?u=b" },
  { sceneId: "daily-fortune", shape: "lang", label: "Daily Fortune", detail: "EN / JP / KR / TC",
    tier: 1, thumb: "/api/pixai-cdn/thumb?u=c" },
  { sceneId: "daily-setlog", shape: "select", label: "Daily Setlog", detail: "4 options",
    tier: 1, thumb: "" },
];

test("a live scene we carry no curated row for still gets a full tile", () => {
  const rows = mergeScenes(LIVE);
  const fortune = rows.find((r) => r.slug === "daily-fortune");
  assert.ok(fortune, "daily-fortune must have a tile -- this is the bug");
  assert.equal(fortune.name, "Daily Fortune");
  assert.equal(fortune.shape, "lang");
  assert.equal(fortune.detail, "EN / JP / KR / TC");
  assert.equal(fortune.tier, true);
  assert.equal(fortune.thumb, "/api/pixai-cdn/thumb?u=c",
    "with no local webp the tile falls back to the catalog's own thumbnail");
});

test("curated copy is overlaid on the live rows, so no shipped tile's wording changes", () => {
  const rows = mergeScenes(LIVE);
  const style = rows.find((r) => r.slug === "character-style-generator");
  assert.equal(style.name, "Character Style", "the shipped name, not the derived slug label");
  assert.equal(style.detail, "EN / JP / KR / TC");
});

test("the live membership tier wins, so a re-gated scene re-badges itself", () => {
  const rows = mergeScenes([{ sceneId: "plushie", tier: 1 }]);
  assert.equal(rows[0].tier, true);
  assert.equal(FALLBACK_SCENES.find((r) => r.slug === "plushie").tier, false);
});

test("tiles sort alphabetically by display name, the order the grid shipped in", () => {
  const names = mergeScenes(LIVE).map((r) => r.name);
  assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b, "en")));
});

test("a failed fetch falls back to the curated 28 -- the modal is never empty", () => {
  // api.js never throws: a refusal, an outage or an unarmed mirror all reach the modal as
  // [] (or null, before the first answer). Either way the grid must still render.
  assert.equal(sceneRows([]).length, CURATION.length);
  assert.equal(sceneRows(null).length, CURATION.length);
  assert.equal(sceneRows(undefined).length, CURATION.length);
  assert.deepEqual(sceneRows([]), FALLBACK_SCENES);
  assert.ok(FALLBACK_SCENES.every((r) => r.name && r.slug && r.shape));
});

test("a live catalog replaces the fallback rather than merging with it", () => {
  const rows = sceneRows(LIVE);
  assert.equal(rows.length, LIVE.length);
  assert.ok(!rows.some((r) => r.slug === "lego"), "a retired scene must disappear too");
});

test("rows with no sceneId are dropped", () => {
  assert.equal(mergeScenes([{ label: "junk" }, null, { sceneId: "lego" }]).length, 1);
});

test("the footer tally is computed, not written down", () => {
  // It shipped as the literal "11 one-click · 8 select · 5 text · 3 language · 1 dual",
  // which went stale the moment PixAI added a scene -- the same bug as the grid.
  assert.equal(shapeTally(FALLBACK_SCENES),
    "11 one-click · 8 select · 5 text · 3 language · 1 dual");
  assert.equal(shapeTally(mergeScenes(LIVE)), "1 one-click · 1 select · 2 language");
  assert.equal(shapeTally([]), "");
});

test("AiToolsModal reads the live catalog and holds no grid array of its own", () => {
  const src = readFileSync(
    path.join(__dirname, "../../gallery/src/components/AiToolsModal.jsx"), "utf8");
  assert.match(src, /apiGet\("\/api\/scenes"\)/,
    "the grid must ask the server what exists");
  assert.match(src, /sceneRows\(live\)/);
  assert.doesNotMatch(src, /^const SCENES = \[/m,
    "the hardcoded 28-tile array is the bug -- it lives in sceneCatalog.js as the fallback");
  assert.doesNotMatch(src, /"All " \+ SCENES\.length/,
    "the tier tab's count must come from the rendered rows");
});
