// The Generate dock's height story -- the design of record's own arithmetic, lifted
// out of the React dock so the SAME function the dock renders from can be run by the
// tests against a plain state object (no source extraction, no DOM).
//
// Source: design_handoff/design_handoff_moonglade_suite/Frontend Gallery.dc.html (C3a)
//   measureDock 2020-2047 (the prompt-rows cap), fitReel 2071-2081 (the reel's room and
//   tier), reelShown 2823, promptRows 3561 -- as tuned by the owner's height pass,
//   calls 08-16d/e/f (drift-report §43, handoff-2026-08-16-generate-dock-history §4):
//
//   · standard stays under the separator-bar ceiling; ▲ / a long prompt / History may grow
//     to 100vh − 28 (since the owner walk of 2026-09-29 the collapsed dock is one fixed
//     height, never content-sized -- collapsedHeight below);
//   · the prompt's resting floor is 6 rows -- grows with the text (76 chars a row, +1
//     while focused) to the room-driven cap, max 14; past that the textarea scrolls,
//     never the panel;
//   · ▲ keeps the reel visible above the settings slabs: tiles tier to 84/104 in ▲,
//     the reel's room is measured against ▲'s own ceiling minus the ~330px of slab
//     chrome, and the reel auto-hides only when a short window leaves it under 60px;
//     open History always shows its strip;
//   · ▲ and History compose (neither toggle closes the other -- that lives in the dock).
//
// One deliberate reading: the DC's measureDock chrome still zeroes the reel in ▲
// (`expanded ? 0 : reelH + 46`, a line older than 08-16e's reel-stays call). We count the
// reel whenever it is SHOWN -- the DC's own invariant ("never the panel") -- which can
// only lower the cap in ▲, never the 6-row floor.

import { HISTORY_STRIP } from "./historyCore.js";

export const PROMPT_FLOOR = 6;     // rows at rest (08-16d/f)
export const PROMPT_CAP = 14;      // rows, room permitting
export const PROMPT_COLS = 76;     // chars per row the DC counts with
export const LONG_PROMPT_ROWS = 4; // past this the dock may leave the separator ceiling
export const REEL_MIN_ROOM = 60;   // px of room below which the reel hides
export const SLAB_CHROME = 330;    // px the ▲ settings slabs take from the reel's room
export { HISTORY_STRIP };          // px the 2-row History strip takes (historyCore.js)
// The collapsed dock's fixed height (owner walk 2026-09-29, second pass) budgets the composer's
// Session M pieces from their own CSS, so a Random / Matrix switch lands inside the budget:
export const RUN_ROOM = 212;       // px: token line 18 + Random | Matrix row 44 + preview at its
                                   // fullest 150 (label + six rows + "… N more", runs.css)
export const QUICK_ROW = 30;       // px: one MODELS / LORAS chip row and its gap (power.css)

/* The collapsed dock's HEIGHT -- one fixed number per window (owner walk 2026-09-29, second
   pass: the first pass's "never shrinks" hold still moved the Image · Edit · Video tabs, because
   each tab had its own ceiling and a first visit to a taller mode still grew the dock). It is
   what the tallest mode needs at this window -- the tabs row, the reel's slot and the Image
   composer (its prompt at the resting floor, or at the 14-row cap while the prompt is long; the
   run pieces while the prompt uses variables; the quick-pick rows the account has) -- capped at
   100vh − 28. Nothing it reads changes on an Image / Edit / Video, Random / Matrix or LoRAs /
   Context switch (the prompt, its variables and the chip rows belong to the draft and the
   account, not the tab), so those switches never move the tabs; a mode with less shows room in
   the body, and the body scrolls if a mode ever holds more. The owner's finding wins over the
   height pass's "content-sized" here.
     · standard stays under the separator bar when that leaves the composer its room; past it
       the reel's slot is given up first, the composer's never (Session M's "the reel yields");
     · History and a long prompt lift the ceiling as the DC's dockStyle does, sized to need. */
function collapsedHeight({ vh, sepBottom, historyOpen, longPrompt, variables, quickRows, reelTier }) {
  const reelSlot = historyOpen ? HISTORY_STRIP : reelTier + 46;
  const composer = 96 + (longPrompt ? PROMPT_CAP : PROMPT_FLOOR) * 25
    + (variables ? RUN_ROOM : 0) + Math.max(0, Number(quickRows) || 0) * QUICK_ROW;
  const need = 46 + reelSlot + composer;
  if (historyOpen || longPrompt) return Math.min(vh - 28, need);
  return Math.min(vh - 28, Math.max(46 + composer, Math.min(need, vh - sepBottom - 14)));
}

export function dockLayout({ vh, sepBottom, expanded, historyOpen, promptLen, promptFocus, extraPx,
  variables, quickRows }) {
  const promptLines = Math.ceil((promptLen || 1) / PROMPT_COLS);
  const longPrompt = promptLines > LONG_PROMPT_ROWS;
  // Session M: the composer's run pieces (the variables' line, Random | Matrix, the preview,
  // the Lists sheet, THE confirm), measured. The reel gives up its room to them first; the
  // collapsed height already budgets them (collapsedHeight), so they never move the dock.
  // 0 (or absent) changes nothing below.
  const extra = Math.max(0, Number(extraPx) || 0);
  const reelTier = expanded
    ? (vh < 760 ? 84 : 104)
    : (vh < 620 ? 64 : vh < 820 ? 96 : 132);
  // the dock's height: ▲ is 100vh − 28 (DC dockStyle 3505-3506); collapsed, the one fixed
  // height above
  const capH = expanded ? vh - 28
    : collapsedHeight({ vh, sepBottom, historyOpen, longPrompt, variables, quickRows, reelTier });
  // fitReel: the reel's room under the dock's own height, less header · footer · caption +
  // padding, less the slabs in ▲
  const reelRoom = capH - 56 - 118 - 46 - (expanded ? SLAB_CHROME : 0) - extra;
  const reelH = Math.max(44, Math.min(reelTier, reelRoom));
  const reelVisible = !!historyOpen || reelRoom >= REEL_MIN_ROOM;
  // measureDock: how many prompt rows the dock can actually show. In History the strip
  // (2 rows of fixed 96px tiles) replaces the reel's one-row term.
  const chrome = 46 + (historyOpen ? HISTORY_STRIP : (reelVisible ? reelH + 46 : 0))
    + (expanded ? SLAB_CHROME : 0) + 96 + extra;
  const promptMax = Math.max(2, Math.min(PROMPT_CAP, Math.floor((capH - chrome) / 25)));
  const promptRows = Math.max(PROMPT_FLOOR,
    Math.min(promptMax, promptLines + (promptFocus ? 1 : 0)));
  return { promptLines, longPrompt, capH, reelRoom, reelTier, reelH, reelVisible, promptMax, promptRows };
}

/* The dock's box while it is open -- what keeps its top edge, and the Image · Edit · Video tabs
   on it, where they are (owner walk 2026-09-29: the dock is bottom-anchored, so any change in
   its height moves the tabs under the mouse). The box is a HEIGHT, never content-sized: in ▲
   100vh − 28 (top 14px from the window's top), collapsed dockLayout's one fixed height. A mode
   with less shows room in its body; a mode with more scrolls its body.
   The one exception is the composer itself: the body scrolls, the composer never does, so if
   the tabs row and the composer (`fitPx`, measured) ever need more than the fixed height -- THE
   confirm open in a short window, say -- the dock grows to fit them rather than cut off the
   Generate button, up to 100vh − 28. -> {height, maxHeight} in px. */
export function dockBox({ vh, capH, fitPx }) {
  const ceil = Math.max(180, (Number(vh) || 0) - 28);
  const rule = Math.max(180, Number(capH) || 0);
  const fit = Math.max(0, Math.round(Number(fitPx) || 0));
  const h = Math.min(ceil, Math.max(rule, fit));
  return { height: h, maxHeight: h };
}
