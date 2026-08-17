// The Generate dock's height story -- the design of record's own arithmetic, lifted
// out of the React dock so the SAME function the dock renders from can be run by the
// tests against a plain state object (no source extraction, no DOM).
//
// Source: design_handoff/design_handoff_moonglade_suite/Frontend Gallery.dc.html (C3a)
//   measureDock 2020-2047 (the prompt-rows cap), fitReel 2071-2081 (the reel's room and
//   tier), reelShown 2823, promptRows 3561 -- as tuned by the owner's height pass,
//   calls 08-16d/e/f (drift-report §43, handoff-2026-08-16-generate-dock-history §4):
//
//   · standard stays CONTENT-SIZED under the separator-bar ceiling; ▲ / a long prompt /
//     History may grow to 100vh − 28;
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

export function dockLayout({ vh, sepBottom, expanded, historyOpen, promptLen, promptFocus }) {
  const promptLines = Math.ceil((promptLen || 1) / PROMPT_COLS);
  const longPrompt = promptLines > LONG_PROMPT_ROWS;
  // the dock's clamp (DC dockStyle 3505-3506): the separator ceiling, or 100vh − 28 in ▲ /
  // with a long prompt / in History -- History is its own dock mode
  const capH = (expanded || longPrompt || historyOpen) ? vh - 28 : vh - sepBottom - 14;
  // fitReel: the reel's room under ITS ceiling (▲'s / History's own when open), less
  // header · footer · caption + padding, less the slabs in ▲
  const reelCap = (expanded || historyOpen) ? vh - 28 : vh - sepBottom - 14;
  const reelRoom = reelCap - 56 - 118 - 46 - (expanded ? SLAB_CHROME : 0);
  const reelTier = expanded
    ? (vh < 760 ? 84 : 104)
    : (vh < 620 ? 64 : vh < 820 ? 96 : 132);
  const reelH = Math.max(44, Math.min(reelTier, reelRoom));
  const reelVisible = !!historyOpen || reelRoom >= REEL_MIN_ROOM;
  // measureDock: how many prompt rows the dock can actually show. In History the strip
  // (2 rows of fixed 96px tiles) replaces the reel's one-row term.
  const chrome = 46 + (historyOpen ? HISTORY_STRIP : (reelVisible ? reelH + 46 : 0))
    + (expanded ? SLAB_CHROME : 0) + 96;
  const promptMax = Math.max(2, Math.min(PROMPT_CAP, Math.floor((capH - chrome) / 25)));
  const promptRows = Math.max(PROMPT_FLOOR,
    Math.min(promptMax, promptLines + (promptFocus ? 1 : 0)));
  return { promptLines, longPrompt, capH, reelRoom, reelTier, reelH, reelVisible, promptMax, promptRows };
}
