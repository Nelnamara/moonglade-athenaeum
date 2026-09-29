/* =========================================================================
   loom-shots-core.js — A COLLECTION AS ORDERED SHOTS (P5), as a pure builder.

   Session P, Stage B1 (NOTES P5; Loom Handoff.dc.html section B's P5 prose and section A's
   "▮ Send to The Loom · as shots, in order"; BUILD-w5-p §5.3; rulings 4, 9, 10; review N4).

   The gallery sends /loom?shots=<ids in order>&from=<collection>&n=<nonce>. The Loom reads it
   once (adoptShotsHandoff in master-storyboard.jsx: sanitised, capped, confirmed) and appends
   ONE act built here:

     {name: "Act N — from ❖ <name>", source: {kind: "collection", name, nonce}, cards: [...]}

   one image-to-video shot per picture, in order: the picture is the open frame, 5 s, titled
   from the picture's prompt (trimTitle), status "todo". NOTHING IS RENDERED -- a card made
   here carries no resultMid, no takes, no pending marker and no anchor, so it is exactly an
   unrendered shot the owner has not pressed Render on. An act whose nonce is already on the
   board is never added twice (a reload, a second tab).

   An imported picture (`local_…`) becomes a shot like any other; its card wears the peach
   "imported picture — can't be sent to PixAI yet" mark and generateShot refuses it before
   anything is priced (ruling 4, review F16) -- that is the card's and the render path's job,
   not this builder's.

   Same discipline as the other pure modules: NO React, no DOM, no window, no fetch, and it
   imports only loom-core.js (loom-no-auto-render.test.js pins that). Ids are ARGUMENTS
   (`idFor`), never generated here.
   ========================================================================= */

import { newCardShape } from "./loom-core.js";

export const SHOT_TITLE_MAX = 60;
export const SHOT_SECONDS = 5;
/** The `from` the gallery sends when the pictures were a plain selection, not a collection. */
export const FROM_SELECTION = "your selection";

// Sentence punctuation a trimmed title should not end on (brackets and quotes are kept: a
// title ending "(close up)" keeps its bracket).
const TRAILING = /[\s.,;:!?…\-–—·|/\\]+$/u;

/**
 * trimTitle(prompt, n): the picture's prompt as a shot title -- its first line, cut at a word
 * boundary to at most 60 characters, trailing punctuation stripped. Nothing left -> "Picture n".
 */
export const trimTitle = (prompt, n) => {
  const first = String(prompt == null ? "" : prompt).split(/\r?\n/).map((l) => l.trim()).find((l) => l) || "";
  let t = first.replace(/\s+/g, " ").trim();
  if (t.length > SHOT_TITLE_MAX) {
    const cut = t.slice(0, SHOT_TITLE_MAX + 1);
    const sp = cut.lastIndexOf(" ");
    t = sp > 0 ? cut.slice(0, sp) : t.slice(0, SHOT_TITLE_MAX);
  }
  t = t.replace(TRAILING, "").trim();
  return t || "Picture " + (Number(n) > 0 ? Number(n) : 1);
};

/** The collection hand-off an act came from, or "" (a hand-made act). */
export const actNonce = (act) => (act && act.source && act.source.kind === "collection" ? String(act.source.nonce || "") : "");

/** Is an act with this nonce already on the board? (reload, two tabs: a no-op) */
export const hasShotsAct = (project, nonce) => !!nonce
  && ((project && project.acts) || []).some((a) => actNonce(a) === String(nonce));

/** The act's name: "Act 4 — from ❖ Loom stills" (a plain selection has no ❖). */
export const shotsActName = (actNumber, name) => {
  const label = String(name || "").trim() || FROM_SELECTION;
  return "Act " + actNumber + " — from " + (label === FROM_SELECTION ? label : "❖ " + label);
};

/**
 * shotsFromPictures(pictures, {actNumber, name, nonce, idFor}) -> act
 *   pictures  [{id, prompt}] in the order they become shots
 *   idFor     (kind, index) -> a fresh id: ("act", 0) for the act, ("card", i) per shot
 */
export const shotsFromPictures = (pictures, opts = {}) => {
  const { actNumber = 1, name = "", nonce = "", idFor } = opts;
  const mk = typeof idFor === "function" ? idFor : (kind, i) => kind + "-" + i;
  const cards = (pictures || []).map((p, i) => newCardShape(mk("card", i), {
    mode: "I2V", duration: SHOT_SECONDS, status: "todo",
    title: trimTitle(p && p.prompt, i + 1),
    openFrame: { mediaId: String((p && p.id) || ""), thumbId: "", source: "", desc: "", tag: "" },
  }));
  return {
    id: mk("act", 0), name: shotsActName(actNumber, name), collapsed: false, cards,
    source: { kind: "collection", name: String(name || "").trim() || FROM_SELECTION, nonce: String(nonce || "") },
  };
};

/** Append the act unless its nonce is already on the board: {project, added}. */
export const appendShotsAct = (project, act) => {
  if (!project || !act) return { project, added: false };
  if (hasShotsAct(project, actNonce(act))) return { project, added: false };
  return { project: { ...project, acts: [...(project.acts || []), act] }, added: true };
};
