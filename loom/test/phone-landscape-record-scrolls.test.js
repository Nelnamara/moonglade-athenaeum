import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The owner's walk, 2026-10-03: sideways, a picture's record pinned its action group (Remix / Send to
   Video, Edit prompt, Filter by model, View batch, Suggest prompt) to the side panel's foot; on a short
   screen that took about half the height, and the fields scrolled in a small window and slid up under
   it. Sideways the panel scrolls as one now; upright the foot is pinned as before. The render harness
   measures both (test_landscape_record_is_a_picture_beside_a_380px_panel_that_scrolls_as_one). */

const here = path.dirname(fileURLToPath(import.meta.url));
const css = (f) => readFileSync(path.join(here, "..", "..", "gallery", "src", "styles", f), "utf8").split("\r\n").join("\n");

test("sideways, the record's action group is in the flow", () => {
  assert.match(css("phone-landscape.css"), /\.idm-rec \.idm-recrow \{ position: static; margin: 0 -14px; \}/);
});

test("upright, the foot is still pinned", () => {
  assert.match(css("image-details-mobile.css"), /\.idm-recrow \{[^}]*position: sticky;/);
});
