/* genPrefs.js -- which Generate settings follow the account, and the validation of what comes
   back. PURE (imports nothing); useGenerate.js does the reading and writing through the wave-1
   per-account store (/api/account/prefs), and the Lightbox edit bar reads the profile from it.
   Pinned by loom/test/tsubaki-core.test.js.

   Stored under ONE key, gen.image, as a small object:
     creativity  "off" | "low" | "medium"           decision 5
     tier        a size tier's name ("XL", "L", ...)  decision 6 ("" = the model's default)
     aspect      width ÷ height, 0.2 .. 5            decision 7
     landscape   the Portrait | Landscape switch      decision 7
     auto        Auto (size from @image1)             decision 1
     mode        the profile / quality mode           T1a
     recipes     [{id, title, cover}], at most 10     lane w2-recipes' row, the dock's state
   Never the prompt, the model, the LoRAs or the images: those are the draft, not settings.

   Everything read back is checked: a value of the wrong type or out of range is dropped, never
   repaired into something the owner did not pick. */

export const GEN_PREFS_KEY = "gen.image";
const LEVELS = ["off", "low", "medium"];
const MODES = ["auto", "lite", "standard", "pro", "ultra", "flash"];
export const RECIPE_MAX = 10;

export function prefsFromState(s) {
  return {
    creativity: s.creativity,
    tier: s.tier || "",
    aspect: Number(s.aspect) || 1,
    landscape: !!s.landscape,
    auto: s.auto !== false,
    mode: s.mode || "auto",
    recipes: (s.recipes || []).slice(0, RECIPE_MAX).map((r) => ({
      id: String(r.id), title: String(r.title || ""), cover: String(r.cover || ""),
    })),
  };
}

export function stateFromPrefs(v) {
  const out = {};
  if (!v || typeof v !== "object" || Array.isArray(v)) return out;
  if (LEVELS.includes(v.creativity)) out.creativity = v.creativity;
  if (typeof v.tier === "string" && /^[A-Za-z0-9]{0,8}$/.test(v.tier)) out.tier = v.tier;
  const a = Number(v.aspect);
  if (typeof v.aspect === "number" && isFinite(a) && a >= 0.2 && a <= 5) out.aspect = a;
  if (typeof v.landscape === "boolean") out.landscape = v.landscape;
  if (typeof v.auto === "boolean") out.auto = v.auto;
  if (typeof v.mode === "string" && MODES.includes(v.mode)) out.mode = v.mode;
  if (Array.isArray(v.recipes)) {
    out.recipes = v.recipes
      .filter((r) => r && typeof r === "object" && /^\d{1,32}$/.test(String(r.id || "")))
      .slice(0, RECIPE_MAX)
      .map((r) => ({ id: String(r.id), title: String(r.title || "").slice(0, 200),
        cover: typeof r.cover === "string" ? r.cover.slice(0, 2048) : "" }));
  }
  return out;
}

/* The dock's profile, for the Lightbox edit bar (T3a: "the dock's profile"). */
export function prefsMode(v) {
  const p = stateFromPrefs(v);
  return p.mode || "auto";
}
