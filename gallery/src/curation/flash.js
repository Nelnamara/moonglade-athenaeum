/* The gold flash that confirms a rating on each target (N5). Imperative on purpose: the
   grid is memoized and its cards take no per-key props, so the flash is a short-lived
   element appended to the card (or the open Lightbox / record) and removed again -- the same
   reach the palette's focus and the viewer landing make into the grid's own DOM.

   Motion: curation.css animates .mgcu-flash and, under prefers-reduced-motion, leaves it
   STATIC (it still appears, it just does not move), which is what "static under reduced
   motion" asks for. */
import { flashText } from "./curationCore.js";

export const FLASH_MS = 720;

function cardFor(mediaId) {
  const q = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(String(mediaId)) : String(mediaId).replace(/["\\]/g, "\\$&");
  try { return document.querySelector('.mgg-card[data-id="' + q + '"]'); } catch { return null; }
}

/* Where a flash for `mediaId` lands: its grid card if it is on screen, else the open viewer's
   picture (Lightbox), else the open record's frame. `openId` is the picture the viewer or
   record is showing. */
function hostsFor(mediaId, openId) {
  const hosts = [];
  const card = cardFor(mediaId);
  if (card) hosts.push(card);
  if (openId && String(openId) === String(mediaId)) {
    const stage = document.querySelector(".lbx-hero") || document.querySelector(".placard-frame");
    if (stage) hosts.push(stage);
  }
  return hosts;
}

export function flashRating(mediaIds, rating, openId) {
  if (typeof document === "undefined") return;
  const text = flashText(rating);
  for (const id of mediaIds) {
    for (const host of hostsFor(id, openId)) {
      const el = document.createElement("span");
      el.className = "mgcu-flash";
      el.setAttribute("aria-hidden", "true");
      el.textContent = text;
      host.appendChild(el);
      window.setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, FLASH_MS);
    }
  }
}
