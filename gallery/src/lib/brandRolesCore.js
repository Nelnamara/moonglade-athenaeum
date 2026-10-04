/* The Branding tab's named roles -- the rules the Roles section draws and checks with
   (Session X, Branding Roles Handoff; hidden, unlock-gated). Pure: loom/test/brand-roles-core.test.js
   holds them, components/BrandRoles.jsx and BrandRolesPhone.jsx draw them.

   WHO DECIDES. The server (moonglade_gallery.py: ROLE_SLOTS, role_image_spec, role_spec_failures)
   is the one that decides: it measures the file again and refuses what breaks the spec, whatever
   this module said. This module runs the SAME rules over the SAME measurements on the device first,
   so the editor can tick them live and nothing is uploaded that would be refused (the handoff's
   "checked locally before any upload"). The spec itself is not copied here: each IMAGE's effective
   spec arrives in the Branding payload (`roles[].images[].spec`) -- the role's formats and drawn
   minimum, with the shape and (where the pack's own art is smaller) the minimum size taken from the
   pack default that image replaces -- so the two cannot drift. The refusal sentences are pinned
   against the server's in tests/test_branding_roles.py and loom/test/brand-roles-core.test.js alike. */

export const ROLE_REFUSAL_END = "Your current art is unchanged.";
const NEED_VERB = { format: "be", transparent: "have", animation: "be", aspect: "be", size: "be" };

/** A picture's shape in words for a refusal: "1:1", "3:2", "16:9", else "1.68:1". */
export function ratioLabel(w, h) {
  if (!(w > 0) || !(h > 0)) return "0:0";
  const have = w / h;
  const gcd = (a, b) => (b ? gcd(b, a % b) : a);
  for (let q = 1; q <= 16; q++) {
    const p = Math.round(have * q);
    if (p >= 1 && Math.abs(have - p / q) / have <= 0.005) {
      const g = gcd(p, q);
      return (p / g) + ":" + (q / g);
    }
  }
  return have.toFixed(2) + ":1";
}

/** An image's shape in words, from the pack default it replaces: "about square" when that default is
    square to within the tolerance, else "about 9:10". The server says the same (_aspect_words). */
export function aspectWords(spec) {
  const [aw, ah] = spec.aspect;
  if (Math.abs(aw / ah - 1) <= spec.aspect_tolerance) return "about square";
  return "about " + ratioLabel(aw, ah);
}

/** "WEBP/PNG · transparent · about square · ≥ 480 px tall · animated WebP ok" (the gold mono line:
    the EFFECTIVE rule for this image). `phone` drops "tall", as the phone's role screen draws it. */
export function specLine(spec, { phone = false } = {}) {
  const min = "≥ " + spec.min_px + " px" + (spec.min_axis === "height" && !phone ? " tall" : "");
  const moves = (spec.animated_formats || []).length
    ? "animated " + spec.animated_formats.map((f) => (f === "WEBP" ? "WebP" : f)).join("/") + " ok" : null;
  return [spec.formats.join("/"), spec.transparent ? "transparent" : null, aspectWords(spec), min, moves]
    .filter(Boolean).join(" · ");
}

/** The rules `facts` breaks, in the editor's order (format, transparency, animation, shape, size).
    Mirrors role_spec_failures() on the server. facts = {format: "PNG", w, h, see_through: 0..1,
    animated}. Each failure is {rule, need, got}. */
export function specFailures(spec, facts) {
  const failed = [];
  const fmt = String(facts.format || "").toUpperCase();
  if (!spec.formats.includes(fmt)) {
    failed.push({ rule: "format", need: spec.formats.join(" or "), got: fmt || "unknown" });
  }
  if (spec.transparent && facts.see_through < spec.see_through_min) {
    failed.push({ rule: "transparent", need: "a transparent background",
      got: facts.see_through <= 0 ? "opaque" : (facts.see_through * 100).toFixed(1) + "% see-through" });
  }
  if (facts.animated && !(spec.animated_formats || []).includes(fmt)) {
    failed.push({ rule: "animation", need: "a still picture", got: "animated" });
  }
  const [aw, ah] = spec.aspect;
  const want = aw / ah;
  if (!(facts.h > 0) || Math.abs(facts.w / facts.h - want) / want > spec.aspect_tolerance) {
    failed.push({ rule: "aspect", need: aspectWords(spec), got: ratioLabel(facts.w, facts.h) });
  }
  const tall = spec.min_axis === "height";
  const have = tall ? facts.h : Math.min(facts.w, facts.h);
  if (have < spec.min_px) {
    const unit = tall ? " px tall" : " px";
    failed.push({ rule: "size", need: "at least " + spec.min_px + unit, got: have + unit });
  }
  return failed;
}

/** The live tick line once a file has landed: one entry per rule, in order, each
    {rule, ok, text}: "✓ WEBP  ✓ transparent  ✕ 3:4 (got 1:1)  ✓ ≥ 600 px". */
export function ticks(spec, facts) {
  const bad = new Map(specFailures(spec, facts).map((f) => [f.rule, f]));
  const fmt = String(facts.format || "").toUpperCase() || "unknown";
  const out = [];
  out.push(bad.has("format")
    ? { rule: "format", ok: false, text: spec.formats.join("/") + " (got " + fmt + ")" }
    : { rule: "format", ok: true, text: fmt });
  if (spec.transparent) {
    out.push(bad.has("transparent")
      ? { rule: "transparent", ok: false, text: "transparent (got " + bad.get("transparent").got + ")" }
      : { rule: "transparent", ok: true, text: "transparent" });
  }
  if (facts.animated) {
    out.push(bad.has("animation")
      ? { rule: "animation", ok: false, text: "still picture (got animated)" }
      : { rule: "animation", ok: true, text: "animated" });
  }
  const shape = aspectWords(spec);
  out.push(bad.has("aspect")
    ? { rule: "aspect", ok: false, text: shape + " (got " + bad.get("aspect").got + ")" }
    : { rule: "aspect", ok: true, text: shape });
  const min = "≥ " + spec.min_px + " px";
  out.push(bad.has("size")
    ? { rule: "size", ok: false, text: min + " (got " + bad.get("size").got + ")" }
    : { rule: "size", ok: true, text: min });
  return out;
}

/** The loud refusal: one broken rule reads "Refused: the Login companion must be 3:4. This one is
    1:1. Your current art is unchanged."; several read as pairs. Identical to the server's. */
export function refusalText(roleName, failed) {
  let what;
  if (failed.length === 1) {
    const f = failed[0];
    what = NEED_VERB[f.rule] + " " + f.need + ". This one is " + f.got + ".";
  } else {
    const parts = [];
    let last = null;
    for (const f of failed) {
      const verb = NEED_VERB[f.rule];
      parts.push((verb === last ? "" : verb + " ") + f.need + " (this one is " + f.got + ")");
      last = verb;
    }
    what = parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] + ".";
  }
  return "Refused: the " + roleName + " must " + what + " " + ROLE_REFUSAL_END;
}

/** What a file is, from its first bytes (the extension and the browser's MIME type are the sender's
    word; these are not). "" for anything the roles do not recognise. */
export function sniffFormat(bytes) {
  const b = bytes || [];
  const at = (i, s) => s.split("").every((c, k) => b[i + k] === c.charCodeAt(0));
  if (b[0] === 0x89 && at(1, "PNG")) return "PNG";
  if (at(0, "RIFF") && at(8, "WEBP")) return "WEBP";
  if (b[0] === 0xFF && b[1] === 0xD8 && b[2] === 0xFF) return "JPEG";
  if (at(0, "GIF8")) return "GIF";
  if (at(0, "BM")) return "BMP";
  if (at(4, "ftypavif")) return "AVIF";
  return "";
}

/** Whether the file moves, from its first bytes (a few KB are enough): an animated WebP sets the
    animation flag in its VP8X header; an animated PNG carries an acTL chunk ahead of its first
    IDAT. A GIF or anything else is not asked: it fails the format rule first. */
export function sniffAnimated(bytes, format) {
  const b = bytes || [];
  if (format === "WEBP") {
    const vp8x = b[12] === 0x56 && b[13] === 0x50 && b[14] === 0x38 && b[15] === 0x58;     // "VP8X"
    return !!(vp8x && (b[20] & 0x02));
  }
  if (format === "PNG") {
    let text = "";
    for (let i = 0; i < b.length; i++) text += String.fromCharCode(b[i]);
    const ac = text.indexOf("acTL");
    const idat = text.indexOf("IDAT");
    return ac >= 0 && (idat < 0 || ac < idat);
  }
  return false;
}

/** The share of pixels more than half see-through, from canvas RGBA data (alpha < 128). */
export function seeThroughFraction(rgba) {
  const n = Math.floor(rgba.length / 4);
  if (n === 0) return 0;
  let clear = 0;
  for (let i = 3; i < rgba.length; i += 4) if (rgba[i] < 128) clear++;
  return clear / n;
}

/** The longest side the transparency sample is drawn at: the share of clear pixels does not need
    the full picture, and a 4096 px canvas is a lot to ask of a phone. */
export const SAMPLE_PX = 256;

/** Measure a File or Blob on this device: {format, w, h, see_through, animated} or {unreadable: true}.
    The format and whether it moves are sniffed from the bytes; the size and transparency come from
    decoding it (the first frame, for an animation). */
export async function measureBlob(blob) {
  const head = new Uint8Array(await blob.slice(0, 4096).arrayBuffer());
  const format = sniffFormat(head);
  const animated = sniffAnimated(head, format);
  let bmp;
  try {
    bmp = await createImageBitmap(blob);
  } catch (e) {
    return { unreadable: true, format, animated };
  }
  const w = bmp.width, h = bmp.height;
  const scale = Math.min(1, SAMPLE_PX / Math.max(w, h));
  const cw = Math.max(1, Math.round(w * scale)), ch = Math.max(1, Math.round(h * scale));
  const canvas = document.createElement("canvas");
  canvas.width = cw; canvas.height = ch;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0, cw, ch);
  const see_through = seeThroughFraction(ctx.getImageData(0, 0, cw, ch).data);
  if (bmp.close) bmp.close();
  return { format, w, h, see_through, animated };
}

/** The collapsed row's second line: where the role shows, or for a multi-image role the image
    names and, once any is yours, "N of M yours". */
export function rowSub(role) {
  const mine = role.images.filter((i) => i.yours).length;
  if (role.images.length === 1) return role.where;
  const names = role.images.map((i) => i.label.toLowerCase()).join(" · ");
  return mine ? names + " · " + mine + " of " + role.images.length + " yours" : names;
}

/** The phone list row's state word: "yours", "default" or "N of M yours". */
export function phoneState(role) {
  const mine = role.images.filter((i) => i.yours).length;
  if (role.images.length === 1) return mine ? "yours" : "default";
  return mine ? mine + " of " + role.images.length + " yours" : "default";
}

/** An image's current URL, with its file's stamp so a changed override is fetched afresh. */
export function imageUrl(img) {
  return img.yours ? img.url + "?v=" + img.v : img.url;
}

/** Any image whose override cannot be read (the row says so, in peach, and the app shows the default). */
export function unreadableNote(role) {
  return role.images.some((i) => i.unreadable) ? "Your file couldn't be read; showing the default." : "";
}

/** The sentence the one-time ask opens with: "Go back to the default Login companion?". */
export function restoreAsk(role, img) {
  const what = role.images.length === 1 ? role.name : role.name + " (" + img.label.toLowerCase() + ")";
  return "Go back to the default " + what + "?";
}
export const RESTORE_BODY = "Your image is removed from this install.";
