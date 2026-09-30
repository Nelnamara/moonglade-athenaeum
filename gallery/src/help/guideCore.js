/* THE FIRST-RUN GUIDE'S PURE CORE (Session I decision 1, "one guide in three layers").

     ① the welcome card   the first visit to a surface; "Show me around" or "Got it"
     ② the tour           only from "Show me around": 3-4 coach marks on real controls
     ③ Nel's notes        only after the tour is FINISHED with Done: one pinned note at a
                          time, the next after the control is used. Every note carries
                          "hide notes" (the same switch as Help -> "Hide Nel's notes"), and
                          Escape waves off the one on screen.

   NO WAY IN WITHOUT A WAY OUT (owner walk 2026-09-29: "forced to do the first run tutorial
   with no way out of it"). "Got it" on the welcome card and "Skip tour" (or Escape) on the
   tour both END the guide for that surface -- no notes follow either. Finishing the tour
   with Done is the one road into the notes, because that person asked to be shown around.

   One key per surface per account (the wave 1 store, useAccountPrefs):
     guide.<surface> = welcome | tour | notes:<n> | done
   An ABSENT key is the first visit, so nothing is written until the person answers the
   welcome card -- opening a surface never writes. Branding's key therefore cannot exist
   before its tab does.

   THE NOTE CURSOR. A surface's steps are ONE ordered list: the first few carry tour text
   (the tour is that prefix) and every step carries note text. `notes:<n>` is the index of
   the next note to consider, so the tour and the notes share it: finishing the tour starts
   the notes after it (only what the tour did not reach). "the next shows after you've used
   that control" is the cursor moving past the note that was on screen.

   Also here: where a coach mark or a note sits next to its control, which is a question
   about rectangles and nothing else, and which open layers a note must never draw over.
   Imports nothing; loom/test/guide-core.test.js. */

export const GUIDE_SURFACES = ["gallery", "dock", "loom", "folio", "panel", "branding"];
export const NOTES_HIDDEN_KEY = "guide.notes_hidden";

export function guideKey(surface) {
  return "guide." + surface;
}

/* The stored value -> {phase, n}. An absent value is the first visit; a value this build
   cannot read is treated as DONE, never as a reason to show the welcome card again. */
export function readGuide(v) {
  if (v === undefined || v === null || v === "" || v === "welcome") return { phase: "welcome", n: 0 };
  if (v === "tour") return { phase: "tour", n: 0 };
  if (v === "done") return { phase: "done", n: 0 };
  const m = /^notes:(\d{1,4})$/.exec(String(v));
  if (m) return { phase: "notes", n: Number(m[1]) };
  return { phase: "done", n: 0 };
}

/* The welcome card's two answers. "Got it" is done: no notes follow it. */
export function afterWelcome(choice) {
  return choice === "tour" ? "tour" : "done";
}

/* The tour ends with step `k` (0-based) the last one shown. Finished with Done, the notes
   pick up after it; skipped (the Skip button or Escape), the guide is done. */
export function afterTour(k, stepCount, skipped) {
  if (skipped) return "done";
  const next = Math.max(0, Math.min((k | 0) + 1, stepCount | 0));
  return "notes:" + next;
}

/* Note `j` was used (or waved off with "got it"): the cursor moves past it, and past the
   end the surface is done. */
export function afterNote(j, total) {
  const next = (j | 0) + 1;
  return next >= (total | 0) ? "done" : "notes:" + next;
}

/* The tour's steps and the notes' list for one surface's step data. */
export function tourSteps(steps) {
  return (steps || []).filter((s) => s && s.tour);
}
export function noteText(step) {
  return (step && (step.note || step.tour)) || "";
}

/* The first note at or after the cursor whose control is on screen right now (`present`
   answers that for a step), or -1. A note whose control is not showing is passed over for
   now rather than holding up the rest; the cursor only ever moves past the note that was
   actually shown, so a skipped one simply never interrupts. */
export function firstPresentNote(steps, n, present) {
  for (let j = Math.max(0, n | 0); j < (steps || []).length; j++) {
    if (present(steps[j], j)) return j;
  }
  return -1;
}

/* Where a card of `size` {w, h} sits beside a control's rect {left, top, right, bottom} in a
   viewport {w, h}. Below the control when it fits, above when it does not; lined up with the
   control's right edge when the control is on the right half of the screen (the header's
   right-hand buttons), its left edge otherwise; always inside the viewport by `margin`.
   Returns {left, top, placement: "below" | "above"}. */
export function placeBeside(rect, size, viewport, gap, margin) {
  const g = gap == null ? 10 : gap;
  const mg = margin == null ? 12 : margin;
  const vw = viewport.w, vh = viewport.h;
  const below = rect.bottom + g;
  const above = rect.top - g - size.h;
  let placement = "below";
  let top = below;
  if (below + size.h > vh - mg && above >= mg) { placement = "above"; top = above; }
  const onRight = (rect.left + rect.right) / 2 > vw / 2;
  let left = onRight ? rect.right - size.w : rect.left;
  left = Math.max(mg, Math.min(left, vw - mg - size.w));
  top = Math.max(mg, Math.min(top, vh - mg - size.h));
  return { left: Math.round(left), top: Math.round(top), placement };
}

/* Is a rect worth pointing at: non-empty and at least partly inside the viewport. */
export function rectShowing(rect, viewport) {
  if (!rect || rect.width <= 0 || rect.height <= 0) return false;
  return rect.bottom > 0 && rect.right > 0 && rect.top < viewport.h && rect.left < viewport.w;
}

function overlaps(a, b) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/* THE CHIPS A NOTE MUST NOT COVER: the header's chip row -- the pinned goal and the Vigil
   (with the pin's ✕), the credits and followers chips, the claim, Activity (owner walk
   2026-09-29: the Generate note sat over the pin chip's ✕ and the Vigil). */
export const CHIP_ROW = ".mgg-chips, .mgx-cred, .mgx-claim, .mgx-act-wrap";

/* ...AND EVERY OTHER CONTROL IN THE HEADER (owner walk 2026-09-29, second pass: after the tour
   the Filters note sat right under Filters, over the nav row -- IMPORT · CONTESTS · HEALTH ·
   PANEL -- and a click meant for HEALTH landed on the note). The header band is the banner and
   the nav band under it (App.jsx's <header className="mgx-hdr">); anything in it that can be
   clicked, typed in or dragged is kept clear, and the search slab whole (its glyph is a bare
   clickable <i>). NOTE_AVOID is what GuideHost measures. */
export const HEADER_BAND = ".mgx-hdr";
export const HEADER_CONTROLS = [
  "button", "a[href]", "input", "select", "textarea", "summary", ".mgl-search",
  '[role="button"]', '[role="link"]', '[role="tab"]', '[role="switch"]', '[role="slider"]',
  '[role="checkbox"]', '[role="combobox"]', '[tabindex]:not([tabindex="-1"])',
].map((s) => HEADER_BAND + " " + s).join(", ");
export const NOTE_AVOID = CHIP_ROW + ", " + HEADER_CONTROLS;

/* placeBeside, kept clear of `avoid` (the rects of NOTE_AVOID). The natural spot first; then,
   for a control IN the header band (`band`, its {top, bottom}), just below the band -- over the
   grid, lined up with the control's edges; then below or above the control, each lined up
   with the control's own left and right edges. The first that covers nothing in `avoid` wins;
   null when every one does, and then that note is not shown at all. */
export function placeClear(rect, size, viewport, avoid, gap, margin, band) {
  const g = gap == null ? 10 : gap;
  const mg = margin == null ? 12 : margin;
  const first = placeBeside(rect, size, viewport, g, mg);
  const list = (avoid || []).filter((a) => a && a.right > a.left && a.bottom > a.top);
  const clampL = (l) => Math.round(Math.max(mg, Math.min(l, viewport.w - mg - size.w)));
  const tops = { below: rect.bottom + g, above: rect.top - g - size.h };
  const order = first.placement === "below" ? ["below", "above"] : ["above", "below"];
  const cands = [first];
  if (band && band.bottom > band.top && rect.top < band.bottom) {
    const top = Math.round(Math.max(band.bottom, rect.bottom) + g);
    if (top + size.h <= viewport.h - mg) {
      for (const left of [first.left, clampL(rect.left), clampL(rect.right - size.w)]) {
        cands.push({ left, top, placement: "below" });
      }
    }
  }
  for (const placement of order) {
    const top = Math.round(tops[placement]);
    if (top < mg || top + size.h > viewport.h - mg) continue;   // off screen that way
    for (const left of [first.left, clampL(rect.left), clampL(rect.right - size.w)]) {
      cands.push({ left, top, placement });
    }
  }
  for (const c of cands) {
    const box = { left: c.left, top: c.top, right: c.left + size.w, bottom: c.top + size.h };
    if (!list.some((a) => overlaps(box, a))) return c;
  }
  return null;
}

/* THE LAYERS A NOTE NEVER DRAWS OVER (owner walk 2026-09-29: notes sat on top of the model
   picker, the Colour palette dialog and the recipe market). Anything the app opens over a
   surface matches one of these: a dialog, a menu, a list that drops down, and the four
   layers that carry no role of their own. GuideHost asks the page which are open and
   `layerOpen` decides. */
export const LAYER_SELECTORS = [
  '[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]', '[role="menu"]',
  '[role="listbox"]',
  ".mfly.open",           // the model / LoRA browser
  ".mg-gallery-picker",   // the gallery picker (it is its own scrim)
  ".mgl-menu",            // the library's drop-down menus
  ".at-panel",            // the Activity drop-down
].join(", ");

/* Is one of `layers` open over the surface? Each is {showing, own, holdsAnchor}: `showing`,
   drawn and on screen; `own`, one of the guide's own cards; `holdsAnchor`, it contains one
   of the surface's controls -- so it IS the surface (the dock, the Folio's slab, the Control
   Panel), not something opened over it. */
export function layerOpen(layers) {
  return (layers || []).some((l) => !!(l && l.showing && !l.own && !l.holdsAnchor));
}
