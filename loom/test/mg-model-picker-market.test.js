import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// O12/O13 (Phase 2): the gallery's own #model-flyout has a Popular/Newest sort toggle + 6
// category chips for LoRA browsing that <mg-model-picker> never had (O12: "sort/category
// are not a real gap... the component mounts base-only" -- true only until the gallery
// actually adopts it for LoRAs too, which is exactly what O13's migration does). The
// server (/api/model-search) already honors sort=/category= -- only the client UI/wiring
// was missing. Opt-in via `market`, OFF by default: zero regression risk to the Loom's
// existing kind="lora" multi mount, which does not set it.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../static/mg-model-picker.js"), "utf8");

test("market is an opt-in attribute, read once at connect", () => {
  assert.match(src, /this\._market = this\.hasAttribute\('market'\)/,
    "market must be opt-in, or every existing mount (the Loom's kind=\"lora\" multi) " +
    "would silently grow a sort/category UI it never asked for");
});

test("the sort toggle and all 6 gallery category chips are rendered when market is on", () => {
  assert.match(src, /_marketSkeleton\(\)\s*\{/);
  assert.match(src, /data-sort="popular"/);
  assert.match(src, /data-sort="newest"/);
  ["character", "style", "pose", "clothing", "background", "detail"].forEach((cat) => {
    assert.match(src, new RegExp('data-cat="' + cat + '"'),
      "missing the \"" + cat + "\" category chip -- must match the gallery's own #mkt-cats list exactly");
  });
});

test("sort and category are threaded into the /api/model-search query only when market is on", () => {
  assert.match(src,
    /if \(this\._market\) \{\s*\n\s*u \+= '&sort=' \+ encodeURIComponent\(this\._sort\) \+ '&category=' \+ encodeURIComponent\(this\._category\);/,
    "a non-market mount (e.g. the Loom's base-model picker, or its existing LoRA mount) " +
    "must never send sort=/category= -- the server treats an unexpected category as " +
    "'ignored', but this must be a deliberate, gated addition, not accidental for every mount");
});

test("clicking a sort/category button updates state and re-searches, not just toggles a class", () => {
  assert.match(src, /self\._sort = s;[\s\S]{0,220}self\._search\(\);/);
  assert.match(src, /self\._category = c;[\s\S]{0,220}self\._search\(\);/);
});
