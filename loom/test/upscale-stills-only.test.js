import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// UPSCALE IS OFFERED ON STILLS ONLY (owner walk 2026-09-29). A video's details page showed
// ⇱ Upscale, and the panel it opened could only answer "Upscaling applies to images, not
// videos". Every surface that offers it now asks first whether the item is a video. The phone
// Lightbox's own row is guarded with its order in phone-lightbox-chip-order.test.js.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

test("the desktop record: the file-actions Upscale renders only when the row is not a video", () => {
  const d = src("gallery/src/components/DetailsView.jsx");
  assert.match(d, /\{row\.is_video !== "1" \? \(\n\s*<button className="btn" title="Upscale or Hires"\n\s*onClick=\{\(\) => upEl\.current && upEl\.current\.open\(row\.media_id\)\}>⇱ Upscale<\/button>\n\s*\) : null\}/);
  assert.equal((d.match(/⇱ Upscale<\/button>/g) || []).length, 1, "one Upscale chip on the record");
});

test("the desktop Lightbox: the chip renders only for a still (grid cards carry is_video truthy)", () => {
  const l = src("gallery/src/components/Lightbox.jsx");
  assert.match(l, /\{!it\.is_video \? \(\n\s*<button className="lbx-chip" title="Upscale or Hires this picture"\n\s*onClick=\{\(\) => upEl\.current && upEl\.current\.open\(it\.media_id\)\}>⇱ Upscale<\/button>\n\s*\) : null\}/);
  // the same truthiness the stage itself uses to decide <video> vs <img>
  assert.match(l, /\{it\.is_video \? \(\n\s*<video key=\{it\.media_id\}/);
});

test("the phone record: the chip renders only when the row is not a video", () => {
  const m = src("gallery/src/components/ImageDetailsMobile.jsx");
  assert.match(m, /\{row\.is_video !== "1" \? \(\n\s*<button type="button" className=\{"idm-chip" \+ \(upscaleOpen \? " on" : ""\)\} onClick=\{toggleUpscale\}>⇱ Upscale<\/button>\n\s*\) : null\}/);
  assert.equal((m.match(/onClick=\{toggleUpscale\}>⇱ Upscale<\/button>/g) || []).length, 1);
});
