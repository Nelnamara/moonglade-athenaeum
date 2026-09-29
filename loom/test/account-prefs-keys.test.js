import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { prefKeyProblem } from "../../gallery/src/hooks/accountPrefsStore.js";
import { GEN_PREFS_KEY } from "../../gallery/src/gen/genPrefs.js";
import { MINE_KEY } from "../../gallery/src/gen/colorPaletteCore.js";
import { DRAFT_PREFIX, draftId } from "../../gallery/src/recipes/recipesCore.js";
import { GUIDE_SURFACES, NOTES_HIDDEN_KEY, guideKey } from "../../gallery/src/help/guideCore.js";
import { SEEN_KEY as FOLIO_SEEN_KEY } from "../../gallery/src/folio/maskedFeatsCore.js";

/* The account store (/api/account/prefs, one document per account) is shared by three lanes
   that never saw each other: wave 2's dock settings (gen.image), palettes (palette.mine) and
   recipe drafts (recipes.draft.<id>, recipes.picker-size), and wave 3's Help -- the guide's
   per-surface state (guide.<surface>), its notes switch (guide.notes_hidden) and the version
   what's new last showed (seen.whatsnew), and wave 4's Folio -- the record of which earned feats
   the account has been shown (folio.seen). Each lane owns its own first segment, so no key of
   one can be a key of another, and every key passes the store's own rule. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8");

const literal = (rel, name) => {
  const m = src(rel).match(new RegExp("const " + name + ' = "([^"]+)"'));
  assert.ok(m, name + " not found in " + rel);
  return m[1];
};
const SEEN_KEY = literal("help/whatsNew.js", "SEEN_KEY");
const PICKER_SIZE = (src("recipes/RecipesOverlay.jsx").match(/prefs\.get\("(recipes\.[a-z.-]+)"/) || [])[1];

const OWNERS = {
  "wave 2 dock": [GEN_PREFS_KEY],
  "wave 2 palette": [MINE_KEY],
  "wave 2 recipes": [DRAFT_PREFIX + draftId(1759000000000, "abc123"), PICKER_SIZE],
  "wave 3 help": GUIDE_SURFACES.map(guideKey).concat([NOTES_HIDDEN_KEY, SEEN_KEY]),
  "wave 4 folio": [FOLIO_SEEN_KEY],
};

describe("the shared account store's keys", () => {
  test("every key is one the store accepts", () => {
    for (const [owner, keys] of Object.entries(OWNERS)) {
      for (const k of keys) assert.equal(prefKeyProblem(k), "", owner + ": " + k);
    }
  });

  test("each lane writes under its own first segment and no two lanes share one", () => {
    const seg = (k) => k.split(".")[0];
    const byOwner = Object.fromEntries(Object.entries(OWNERS).map(([o, ks]) => [o, new Set(ks.map(seg))]));
    const owners = Object.keys(byOwner);
    for (let i = 0; i < owners.length; i++) {
      for (let j = i + 1; j < owners.length; j++) {
        const shared = [...byOwner[owners[i]]].filter((s) => byOwner[owners[j]].has(s));
        assert.deepEqual(shared, [], owners[i] + " and " + owners[j] + " share a namespace");
      }
    }
  });

  test("no guide surface can be named like the notes switch", () => {
    assert.ok(!GUIDE_SURFACES.map(guideKey).includes(NOTES_HIDDEN_KEY));
    assert.equal(new Set(GUIDE_SURFACES).size, GUIDE_SURFACES.length);
  });
});
