import React from "react";

/* The gallery layout switcher: a compact glyph strip (masonry / grid / hero /
   timeline). Lifted out of the SeparatorBar's SIZE group and up into the top
   LibraryBar beside Actions (2026-09-09, owner) -- the Hero cell (2026-09-05)
   made the four-cell strip crowd the separator row and stack oddly against the
   SIZE pill, so it moves to where there is room. Same glyphs, same
   .mgx-lay/.mgx-laycell marks and CSS as before; only its home changed.
   Persisted as mg_gallery_layout (App state, localStorage-backed). Hidden below
   the desktop breakpoint in shell.css -- mobile is masonry-only, so there is
   nothing to switch between there.

   The command palette (App.jsx) keeps its own copy of these modes/glyphs on
   purpose -- it is not driven off this constant, so the two are edited together
   when the mark set changes (last agreed masonry ▤ · grid ▦ · hero ▣ · timeline ≡). */
export const LAYOUT_CELLS = [
  ["masonry", "▤", "Masonry — aspect-true, no crop"],
  ["grid", "▦", "Grid — 4:3, smart-cropped"],
  ["hero", "▣", "Hero — a large feature, the rest in a grid"],
  ["timeline", "≡", "Timeline — date-banded, newest first"],
];

export default function LayoutStrip({ layout, setLayout }) {
  if (!setLayout) return null;
  return (
    <div className="mgx-lay" role="group" aria-label="Gallery layout">
      {LAYOUT_CELLS.map(([key, glyph, title]) => (
        <button
          key={key}
          type="button"
          className={"mgx-laycell" + (layout === key ? " on" : "")}
          title={title}
          aria-label={title}
          aria-pressed={layout === key}
          onClick={() => setLayout(key)}
        >
          <span aria-hidden="true">{glyph}</span>
        </button>
      ))}
    </div>
  );
}
