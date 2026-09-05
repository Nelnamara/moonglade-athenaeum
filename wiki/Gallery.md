# The Gallery

A local web gallery over your whole catalog.

```bash
python moonglade_gallery.py --out pixai_backup                 # http://127.0.0.1:5000
python moonglade_gallery.py --out pixai_backup --port 5757
python moonglade_gallery.py --out pixai_backup --host 0.0.0.0 --https   # LAN + PWA
python moonglade_gallery.py --out pixai_backup --rebuild-thumbs         # regenerate thumbnails
```

…or double-click **`Serve Gallery.pyw`** for a no-console launcher. The gallery is a
viewer of `catalog.db` + your files, but can also make authenticated API calls for prune /
reconcile (see [Deleting & Sync](Deleting)).

## The header

A row of frosted glow-pill buttons, one hue per destination:

- **✦ Generate** — the dockable Generate / Edit / Video drawer, right over the grid. See
  [Generating](Generating).
- **▰ The Loom** — the storyboard for multi-clip video (acts, shots, cast, frame handoff),
  at `/loom`. Also [Generating](Generating); full manual on [The Loom](The-Loom).
- **🏆** — [The Folio of Honors](Folio-of-Honors): achievements, points, and earnable
  skins. It opens as a maximized overlay over the gallery, not a separate page (`Esc`
  closes it).
- **🏅 Contests** — live PixAI contests. **📈 My Art** — how your published art is doing; each
  piece shows its visibility (Public / Private) and an amber **Sensitive** mark when PixAI has
  flagged it, so a moderated work is no longer shown as a plain "Public".
- **⚙ Panel** — the Control Panel overlay: maintenance jobs with live logs and progress,
  the scheduler, server Stop/Restart, branding.
- **♡ Health** — the [collection health](Health) dashboard.

**Overlays reopen instantly.** Each of these remembers what it last showed for the rest of
the browser session: reopening one paints those numbers/rows in the first frame and
refreshes them behind, instead of showing an empty panel while it loads. Anything you do
that changes the library — publishing, importing, resolving duplicates, a finished
generation, a maintenance job — drops what is remembered, so a reopen after a change always
re-reads. See [Health → How fresh are these numbers?](Health).

**Everything here needs a login as of v2.0.0**, including on the machine running the server.
Once signed in, **Generate**, **The Loom**, **Panel** and the balance chip are available from
any device — generating from a tablet is exactly what the login was built for.

The stricter tier is narrower than it used to be: the destructive Panel jobs (organize,
dedup-apply, rebuild-thumbnails, cancel, schedule), cloud bulk-delete, and setting the API
key or launcher icon still require a request from the server's own machine, because they
touch local files or delete from PixAI irreversibly.

Those controls are simply **not drawn** for a browser that reached the gallery across the
network, so the header tells you when you're that browser: a small dashed
**🌐 LAN session · local-only tools hidden** chip appears beside the nav, and its tooltip
lists exactly what's missing (**↑ Import**, **Delete from PixAI**, **Set launcher icon**,
the destructive Panel jobs). It's easy to leave a tab open on `http://<your-pc>:5000` and
forget you're not on `localhost` — the chip is there so a missing button reads as a tier
rather than a bug. Open the gallery from the serving machine's own `localhost` address and
the chip disappears along with the restriction.

## Browsing & filtering

The filter bar:
- **Prompt / task / media id** — wildcard (`night*`, `a?c`) and multi-word AND search over the
  prompt text, plus a substring match on task id or media id — paste an id from PixAI's site (or
  from `--dump-params` output) to jump straight to that generation.
- **Model / Batch** — searchable dropdowns.
- **From / To** — year + month pickers.
- **Min rating**, **Tag / contest**, **LoRA**, **Published only**.
- **Media** — All / Images / Videos.
- **Source** — All / PixAI history / Generated / Imported / **Deleted on PixAI**.
- **Collection** — filter to a named [collection](Collections).
- **Sort** — newest/oldest, rating, aesthetic, likes, resolution.
- Per-page selector, thumbnail-size slider, saved filter presets, privacy blur. Saved
  views are stored server-side, so a view saved at the desktop is in the tablet's
  dropdown too. They belong to **your account**, not to the install — if someone else
  has a login here, your saved searches are yours and theirs are theirs. (Your skin
  choice, being purely cosmetic, is still install-wide.)
- When any filter is active, the active-filter bar shows an **⬇ Export this view (CSV)**
  link that downloads exactly the rows you're looking at. (The Control Panel's **Download
  catalog (CSV)** is the whole-library dump.) **It's a complete answer even mid-sync.** It
  used to count the matching rows and then, a moment later, ask for that many — so a
  "Sync now" job inserting rows in between meant the file shipped the old count out of the
  new, larger set, with nothing in the CSV admitting it was short. It's now one query, which
  has nothing to disagree with.

### Search operators

The search box also understands `key:value` tokens, so every useful catalog column is
reachable without a dedicated dropdown. Mix them freely with plain words — everything
is ANDed:

```
model:tsubaki night elf          images from a Tsubaki model whose prompt has both words
model:"Ether Real"               quote values that contain spaces
negative:blurry                  search the negative prompt
seed:123456789                   exact seed (paste it straight from a detail page)
rating:>=3 aes:>6                three-plus stars AND aesthetic score above 6
width:>1000 height:>1000         big renders only (likes: steps: cfg: duration: work too)
created:2026-07                  July 2026; created:2026 for the year, created:2026-07-04 for a day
created:<2026                    strictly before 2026 (>, >=, <= also work)
video:1 nsfw:0                   videos, SFW only (published: too; 1/0, true/false, yes/no)
collection:"Elf Portraits"       exact collection name, same as the dropdown
source:api                       online / api / local / deleted, same as the dropdown
tag:elf lora:detail sampler:euler title:grove batch:B1 filename:mp4
task:900000001  media:100000003  exact ids (a bare long number still works as before)
```

Text operators match substrings, case-insensitively, and take the same `*` / `?`
wildcards as free text (`model:eth*mix`). An unrecognized key (or a malformed value
like `width:tall`) isn't an error — the whole token is simply searched as prompt text,
the way search engines behave. Operator searches work everywhere the search box does:
the grid, the pickers, saved views, and the filtered CSV export.

Cards show a ▶ badge on videos and **AI** / **local** badges by source. **Videos play
right in the lightbox** (and on the detail page), so you can browse a mixed grid of
images and videos with the arrow keys without leaving the overlay.

## The lightbox & detail page

- **Click an image** → the lightbox overlay: swipe / `←` `→` to browse, `F`/Space
  slideshow, `Esc` or ✕ to close. Arrow keys **roll over page boundaries** — reach the
  end of a page and it loads the next one, continuing seamlessly. Closing leaves your
  scroll and selections intact.
- **Detail page** (via the lightbox's *Details*, or by clicking a video): full
  metadata (incl. negative + clip-skip), Copy Prompt, **Filter by model** — a filter
  link to every image from the same model — View Batch, Edit Prompt. Keys: `←` `→`
  prev-next, **`Esc` / `↑` back to gallery**, `F` focus mode.

  The facts list shows **the whole generation record**, not just the recipe: alongside
  prompt, seed, steps, sampler, CFG, model and LoRAs you'll see the inference profile
  (quality mode), quality-tag prefix, prompt-helper state, control nets, priority, how
  many seconds the render took and on which backend, the run's started / ended
  timestamps, retry count, and the moderation result; a video adds its mode and model.
  A row is only shown when the run actually recorded it. **A `—` is honest, not a
  hole:** some models (Tsubaki.2 and other AuraFlow models) run on baked-in defaults and
  don't report a sampler or CFG — their step count is filled from the model's own preset,
  and the fields the model genuinely doesn't have stay blank. If your *older* pictures
  show fewer of these rows, run the one-time
  `--backfill-full-meta --with-surface` pass described in [Backing up](Backing-Up).
  **LINEAGE** shows where a derived picture came from — its source image and whether it
  was an edit, an upscale, or turned into a video.
- **◈ Similar** — lookalikes by *eye* rather than by model, and a different control from
  *Filter by model* above. **In the gallery on a computer, the ◈ mark is the door**: hover a
  card in the grid and press the ◈ in its corner, right-click a card and pick *Find similar*,
  press **◈ Similar** in the lightbox, or press **◈ Similar** on the detail page's SIMILAR
  strip. All four do the same thing, and nowhere in the library does ◈ open a *second* kind of
  Similar. (The mark does appear as a small decoration elsewhere in the app — beside a model's
  use count in the picker, on a *USER LORA* badge — where it is punctuation, not a door.)

  What you get is a **state on your library, not a popup**: a dismissible **◈ Similar to
  [thumbnail]** token appears in the search bar with the match count beside it, and the 48
  closest images take the grid's place underneath. **✕ on the token — or `Esc` — puts your
  library back exactly as it was**, same search, same filters, same page, because none of
  them were ever changed. Any result's own ◈ re-points the view at that picture, so you can
  walk from one lookalike to the next.

  **On a phone it works the same way, with the phone's own door.** Press **◈ Similar** on the
  big viewer's button row and the lookalikes fill the library's own space back on the Gallery
  tab, under the same **◈ Similar to [thumbnail]** token — in the search bar, on its own line
  under the field so the field is still usable, with the match count beside it. **✕ on the
  token, or the phone's Back gesture, puts your library back exactly as it was**, same search,
  same filters, same page, same place on the page. The picture screen's own **◈ SIMILAR** row
  and the **see all** sheet behind it read the same mark; that sheet stays a sheet, because
  it is the phone's way of showing you the rest of something you are already looking at.
  *Filter by model* is called that on the phone too.

  Images only. Needs the optional CLIP index — `pip install pixeltable`, then build it once
  with `python moonglade_backup.py --rebuild-similar` (run that while the gallery isn't
  serving Similar queries — both use the same embedded database). To top up an existing index with only the images it lacks rather than rebuilding from scratch, use `--sync-similar` (the incremental counterpart). Without the index the
  view just tells you so; nothing else breaks.

Scroll position and your selections are preserved when you open an image and come
back (even via the browser Back button).

## Editing & curating

- **Star ratings** (0–5) per image, inline, stored in `catalog.db`. **A rating that doesn't
  reach the server now says so** rather than rolling back without a word: in the grid you get
  a "Rating not saved" notice with the reason; on the detail page, which carries no notices,
  the stars themselves turn red for a few seconds and the reason hangs off their tooltip.
  Either way the stars go back to what the catalog really holds. That mattered — a silent
  failure left the widget privately believing you'd set 4 stars while the display still read
  0, so clicking the same star again to retry was read as "you already rated it 4, clear
  it" and submitted a 0. Two clicks through one dropped connection unrated the image.
- **Edit Prompt** — fix/annotate a single image's prompt on its detail page.
- **Find/Replace** — bulk substring replace across selected prompts.
- **Download ZIP** — bundle the selected full-res images (selection persists across pages).
- **[Collections](Collections)** and **Select mode** — see that page.

### Saved prompt snippets

The **★ Snippets** button beside a prompt box stores fragments you reuse. Deleting one used
to fire the moment you *pressed* the × — which sits a few pixels from Insert, in a popover
only 220–340px wide — with nothing to catch a slip and nothing to undo it. Now it fires on
**release**, so sliding off the button cancels the way it does everywhere else, and the
deletion leaves an **Undo** strip pinned to the top of the menu that puts the snippet
straight back. No confirmation dialog, deliberately: this menu exists to be used quickly, and
an undo taxes only the mistake, where a prompt would tax every delete you meant.

### Sending a selection onward

Selections persist across pages, which is the point of them — and it's also what made
**Actions → ▰ Send to The Loom (cast)** miss a video. The cast is images only, but the check
asked the *page you were looking at*, so a video ticked on page 2 and sent from page 1 was
invisible to it and went through. The kinds are now remembered alongside the selection
itself, so the exclusion holds wherever a video was picked.
