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
- Open the **Collection** chip in the filter tray (⚲ Filters) for the list: every collection
  with how many pictures it holds, and **Manage**. Pick one to browse it.
- The detail page lists an image's collections.
- Matching is exact (so "Elf" won't match "Elf Portraits").

Works on **images and videos** alike. Collections are **local**: they live in your catalog and
are never sent to PixAI.

### Smart collections ⟳

A **smart collection** is a saved *search*, not a list of pictures. Type a search (`★4+ keeper`,
`tag:pose-study -reject`, `model:tsubaki night*`) and press Enter; a row under the library bar
offers **Save as smart collection ⟳**. What is stored is the search itself, so the collection is
worked out again every time you open it: rate a picture, mark it a keeper or tag it and it moves
in or out on its own. **⟳ Refresh** runs it again while it is open.

- A smart collection is marked **⟳** in the list, and the row above the grid shows its search.
- You can't add pictures to one by hand — **+ collection** lists hand-picked collections only.
  Pictures leave one by no longer matching.
- To change one, open it and press **Edit query**: the search goes into the search field, you
  change it, and **Save over** replaces the saved search (or **Save as new** keeps both).
- The gallery's **saved views** (the ▾ on the search field) stay what they always were: quick
  filters, not collections.

### The collections manager

**Manage** in the collection list opens one place to look after them all:

- **Rename** by editing the name in place. Names are trimmed and must be unique, without regard
  to case.
- **Merge** two or more hand-picked collections: tick them, and everything goes into the *first*
  one you ticked — each picture once, however many it was in — and the others are removed.
  Smart collections can't merge (their tick box says why).
- **Delete** always asks first, and the question says how many pictures stay. **Deleting a
  collection never deletes a picture**, and neither does merging: a collection is only a label.

## Your own layer: keepers, tags and notes

Three things only you say about a picture, kept in your local catalog and **never sent to PixAI**:

- **Keeper / Reject** — one mark at a time (choosing one clears the other). A keeper wears a small
  green ✓ on its card, a reject wears a ✕ and dims. Rejects **stay visible**: hiding them is a
  search, `-reject`, never automatic.
- **Tags** — your own, lowercase and hyphenated (`Pose Study` becomes `pose-study`), up to 32
  characters each and 32 on a picture.
- **A note** — up to 500 characters.

Open a picture's **Details** and the **Your layer** card edits all three. Search reads them:
`keeper`, `reject`, `tag:pose-study`, `note:"good hands"`, with `-` in front to leave one out
(see [search operators](Gallery)).

## Bulk curation, and Undo

Tick pictures and a bar appears over the grid: **★ 1–5**, **+ Tag**, **✓ Keeper**, **✕ Reject**
and **+ collection**, each applied to every ticked picture at once. A note at the bottom of
the screen says what changed — and it counts **only the pictures that really changed**, so
rating a picture that already has that rating is not counted. For ten seconds it carries **Undo**,
which puts *each picture back to the values it had*, not one value for all.

## Rating keys

With the pointer over a picture, press **1–5** to rate it and **0** to clear the rating. The keys
act on, in this order: the **ticked pictures** if there are any, otherwise the picture open in the
**Lightbox** (or on the Details page), otherwise the picture **under the pointer**. A gold ★
flash confirms on each one (a still ★ if your system asks for reduced motion). They are ignored
while you type in a field, and while a panel or the command palette is up. The palette lists
this as **Rate 1–5**.

## Why collections instead of folders?
Physical folders break when you re-run Organize (which renames/moves files into
`YYYY-MM/`). Collections live in the catalog and are keyed by `media_id`, so they
never break — keep your month folders tidy for Explorer browsing *and* organize
images into cross-cutting sets (Favorites, a character, a project) at the same time.

## Other bulk actions
Selecting anything reveals an **Actions ▾** button in the bulk bar — it opens a menu
holding everything below, rather than a row of separate buttons:
- **+ Add to collection**.
- **− Remove from «collection»** — only appears while a Collection filter is active
  (removing from "which collection?" has no answer otherwise); takes the selection out
  of that one collection. A `catalog.db` label change only — no files are touched.
- **Send to Video** loads the selection into the Generate drawer's Video tab as
  reference images (images only, up to 6) — see [Generating](Generating).
- **Send to The Loom (cast)** sends the selected images to the Loom's cast.
- **Print sheet** opens a print-ready contact sheet of the selection.
- **Find/replace in prompts** across the selection.
- **Download ZIP** of the selected full-res images.
- **Delete locally** / **Delete from PixAI** — see [Deleting & Sync](Deleting).
