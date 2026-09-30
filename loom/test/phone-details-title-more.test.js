import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { detailsHeadline, promptExcerpt } from "../../gallery/src/gen/headline.js";

// THE PHONE RECORD'S TITLE AND ITS MORE CHIP (owner walk 2026-09-29). The title drew doubled
// quotes -- “"I Night elf female, Cobalt blue hair"” -- because the phone wrapped a headline
// that already carries its own; the desktop record renders it bare and was right. And the More
// chip was a bare ⋯, which the phone drew as a lone dash.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");
const phone = src("gallery/src/components/ImageDetailsMobile.jsx");

test("the headline helper already quotes a prompt excerpt, and leaves a typed title as typed", () => {
  assert.equal(promptExcerpt("night elf female, cobalt blue hair"), "“Night elf female, cobalt blue hair”");
  assert.equal(detailsHeadline({ title: "Moonwell at dusk" }), "Moonwell at dusk");
});

test("the phone title renders the headline bare, exactly as the desktop record does", () => {
  assert.match(phone, /<h2 className="idm-title" key=\{"t" \+ row\.media_id\}>\{headline\}<\/h2>/);
  assert.doesNotMatch(phone, /&#8220;\{headline\}&#8221;/);
  assert.doesNotMatch(phone, /“\{headline\}”/);
  assert.match(src("gallery/src/components/DetailsView.jsx"), /<h2 className="p-title">\{headline\}<\/h2>/);
});

test("the More chip says its name beside the design's ⋯, and still opens the More sheet", () => {
  assert.match(phone, /<button type="button" className="idm-chip" aria-haspopup="dialog"\n\s*onClick=\{\(\) => moreSheet\.open\("more"\)\}>⋯ More<\/button>/);
  assert.doesNotMatch(phone, />⋯<\/button>/);
  assert.match(phone, /<MobileSheet open closing=\{moreSheet\.closing\} onClose=\{moreSheet\.close\} title="MORE">/);
});
