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

test("all four PixAI sorts and all 9 category chips are rendered when market is on", () => {
  assert.match(src, /_marketSkeleton\(\)\s*\{/);
  // PixAI's four real sorts, captured 2026-07-26. The old Popular/Newest pair could not express
  // Most Liked or Most Used at all, and Popular routed to a backend that ignored every filter.
  [["trending", "Trending"], ["liked", "Most Liked"], ["used", "Most Used"],
   ["newest", "Latest"]].forEach(([key, label]) => {
    assert.match(src, new RegExp('data-sort="' + key + '">' + label),
      'missing the \"' + label + '\" sort');
  });
  assert.ok(!/data-sort="popular"/.test(src),
    "the old Popular button routed base searches to REST, which ignores market filters");
  // Nine, not six. PixAI's canonical list, confirmed 2026-07-26 from their training page --
  // whose category dropdown is currently rendering raw i18n keys
  // ("market:lora-categories.animal.label"), a bug on their side that handed over the exact
  // set. We were missing `animal` and `realistic`, so those two filters were unreachable.
  ["character", "animal", "style", "realistic", "pose", "clothing", "background",
   "detail", "other"].forEach((cat) => {
    assert.match(src, new RegExp('data-cat="' + cat + '"'),
      "missing the \"" + cat + "\" category chip -- must match PixAI's own nine exactly");
  });
});

test("the source row offers Market / Bookmarked / Mine, and Mine is LoRA-only", () => {
  ["market", "bookmark", "mine"].forEach((v) => {
    assert.match(src, new RegExp('data-src="' + v + '"'),
      'missing the "' + v + '" source button');
  });
  // You author LoRAs, not base models -- and PixAI's own base-model picker has no equivalent
  // tab either, so the button must be gated on kind rather than rendered unconditionally.
  assert.match(src, /this\._kind === 'lora'[\s\S]{0,120}data-src="mine"/,
    "the Mine button must be gated on kind === 'lora'");
});

test("base models get Model Type chips, LoRAs get categories -- not the same control", () => {
  // PixAI gives base models a different filter set: Model Type, Posted at, License. No LoRA
  // category, no Source, no My-LoRA tab. Rendering one shared row would half-apply.
  assert.match(src, /this\._kind === .lora./,
    "the category-vs-architecture choice must branch on kind");
  assert.match(src, /mg-mkttypes/, "base models need their own architecture chip row");

  // Every token measured off a live request 2026-07-26. A wrong enum here does not error -- it
  // returns the wrong rows, or none, and reads as an empty result, so none of these may drift.
  [["MMDIT26B_MODEL", "DiT.3"], ["MMDIT26A_MODEL", "DiT.2"], ["DIT7_MODEL", "DiT.1"],
   ["USER_DIT26A_MODEL", "Community DiT"], ["SDXL_MODEL", "SDXL"],
   ["SD_V1_MODEL", "SD 1.5"]].forEach(([token, label]) => {
    assert.match(src, new RegExp('data-mt="' + token + '">' + label.replace(".", "\.")),
      label + ' must map to ' + token + ' (measured, not inferred)');
  });

  // Community DiT is USER_DIT26A_MODEL, NOT DIT9_MODEL. Both were plausible and the wrong one
  // fails silently, which is why it was captured rather than guessed.
  assert.ok(!/data-mt="DIT9_MODEL"/.test(src),
    "DIT9_MODEL is not what Community DiT sends");
});

test("Model Type is multi-select, and All means clear", () => {
  // Measured: successive clicks sent [USER_DIT26A_MODEL], then [.., SDXL_MODEL], then
  // [.., SD_V1_MODEL]. A single-value control would have been quietly wrong.
  assert.match(src, /this\._modelTypes = \[\]/, "must start as an array");
  assert.match(src, /self\._modelTypes\.splice\(at, 1\)/, "clicking a chosen chip must REMOVE it");
  assert.match(src, /self\._modelTypes\.push\(v\)/, "clicking a new chip must ADD it");
  assert.match(src, /if \(!v\) \{[\s\S]{0,120}self\._modelTypes = \[\]/,
    "the All chip must clear the set rather than select a token");
  // Sent as a REPEATED param, matching the server reading request.args.getlist.
  assert.match(src, /model_type=. \+ encodeURIComponent\(t\)/);
});

test("filters are hidden on the bookmark list, where the server cannot honour them", () => {
  // The bookmark connection accepts a keyword and the architecture filter and nothing else.
  // Leaving sort/category/dropdowns on screen there would be controls that silently do
  // nothing -- the specific failure mode that made the Enhance cards waste months.
  assert.match(src, /_syncFilterVisibility\(\)\s*\{/);
  assert.match(src, /this\._src === 'bookmark' \? 'none' : ''/,
    "bookmark must hide the filter block");
  assert.match(src, /if \(this\._src !== 'bookmark'\) \{/,
    "and must not SEND those params either -- a hidden control can still hold a stale value");
});

test("every market param is sent ONLY when market is on", () => {
  // This used to pin the URL builder's exact source line, which broke the moment round 3 added
  // three more filters -- while the thing it actually cares about was never in danger. It now
  // asserts the INTENT: a non-market mount (the Loom's base-model picker, or its existing LoRA
  // mount) must never send any market param. The server treats an unexpected category as
  // "ignored", so this would fail quietly rather than loudly, which is why it is pinned at all.
  const fn = src.match(/_searchUrl\(cursor\)\s*\{[\s\S]*?\n    \}/);
  assert.ok(fn, "could not find _searchUrl to inspect");
  const body = fn[0];

  const gate = body.indexOf("if (this._market) {");
  assert.ok(gate > 0, "_searchUrl must gate market params behind this._market");

  // Everything from the gate to the end of its block.
  let depth = 0, end = -1;
  for (let i = body.indexOf("{", gate); i < body.length; i++) {
    if (body[i] === "{") depth++;
    else if (body[i] === "}") { depth--; if (depth === 0) { end = i; break; } }
  }
  assert.ok(end > gate, "could not find the end of the market block");
  const inside = body.slice(gate, end);
  const outside = body.slice(0, gate) + body.slice(end);

  ["&src=", "&sort=", "&category=", "&posted=", "&source=", "&license="].forEach((param) => {
    assert.ok(inside.includes(param), 'market param ' + param + ' must be inside the gate');
    assert.ok(!outside.includes(param),
      'market param ' + param + ' LEAKED outside the market gate -- every mount would send it');
  });
});

test("clicking a sort/category button updates state and re-searches, not just toggles a class", () => {
  assert.match(src, /self\._sort = s;[\s\S]{0,220}self\._search\(\);/);
  assert.match(src, /self\._category = c;[\s\S]{0,220}self\._search\(\);/);
});

test("changing source or a filter dropdown also re-searches", () => {
  // A control that repaints itself but does not refetch is the worst kind of broken: it looks
  // like it worked.
  assert.match(src, /self\._src = v;[\s\S]{0,400}self\._search\(\);/,
    "switching source must re-search");
  assert.match(src, /self\._posted = sel\.value/);
  assert.match(src, /self\._source = sel\.value/);
  assert.match(src, /self\._license = sel\.value/);
  assert.match(src, /sel\.classList\.toggle\('on', !!sel\.value\);[\s\S]{0,80}self\._search\(\);/,
    "a dropdown change must re-search, not only restyle itself");
});
