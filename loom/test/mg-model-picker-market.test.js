import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// O12/O13 (Phase 2): the gallery's own #model-flyout has a Popular/Newest sort toggle + 6
// category chips for LoRA browsing that the picker never had (O12: "sort/category are not
// a real gap... the component mounts base-only" -- true only until the gallery actually
// adopts it for LoRAs too, which is exactly what O13's migration does). The server
// (/api/model-search) already honors sort=/category= -- only the client UI/wiring was
// missing. Opt-in via `market`, OFF by default: zero regression risk to the Loom's existing
// kind="lora" multi mount, which does not set it.
//
// PORTED 2026-08-08 (static/ -> React): the <mg-model-picker> custom element was reimplemented
// as gallery/src/components/ModelPicker.jsx. The market chrome ported near-verbatim, so these
// assertions now target the React source. The vanilla->React contract changes exercised here:
//   - `market`/`kind` observed ATTRIBUTES  -> PROPS (`market = false` default = opt-in).
//   - `_marketSkeleton()` string builder    -> the `{market && (...)}` JSX block, with the
//     sort/category/model-type option lists lifted to the SORTS / LORA_CATS / BASE_TYPES
//     module constants and rendered via `.map(([v,label]) => <button data-... ={v}>)`.
//   - internal `this._sort`/`this._category`/... state + `self._search()` re-fetch -> useState
//     setters (setSort/setCategory/...) feeding `searchUrl` (a useCallback), with the re-search
//     driven by the effect that re-runs `doSearch` whenever `searchUrl` changes. Clicking a
//     chip that only re-styled without refetching is still the failure guarded against; in React
//     the "on" class is DERIVED from state and the refetch is the effect, so both are asserted.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/ModelPicker.jsx"), "utf8");

test("market is an opt-in prop, off by default, and gates the whole chrome", () => {
  // The custom element read `this._market = this.hasAttribute('market')` once at connect; the
  // React port takes it as a prop DEFAULTING TO FALSE, so every existing mount (the Loom's
  // kind="lora" multi) that does not pass it grows no sort/category UI it never asked for.
  assert.match(src, /market = false,/,
    "market must default to false, or every existing mount would silently grow a sort/category UI");
  // ...and the entire market region renders only behind that gate (the JSX equivalent of the
  // element only calling _marketSkeleton() when this._market was set).
  assert.match(src, /\{market && \(/,
    "the market chrome must be gated on the market prop");
});

test("all four PixAI sorts and all 9 category chips are rendered when market is on", () => {
  // The option lists moved out of _marketSkeleton()'s string into module constants that the
  // JSX maps over with data-sort={v} / data-cat={v}. Assert the render idiom exists...
  assert.match(src, /data-sort=\{v\}/, "sorts must render from the SORTS list");
  assert.match(src, /data-cat=\{v\}/, "categories must render from the LORA_CATS list");
  // ...and pin the tuples themselves, since a wrong enum here returns the wrong rows silently.
  // PixAI's four real sorts, captured 2026-07-26. The old Popular/Newest pair could not express
  // Most Liked or Most Used at all, and Popular routed to a backend that ignored every filter.
  [["trending", "Trending"], ["liked", "Most Liked"], ["used", "Most Used"],
   ["newest", "Latest"]].forEach(([key, label]) => {
    assert.match(src, new RegExp('\\["' + key + '", "' + label + '"\\]'),
      'missing the "' + label + '" sort');
  });
  assert.ok(!/"popular"/.test(src),
    "the old Popular button routed base searches to REST, which ignores market filters");
  // Nine, not six. PixAI's canonical list, confirmed 2026-07-26 from their training page --
  // whose category dropdown is currently rendering raw i18n keys
  // ("market:lora-categories.animal.label"), a bug on their side that handed over the exact
  // set. We were missing `animal` and `realistic`, so those two filters were unreachable.
  [["character", "Character"], ["animal", "Animal"], ["style", "Style"],
   ["realistic", "Realistic"], ["pose", "Pose"], ["clothing", "Clothing"],
   ["background", "Background"], ["detail", "Detail"], ["other", "Other"]].forEach(([cat, label]) => {
    assert.match(src, new RegExp('\\["' + cat + '", "' + label + '"\\]'),
      'missing the "' + cat + '" category chip -- must match PixAI\'s own nine exactly');
  });
});

test("the source row offers Market / Bookmarked / Mine, and Mine is LoRA-only", () => {
  // Rendered via data-src={v} over a tuple list; assert the render idiom + each token.
  assert.match(src, /data-src=\{v\}/, "the source row must render its buttons from a list");
  ["market", "bookmark", "mine"].forEach((v) => {
    assert.match(src, new RegExp('"' + v + '"'),
      'missing the "' + v + '" source button');
  });
  // You author LoRAs, not base models -- and PixAI's own base-model picker has no equivalent
  // tab either, so the Mine button is spread in only when kind === "lora", not rendered
  // unconditionally (was `this._kind === 'lora' ... data-src="mine"`).
  assert.match(src, /kind === "lora" \? \[\["mine", "Mine"\]\]/,
    "the Mine button must be gated on kind === 'lora'");
});

test("base models get Model Type chips, LoRAs get categories -- not the same control", () => {
  // PixAI gives base models a different filter set: Model Type, Posted at, License. No LoRA
  // category, no Source, no My-LoRA tab. Rendering one shared row would half-apply. In React
  // this is the `kind === "lora" ? <categories> : <model-types>` ternary in the JSX.
  assert.match(src, /kind === "lora" \?/,
    "the category-vs-architecture choice must branch on kind");
  assert.match(src, /mg-mkttypes/, "base models need their own architecture chip row");
  assert.match(src, /data-mt=\{v\}/, "model-type chips must render from the BASE_TYPES list");

  // Every token measured off a live request 2026-07-26. A wrong enum here does not error -- it
  // returns the wrong rows, or none, and reads as an empty result, so none of these may drift.
  [["MMDIT26B_MODEL", "DiT.3"], ["MMDIT26A_MODEL", "DiT.2"], ["DIT7_MODEL", "DiT.1"],
   ["USER_DIT26A_MODEL", "Community DiT"], ["SDXL_MODEL", "SDXL"],
   ["SD_V1_MODEL", "SD 1.5"]].forEach(([token, label]) => {
    assert.match(src, new RegExp('\\["' + token + '", "' + label + '"\\]'),
      label + ' must map to ' + token + ' (measured, not inferred)');
  });

  // Community DiT is USER_DIT26A_MODEL, NOT DIT9_MODEL. Both were plausible and the wrong one
  // fails silently, which is why it was captured rather than guessed.
  assert.ok(!/DIT9_MODEL/.test(src),
    "DIT9_MODEL is not what Community DiT sends");
});

test("Model Type is multi-select, and All means clear", () => {
  // Measured: successive clicks sent [USER_DIT26A_MODEL], then [.., SDXL_MODEL], then
  // [.., SD_V1_MODEL]. A single-value control would have been quietly wrong. The element kept
  // a `this._modelTypes = []` array mutated by splice/push; the port keeps a useState array
  // updated immutably in the button's onClick.
  assert.match(src, /const \[modelTypes, setModelTypes\] = useState\(\[\]\)/, "must start as an array");
  // All (!v) clears; an already-chosen chip is filtered OUT; a new chip is concat'd IN.
  assert.match(src, /!v \? \[\]/, "the All chip must clear the set rather than select a token");
  assert.match(src, /old\.filter\(\(x\) => x !== v\)/, "clicking a chosen chip must REMOVE it");
  assert.match(src, /old\.concat\(v\)/, "clicking a new chip must ADD it");
  // Sent as a REPEATED param, matching the server reading request.args.getlist.
  assert.match(src, /modelTypes\.forEach\(\(t\) => \{ u \+= "&model_type=" \+ encodeURIComponent\(t\)/);
});

test("filters are hidden on the bookmark list, where the server cannot honour them", () => {
  // The bookmark connection accepts a keyword and the architecture filter and nothing else.
  // Leaving sort/category/dropdowns on screen there would be controls that silently do
  // nothing -- the specific failure mode that made the Enhance cards waste months. The
  // element's _syncFilterVisibility() toggled display; the port derives `filtersHidden` and
  // applies display:none, and still refuses to SEND those params in searchUrl.
  assert.match(src, /const filtersHidden = market && src === "bookmark"/,
    "bookmark must hide the filter block");
  assert.match(src, /filtersHidden \? \{ display: "none" \}/,
    "the derived hidden flag must actually collapse the filter block");
  assert.match(src, /if \(src !== "bookmark"\) \{/,
    "and must not SEND those params either -- a hidden control can still hold a stale value");
});

test("every market param is sent ONLY when market is on", () => {
  // This used to pin the URL builder's exact source line, which broke the moment round 3 added
  // three more filters -- while the thing it actually cares about was never in danger. It now
  // asserts the INTENT: a non-market mount (the Loom's base-model picker, or its existing LoRA
  // mount) must never send any market param. The server treats an unexpected category as
  // "ignored", so this would fail quietly rather than loudly, which is why it is pinned at all.
  // searchUrl is now a useCallback((cursor) => {...}, [deps]); extract its body up to the deps.
  const fn = src.match(/const searchUrl = useCallback\(\(cursor\) => \{[\s\S]*?\n  \}, \[/);
  assert.ok(fn, "could not find the searchUrl useCallback to inspect");
  const body = fn[0];

  const gate = body.indexOf("if (market) {");
  assert.ok(gate > 0, "searchUrl must gate market params behind the market prop");

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
  // The element did `self._sort = s; ...; self._search()` in the click handler. In React the
  // click sets state (setSort/setCategory), the "on" class is DERIVED from that state, and the
  // re-search is the effect below re-running doSearch whenever searchUrl changes -- and
  // searchUrl depends on sort + category, so a chip click provably refetches.
  assert.match(src, /onClick=\{\(\) => setSort\(v\)\}/, "a sort chip must update state");
  assert.match(src, /onClick=\{\(\) => setCategory\(v\)\}/, "a category chip must update state");
  // The refetch effect: unchanged key skips, changed key re-searches. This is the ONLY re-search
  // path, so it is what makes a state change actually refetch rather than only restyle.
  assert.match(src, /if \(key === lastKeyRef\.current\) return;[\s\S]{0,80}doSearch\(\);/,
    "a filter change must re-search, not only restyle");
  // searchUrl must actually depend on sort + category, or the effect key would never change.
  assert.match(src, /\}, \[kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType\]\);/,
    "searchUrl must depend on every filter so the refetch effect fires when one changes");
});

test("changing source or a filter dropdown also re-searches", () => {
  // A control that repaints itself but does not refetch is the worst kind of broken: it looks
  // like it worked. Each of these sets state that searchUrl depends on (asserted above), so the
  // refetch effect fires; here we pin that each control is actually wired to its setter.
  assert.match(src, /onClick=\{\(\) => setSrc\(v\)\}/, "switching source must update state (and thus re-search)");
  assert.match(src, /onChange=\{\(e\) => setPosted\(e\.target\.value\)\}/);
  assert.match(src, /onChange=\{\(e\) => setSource\(e\.target\.value\)\}/);
  assert.match(src, /onChange=\{\(e\) => setLicense\(e\.target\.value\)\}/);
  // The element toggled the select's `on` class off `!!sel.value`; the port derives it from
  // state (className={"mg-posted" + (posted ? " on" : "")}) -- a set filter still reads as set
  // at a glance without the refetch being a separate, forgettable step.
  assert.match(src, /"mg-posted" \+ \(posted \? " on" : ""\)/,
    "a set dropdown must still show as active, derived from state not a manual class toggle");
});
