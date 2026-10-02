/* THE HONORS CARD, BROWSER HALF (Session O, O6). Everything here runs on THIS device and talks
   to nothing but the app's own badge art (same origin, so the canvas stays clean and can be
   read back): the card is drawn, saved, copied or handed to the system share sheet locally, and
   nothing is uploaded. The rules of what it says and how it is laid out are honorsCardCore.js. */

import { badgeSources } from "../notify/badgeArt.js";
import { CARD_W, CARD_H, drawHonorsCard, CARD_FILE, shareText } from "./honorsCardCore.js";

const TOKENS = ["base", "mantle", "text", "subtext", "overlay0", "surface0", "gold", "lavender"];
const FALLBACK = {
  base: "#0c0a1c", mantle: "#080610", text: "#e7ddff", subtext: "#9a93ab", overlay0: "#6c6480",
  surface0: "#241a3f", gold: "#d4af37", lavender: "#b692e6",
};

/* The active skin's colours, read from the page's own tokens (so the card wears whatever skin
   is on), each with a fallback for a page that has not resolved one. */
export function readPalette(root) {
  const out = {};
  let cs = null;
  try { cs = getComputedStyle(root || document.documentElement); } catch { cs = null; }
  for (const k of TOKENS) {
    const v = cs ? cs.getPropertyValue("--" + k).trim() : "";
    out[k] = v || FALLBACK[k];
  }
  return out;
}

/* Each rarity's colour, as the Folio's own tier triad defines it (.mgfo-t-<tier> sets --tc). */
export function readTierColours(palette) {
  const out = {};
  for (const t of ["common", "rare", "epic", "legendary"]) {
    let v = "";
    try {
      const probe = document.createElement("i");
      probe.className = "mgfo-t-" + t;
      probe.style.display = "none";
      document.body.appendChild(probe);
      v = getComputedStyle(probe).getPropertyValue("--tc").trim();
      probe.remove();
    } catch { v = ""; }
    out[t] = v || palette.lavender;
  }
  return out;
}

/* One image, or null when it does not load in time. A badge is asked for as its still (the
   .png thumb): a canvas draws an animated file's first frame, and the still is the reliable
   rung of badgeArt's own ladder. */
function loadImage(src, ms = 4000) {
  return new Promise((resolve) => {
    if (!src) { resolve(null); return; }
    const img = new Image();
    let done = false;
    const end = (v) => { if (!done) { done = true; clearTimeout(t); resolve(v); } };
    const t = setTimeout(() => end(null), ms);
    img.onload = () => end(img);
    img.onerror = () => end(null);
    img.src = src;
  });
}

/* Draw the card for `model` and hand back the canvas. */
export async function renderHonorsCard(model, { markUrl } = {}) {
  const palette = readPalette();
  const tiers = readTierColours(palette);
  const [mark, ...pics] = await Promise.all([
    loadImage(markUrl),
    ...model.badges.map((b) => loadImage(badgeSources(b.id, 384)[1])),
  ]);
  const images = {};
  model.badges.forEach((b, i) => { images[b.id] = pics[i]; });
  const canvas = document.createElement("canvas");
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  drawHonorsCard(canvas.getContext("2d"), model, { palette, tiers, mark, images });
  return canvas;
}

export function canvasToBlob(canvas) {
  return new Promise((resolve) => {
    try { canvas.toBlob((b) => resolve(b || null), "image/png"); } catch { resolve(null); }
  });
}

/* Save: a download of the blob, made and revoked in this tab. Nothing is sent anywhere. */
export function saveBlob(blob) {
  if (!blob) return false;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = CARD_FILE;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return true;
}

/* Copy: the image onto the local clipboard. False where the browser will not allow it. */
export async function copyBlob(blob) {
  try {
    if (!blob || !navigator.clipboard || typeof ClipboardItem === "undefined") return false;
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  } catch { return false; }
}

/* Share: the phone's own system share sheet, with the image as a file. "unsupported" where the
   device cannot share files (the caller falls back to Save); "cancelled" when the person
   dismissed the sheet. */
export async function shareBlob(blob, model) {
  try {
    if (!blob || typeof navigator.share !== "function" || typeof File === "undefined") return "unsupported";
    const file = new File([blob], CARD_FILE, { type: "image/png" });
    if (navigator.canShare && !navigator.canShare({ files: [file] })) return "unsupported";
    await navigator.share({ files: [file], title: "The Folio of Honors", text: shareText(model) });
    return "shared";
  } catch (e) {
    return e && e.name === "AbortError" ? "cancelled" : "unsupported";
  }
}
