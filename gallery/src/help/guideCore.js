/* THE FIRST-RUN GUIDE'S PURE CORE (Session I decision 1, "one guide in three layers").

     ① the welcome card   the first visit to a surface; "Show me around" or "Got it"
     ② the tour           only from "Show me around": 3-4 coach marks on real controls
     ③ Nel's notes        after ① or ②: one pinned note at a time, the next after the
                          control is used; Help -> "Hide Nel's notes" turns them off

   One key per surface per account (the wave 1 store, useAccountPrefs):
     guide.<surface> = welcome | tour | notes:<n> | done
   An ABSENT key is the first visit, so nothing is written until the person answers the
   welcome card -- opening a surface never writes. Branding's key therefore cannot exist
   before its tab does.

   THE NOTE CURSOR. A surface's steps are ONE ordered list: the first few carry tour text
   (the tour is that prefix) and every step carries note text. `notes:<n>` is the index of
   the next note to consider, so the tour and the notes share it: skipping the welcome card
   starts the notes at 0 (every control, the ones the tour would have shown included);
   finishing or skipping the tour at step k starts them at k + 1 (only what the tour did
   not reach). "the next shows after you've used that control" is the cursor moving past the
   note that was on screen.

   Also here: where a coach mark or a note sits next to its control, which is a question
   about rectangles and nothing else. Imports nothing; loom/test/guide-core.test.js. */

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

/* The welcome card's two answers. */
export function afterWelcome(choice) {
  return choice === "tour" ? "tour" : "notes:0";
}

/* The tour ends -- finished or skipped -- with step `k` (0-based) the last one shown. The
   notes pick up after it. */
export function afterTour(k, stepCount) {
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
