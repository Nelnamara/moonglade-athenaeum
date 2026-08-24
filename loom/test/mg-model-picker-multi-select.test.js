import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// D-11: the model/LoRA picker gained an opt-in multi-select mode for the Loom's LoRA
// picker (single-value mode, the default, is unchanged). This locks in the shape of the
// toggle/resolve logic; real interaction verification (does the chip actually render, does
// weight-editing work) needs a real browser -- so, as with the other picker tests, these
// are source-presence assertions, not full instantiation (no jsdom in this runner).
//
// The <mg-model-picker> custom element was ported to a React component
// (gallery/src/components/ModelPicker.jsx, 2026-08-08). Every multi-select behaviour
// survives the port, so these assertions were retargeted to the React source. The one
// deliberate idiom change: selection is now CONTROLLED by the host, so the vanilla's
// `mg-pick` CustomEvent with a { model, selected } detail became an onToggle(model, selected)
// prop, and the internal `_selected` array + `deselect()` method became the `selected` prop
// the host owns. The mapping used below:
//   this._multi = this.hasAttribute('multi')  -> `multi` prop (opt-in, defaults false)
//   _toggleMulti(m, card)                      -> const toggleMulti = (m) => { ... }
//   _isSelected(m) { ... this._multi ... }     -> const isSelected = useCallback((m) => (multi ...))
//   this._selected / this._value               -> the controlled `selected` / `value` props
//   dispatch mg-pick {model,selected}          -> onToggle(model, selected)
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/ModelPicker.jsx"), "utf8");

test("ModelPicker supports an opt-in multi-select mode", () => {
  assert.match(src, /kind = "base", multi = false/,
    "multi must be an opt-in PROP defaulting off (the host enables it) -- not always-on");
  assert.match(src, /const toggleMulti\s*=\s*\(m\)\s*=>\s*\{/,
    "multi-select needs its own toggle path, not a straight replace like single-value pick");
  assert.match(src, /const isSelected\s*=\s*useCallback\(\(m\)\s*=>\s*\(multi[\s\S]*?selected\.some[\s\S]*?value/,
    "card selection state must branch on multi (reading the controlled `selected` array in " +
    "multi mode, the `value` prop in single mode), or the .sel class breaks in one mode");
});

test("a picked LoRA resolves version_id/lora_base_type/trigger_words via /api/model-version?all=1", () => {
  // &all=1 (per-LoRA version selection): every published release, not just the silently-assumed
  // rows[0] -- the full `versions` array is stashed on the dispatched entry so a per-chip
  // selector (the host's job, same split as the base model's #gen-version/.lv-versel) can offer
  // a real choice, mirroring exactly how onBasePick/onLoraPick already do it for base models.
  // Re-anchored 2026-08-23: the read rides api.js's apiGet -- same endpoint, same &all=1.
  assert.match(src, /apiGet\("\/api\/model-version\?model_id=" \+ encodeURIComponent\(m\.model_id\) \+ "&all=1"\)/,
    "each multi-select pick must resolve real generation metadata AND every published " +
    "version, the same endpoint/param the base-model picker already uses -- without it, " +
    "version_id stays '' and the LoRA can never actually be submitted, and there's no " +
    "version list for a per-chip selector to offer");
  assert.match(src, /const versions = \(d && d\.versions\) \|\| \[\], v = versions\[0\] \|\| \{\};/);
  assert.match(src, /version_id: v\.version_id \|\| "",/);
  assert.match(src, /lora_base_type: v\.lora_base_model_type/);
  assert.match(src, /trigger_words: v\.trigger_words \|\| "",\s*versions,/,
    "the full version list must ride the dispatched entry so a host can render a per-chip selector");
});

test("an unresolved/failed LoRA is marked failed, never silently dropped", () => {
  // Mirrors the Gallery's fail-open fix (audit 2026-07-21, fail-open/high): a LoRA that
  // never resolves must not be able to vanish from a submit unnoticed. Both the
  // "resolved but empty" and the network-failure paths must set failed. (In the controlled
  // React port the resolved-but-empty case is `failed: !v.version_id` -- v.version_id is what
  // entry.version_id gets set to, so this is the same condition the element expressed as
  // `!entry.version_id`.)
  assert.match(src, /failed: !v\.version_id/);
  // The catch first drops out for an entry the user un-picked while the resolve was in flight
  // (the superseded-response guard -- `selectedRef.current` no longer holds this model_id --
  // is what stops a removed LoRA being resurrected), so match the failed:true dispatch inside
  // the catch rather than requiring it to be the very first statement.
  assert.match(src, /\.catch\(\(\) => \{[\s\S]{0,200}?failed: true/,
    "a resolve that fails must still mark the entry failed, never drop it silently");
});
