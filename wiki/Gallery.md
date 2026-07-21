# The Gallery

A local web gallery over your whole catalog.

```bash
python pixai_gallery.py --out pixai_backup                 # http://127.0.0.1:5000
python pixai_gallery.py --out pixai_backup --port 5757
python pixai_gallery.py --out pixai_backup --host 0.0.0.0 --https   # LAN + PWA
python pixai_gallery.py --out pixai_backup --rebuild-thumbs         # regenerate thumbnails
```

…or double-click **`Serve Gallery.pyw`** for a no-console launcher. The gallery is a
viewer of `catalog.db` + your files, but can also make authenticated API calls for prune /
reconcile (see [Deleting & Sync](Deleting)).

## The header

A row of frosted glow-pill buttons, one hue per destination:

- **✦ Generate** — the dockable Generate / Edit / Video drawer, right over the grid. See
  [Generating](Generating).
- **▰ The Loom** — the storyboard for multi-clip video (acts, shots, cast, frame handoff),
  at `/loom`. Also [Generating](Generating); full manual in `docs/LOOM.md`.
- **🏆** — the Trophy Hall: achievements, points, and earnable skins. It opens as a
  maximized overlay over the gallery, not a separate page (`Esc` closes it).
- **🏅 Contests** — live PixAI contests. **📈 My Art** — how your published art is doing.
- **⚙ Panel** — the Control Panel at `/panel`: maintenance jobs with live logs and progress,
  the scheduler, server Stop/Restart, branding.
- **♡ Health** — the [collection health](Health) dashboard.

**Everything here needs a login as of v2.0.0**, including on the machine running the server.
Once signed in, **Generate**, **The Loom**, **Panel** and the balance chip are available from
any device — generating from a tablet is exactly what the login was built for.

The stricter tier is narrower than it used to be: the destructive Panel jobs (organize,
dedup-apply, rebuild-thumbnails, cancel, schedule), cloud bulk-delete, and setting the API
key or launcher icon still require a request from the server's own machine, because they
touch local files or delete from PixAI irreversibly.

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
- Per-page selector, thumbnail-size slider, saved filter presets, privacy blur.

Cards show a ▶ badge on videos and **AI** / **local** badges by source. **Videos play
right in the lightbox** (and on the detail page), so you can browse a mixed grid of
images and videos with the arrow keys without leaving the overlay.

## The lightbox & detail page

- **Click an image** → the lightbox overlay: swipe / `←` `→` to browse, `F`/Space
  slideshow, `Esc` or ✕ to close. Arrow keys **roll over page boundaries** — reach the
  end of a page and it loads the next one, continuing seamlessly. Closing leaves your
  scroll and selections intact.
- **Detail page** (via the lightbox's *Details*, or by clicking a video): full
  metadata (incl. negative + clip-skip), Copy Prompt, **Find Similar (model)** — a filter
  link to every image from the same model — View Batch, Edit Prompt. Keys: `←` `→`
  prev-next, **`Esc` / `↑` back to gallery**, `F` focus mode.
- **✧ Similar** — lookalikes by *eye* rather than by model, and a different control from
  *Find Similar (model)* above: right-click any image card, or **✧ Similar** in the
  lightbox, for the 48 closest images in your catalog. Images only. Needs the optional
  CLIP index — `pip install pixeltable`, then build it once with
  `python pixai_gallery_backup.py --rebuild-similar` (run that while the gallery isn't
  serving Similar queries — both use the same embedded database). Without the index the
  panel just tells you so; nothing else breaks.

Scroll position and your selections are preserved when you open an image and come
back (even via the browser Back button).

## Editing & curating

- **Star ratings** (0–5) per image, inline, stored in `catalog.db`.
- **Edit Prompt** — fix/annotate a single image's prompt on its detail page.
- **Find/Replace** — bulk substring replace across selected prompts.
- **Download ZIP** — bundle the selected full-res images (selection persists across pages).
- **[Collections](Collections)** and **Select mode** — see that page.
