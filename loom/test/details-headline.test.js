// gen/headline.js -- the Image Details headline per Image Details.dc.html.
//
// The DC is the oracle: its three sample records carry a `full` prompt AND the headline the
// design shows for it. If the excerpt rule reproduces the DC's own headlines from the DC's
// own prompts, it is the design; if not, it is a guess. "Where the Refit Broke" (19 Aug
// 2026): the build shipped `title || filename` here, clipping a 1669px filename into a
// 718px slot, mid-word, on 99.95% of the library.
import { test } from "node:test";
import assert from "node:assert/strict";
import { promptExcerpt, detailsHeadline } from "../../gallery/src/gen/headline.js";

// Verbatim from design_handoff/design_handoff_moonglade_suite/Image Details.dc.html
const DC = [
  { full: "1girl, sitting on floor, white slime on face, looking at viewer, night elf, long elven ears, lavender skin, cobalt hair, glowing eyes, artist:nelnamara-archdruid, masterpiece, fantasy, detailed background",
    headline: "“Night elf, long elven ears, lavender skin”" },
  { full: "moonwell reflections, wide establishing shot, volumetric light through cedar boughs, masterpiece",
    headline: "“Moonwell reflections, wide establishing shot”" },
];

test("the DC's second record: excerpt == the DC headline exactly", () => {
  assert.equal(promptExcerpt(DC[1].full), DC[1].headline);
});

test("the DC's first record: scaffold (1girl / looking at viewer) is skipped; the excerpt lands on the descriptive clauses", () => {
  const ex = promptExcerpt(DC[0].full);
  // The DC's own headline skips the opening "1girl, sitting on floor, white slime on face,
  // looking at viewer" and starts at the character description. The exact clause set the
  // designer chose is a judgment; what the rule must guarantee is: no scaffold, no artist
  // tag, starts descriptive, ~40 chars, quoted, capitalised.
  assert.match(ex, /^“[A-Z]/);
  assert.match(ex, /”$/);
  assert.doesNotMatch(ex, /1girl|looking at viewer|masterpiece|artist:/i);
  assert.ok(ex.length <= 60, ex);
});

test("a typed title always wins, verbatim", () => {
  assert.equal(detailsHeadline({ title: " Moonwell at dusk ", prompt_full: "x, y" }), "Moonwell at dusk");
});

test("the filename is NEVER the headline", () => {
  const row = { title: "", prompt_full: "", natural_prompt: "", prompt_preview: "",
    filename: "images/character_nelnamara_thedreamwalker_druid_An_extreme_low_angl_2048_757.webp" };
  assert.equal(detailsHeadline(row), "Untitled");
  const row2 = { ...row, prompt_full: "masterpiece, best quality, 1girl" };   // ONLY scaffold
  assert.equal(detailsHeadline(row2), "Untitled");
});

test("falls through prompt_full -> natural_prompt -> prompt_preview", () => {
  assert.equal(detailsHeadline({ natural_prompt: "A wide shot of a moonwell" }), "“A wide shot of a moonwell”");
  assert.equal(detailsHeadline({ prompt_preview: "ink study of a druid, high contrast" }), "“Ink study of a druid, high contrast”");
});

test("weight syntax and lora tokens are stripped, never printed", () => {
  const ex = promptExcerpt("(night elf:1.3), <lora:nelnamara:0.8>, lavender skin, cobalt hair");
  assert.doesNotMatch(ex, /[<>]|:\d/);
  assert.match(ex, /^“Night elf, lavender skin/);
});
