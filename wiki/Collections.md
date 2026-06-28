# Collections & curation

## Select mode (fast multi-select)

Toggle the **Select** button in the gallery's bulk bar to enter selection mode:

- **Tap/click** an image to toggle it.
- **Drag across images** to *paint* a selection (mouse or touch/stylus) — great on a
  tablet.
- While Select mode is on, **tapping never opens the lightbox**, so there are no
  accidental opens. Drag on the gaps between cards to scroll; toggle Select off for
  normal browsing.

You can also **Select All (page)** and **Clear**. The selection persists across pages
and survives the browser Back button.

## Collections

Select images/videos → **+ Add to Collection** → name it. This groups them into a
named collection **without moving any files** — it's stored in `catalog.db`, so it
**survives [Organize](Backing-Up)** (unlike physical sub-folders).

- An item can be in **several** collections.
- Filter by them via the **Collection** dropdown in the filter bar.
- The detail page lists an image's collections.
- Matching is exact (so "Elf" won't match "Elf Portraits").

Works on **images and videos** alike.

## Why collections instead of folders?
Physical folders break when you re-run Organize (which renames/moves files into
`YYYY-MM/`). Collections live in the catalog and are keyed by `media_id`, so they
never break — keep your month folders tidy for Explorer browsing *and* organize
images into cross-cutting sets (Favorites, a character, a project) at the same time.

## Other bulk actions
- **Find/Replace** prompts across the selection.
- **Download ZIP** of the selected full-res images.
- **Delete (local)** / **Delete from PixAI** — see [Deleting & Sync](Deleting).
