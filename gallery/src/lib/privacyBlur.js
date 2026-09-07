/* privacyBlur -- the library's PRIVACY blur: the eye toggle that frosts thumbnails so the
   catalogue is not readable over your shoulder. All thumbs 16px, flagged ones 28px, hover
   reveals -- the classic gallery's semantics, kept deliberately.

   NOT to be confused with lib/blurPref.js. That one is "Blur behind popups", a PERFORMANCE
   preference about scrim `backdrop-filter`, stored under mg_noblur and inverted (the stored
   value means blur OFF). This one is about PRIVACY, stored under gallery_privacy_blur, and
   reads the honest way round: "1" means blur ON. They are two different toggles that happen
   to share a word.

   WHY THIS MODULE EXISTS (2026-09-07). The key was read and written inline in App.jsx and
   nowhere else, so `blur` reached exactly one surface -- the grid, as
   `"gridwrap" + (blur ? " mgg-blur" : "")` (Grid.jsx). The gallery picker and the generate
   drawer's reference slots carried their own rules keyed on `body.privacy-blur`, and
   NOTHING in the app has ever put a class on <body> -- so those two surfaces never blurred
   at all, on either shell. Rather than teach three files the same string, the key lives here
   once and every surface reads it through this module.

   HOW IT REACHES THE CSS. One class, `mg-blur`, on each surface's OWN root -- not on <body>
   and not on <html>. The grid keeps its own long-standing `mgg-blur` (grid.css); the picker
   and the drawer answer to `.mg-gallery-picker.mg-blur` and `.gen-drawer.mg-blur`. Scoping
   to the surface's own root is what makes this work inside the Loom too, which mounts the
   shared GalleryPicker but has no App.jsx and no gallery <body>.

   Storage can throw outright (private mode, site data blocked). The honest answer there is
   "no preference stored", which means the default: blur OFF, exactly as an install that has
   never touched the eye behaves. Same try/catch discipline as lib/blurPref.js. */

export const PRIVACY_BLUR_KEY = "gallery_privacy_blur";
export const PRIVACY_BLUR_CLASS = "mg-blur";

/** Is the privacy blur switched ON for this browser? Only an explicit "1" counts, so an
    empty string and a missing key are both "off" -- App.jsx has always written "" rather
    than removing the key, and every reader compares `=== "1"`. */
export function isPrivacyBlurOn() {
  try { return localStorage.getItem(PRIVACY_BLUR_KEY) === "1"; } catch { return false; }
}

/** Write the preference. Per-browser by design: it is a property of the screen you are
    sitting in front of, not of the account, so it never reaches config.json. */
export function setPrivacyBlurOn(on) {
  try { localStorage.setItem(PRIVACY_BLUR_KEY, on ? "1" : ""); } catch { /* private mode */ }
}

/** The class suffix a surface root appends. Kept as a helper so no caller has to spell the
    class name, which is how the picker and the drawer drifted apart from the grid before. */
export function privacyBlurClass(on) {
  return on ? " " + PRIVACY_BLUR_CLASS : "";
}
