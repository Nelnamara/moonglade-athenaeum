import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { LANDSCAPE_QUERY } from "../../gallery/src/lib/phoneCore.js";

/* The owner's walk, 2026-10-03: the phone Lightbox's row of buttons scrolled sideways with its
   scrollbar drawn across them, and looked cramped. Upright it wraps onto lines (even gaps, centred, the
   row's own 12 px in from each edge) and every button is at least 44 px tall; sideways it is the rail's
   column, untouched. The render harness measures it at 320, 390 and 430 px
   (test_the_phone_lightbox_buttons_wrap_onto_lines_with_room_to_tap). */

const here = path.dirname(fileURLToPath(import.meta.url));
const css = readFileSync(path.join(here, "..", "..", "gallery", "src", "styles", "lightbox-mobile.css"), "utf8")
  .split("\r\n").join("\n");

test("upright, the row wraps and every button is a 44 px target", () => {
  const block = "@media not all and " + LANDSCAPE_QUERY + " {\n"
    + "  .lbm-actsrow { flex-wrap: wrap; justify-content: center; gap: 8px; overflow: visible; }\n"
    + "  .lbm-actsrow > * { min-height: 44px; }\n}";
  assert.ok(css.includes(block), "lightbox-mobile.css carries the upright wrap block");
});
