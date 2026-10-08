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
- **⇅ Order** on a hand-picked collection's row opens its [manual order](#manual-order).

Renaming a collection keeps its manual order, deleting it drops the order with it, and merging
keeps the order of the collection you ticked first (the pictures merged in go after).

### Manual order

A **hand-picked** collection can keep your own order. Open the collection and set the **Sort** chip
to **manual order** (it is offered only while a hand-picked collection is open); **⇅ Order** then
opens the order editor — or use **⇅ Order** on the collection's row in the manager. Drag a row to
move it, or use its **▲ ▼** (with a row focused, **Alt+↑ / Alt+↓** move it too), then **Save
order**. Opening the editor changes nothing; the order is written once, when you save.

- Pictures you add to the collection later go **to the end**, oldest first.
- **Smart collections can't be ordered by hand**: their membership is worked out live.
- The order is used by **manual order** in the grid and the **Slideshow**, by **⎙ Print sheet**
  (the contact sheet prints a collection in its own order), and by **▮ Send to The Loom · as
  shots, in order**.

Under the rows the editor carries both [Loom sends](The-Loom#sending-pictures-from-the-gallery):
**▮ Send to The Loom · as shots, in order** and **▮ Send to The Loom · as cast**. Like every
collection, the order lives in your local catalog and is never sent to PixAI.

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

## On a phone

**☰ Menu → Collections** is the phone's version of Manage. **Tap** a collection to open it in the
Gallery. **Swipe a row to the left** for **Rename** and **Delete** (or tap the **⋯** at the end of the
row, for the same two buttons). **Merge…** turns on tick boxes: tick two or more hand-picked
collections and the button at the bottom says what it will do; the first one you ticked keeps the
pictures. Smart collections can't merge, and **Delete** always asks first and says how many pictures
stay. **Advanced** search has **Save as smart collection ⟳**, and smart collections are in its
**Collection** list with a ⟳. Long-press a picture to select, then **Actions** starts with the stars,
a tag box, **Keeper** and **Reject**; a note says what really changed and carries **Undo** for ten
seconds. A hand-picked collection's row has **⇅ Order**: it opens its [manual
order](#manual-order), where you **long-press a picture to drag it** (or use ▲ ▼), then **Save
order**. Nothing here deletes a picture or reaches PixAI.

## Rating keys

With the pointer over a picture, press **1–5** to rate it and **0** to clear the rating. The keys
act on, in this order: the **ticked pictures** if there are any, otherwise the picture open in the
**Lightbox** (or on the Details page), otherwise the picture **under the pointer**. A gold ★
flash confirms on each one (a still ★ if your system asks for reduced motion). They are ignored
while you type in a field, and while a panel or the command palette is up. The palette lists
this as **Rate 1–5**.

## Backing up your curation

Your ratings, collections (and their manual order), smart collections, tags, keeper/reject
marks and notes live only in `catalog.db`. **Control Panel → ⬇ Download curation (JSON)**, or
`python -m moonglade --export-curation [FILE]`, saves them as one small file keyed by
media id. If you ever rebuild the catalog from a fresh pull, put them back:

```bash
python -m moonglade --import-curation curation.json                   # dry run: what it would do
python -m moonglade --import-curation curation.json --apply           # do it
```

- **Nothing is written without `--apply`.** The dry run prints exactly what would change.
- **Fill-only by default.** A rating, mark or note the catalog already has is kept; tags and
  collections are added to what is there; a collection that already has a manual order keeps
  it. **`--curation-overwrite`** makes the file win for the pictures it lists — their rating,
  mark, note, tags and collections become the file's (a collection label it does not list is
  taken off that picture: a label, never a file) and its manual orders replace yours.
- **Pictures this catalog does not have are listed, not invented** — import again after a sync.
- **A smart collection whose name is already used** by another collection is skipped and named.
- **An import can be undone.** Before `--apply` writes anything it saves the current state as
  `curation_pre_import_<time>.json` in the library's `_moonglade/decisions/` folder; import that
  file with `--apply --curation-overwrite` to put every picture it touched back. A smart
  collection or a manual order the import created stays.
- A file that is not a curation file, is from a newer version, or holds a value the app would
  refuse (a rating of 7, an over-long note, too many tags) is turned back whole, saying why;
  nothing changes.

It holds the library's curation only. Per-account things — saved views, prompt snippets,
Toolbox presets, preferences — are tied to a sign-in and are not part of it.

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
- **▮ Send to The Loom · as cast** sends the selected images to the Loom's cast (and its cast
  library); **▮ Send to The Loom · as shots, in order** makes them a new act of image-to-video
  shots, one per picture, in the order of the collection you're looking at (its manual order,
  or oldest first) — up to 60 pictures, videos left out, and nothing rendered. See [The
  Loom](The-Loom#sending-pictures-from-the-gallery).
- **Print sheet** opens a print-ready contact sheet of the selection. On a phone it opens as a
  list, one card per picture with its thumbnail, title, model and stars; **Share** hands the
  print-ready page to your phone's share menu.
- **Find/replace in prompts** across the selection.
- **Download ZIP** of the selected full-res images.
- **Delete locally** / **Delete from PixAI** — see [Deleting & Sync](Deleting).
