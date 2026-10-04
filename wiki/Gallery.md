# The Gallery

A local web gallery over your whole catalog. Double-click **`Serve Gallery.pyw`** to start
it — a no-console launcher that opens the gallery in your browser once it is ready. The
gallery is a viewer of `catalog.db` + your files, but can also make authenticated API calls
for prune / reconcile (see [Deleting & Sync](Deleting)).

## Running it from a terminal

```bash
python moonglade_gallery.py --out pixai_backup                 # http://127.0.0.1:5000
python moonglade_gallery.py --out pixai_backup --port 5757
python moonglade_gallery.py --out pixai_backup --host 0.0.0.0 --https   # LAN + PWA
python moonglade_gallery.py --out pixai_backup --rebuild-thumbs         # regenerate thumbnails
```

Started this way the server is not managed, so the Control Panel's **↻ Restart server** is
disabled — **`Serve Gallery.pyw`** is the everyday launch. All of the server's options:

| Flag | Default | Meaning |
|---|---|---|
| `--out` | the library folder set in the Control Panel, else `pixai_backup` | the backup folder that holds `catalog.db`. Typing it always wins over the saved setting |
| `--port` | `5000` | the port to listen on — or the port saved on the Control Panel's **LAN discovery** card (it lives in `config.json` as `PORT`). Typing it always wins |
| `--host` | `127.0.0.1` | the address to listen on — or the saved one (`HOST` in `config.json`). `0.0.0.0` lets other devices on your network in. Typing it always wins |
| `--https` | off | serve over a self-signed certificate, which installing the phone app (PWA) over your LAN needs. Requires the `cryptography` package, and browsers show a one-time certificate warning |
| `--allow-port-reuse` | off | start even if something is already listening on the port. Off on purpose: Windows lets a **second** server share a port that is already serving, and requests then land on either one at random |
| `--rebuild-thumbs` | off | regenerate every thumbnail, including the ones that already exist |
| `--skip-thumbs` | off | don't build catalog thumbnails at start-up — a fast boot; missing ones show *no preview* until they are built. Thumbnails for new generations are still made |
| `--open-browser` | off | open the gallery in your browser about a second and a half after the server starts. For a terminal launch — the **`Serve Gallery`** launcher waits until the server answers and opens the browser itself |
| `-v` / `--verbose` | off | also print info-level lines (request activity, start-up steps) on the console. The log file under `logs/` in your library always has them |

## The header

The banner across the top carries the big buttons at its right, and a row of smaller destinations
sits under it. On a narrow window — an iPad, say — the rows wrap onto a second line rather than
overlapping, and the four layout marks stay visible. Along the banner:

- **?** — opens the [guide](Home#help-inside-the-app) on this page (the **?** key does the same from
  anywhere outside a text field). The first time you open the gallery, a **Welcome to the stacks**
  card offers a short tour.
- **✦ Generate** — the dockable Generate / Edit / Video drawer, right over the grid. See
  [Generating](Generating).
- **▰ The Loom** — the storyboard for multi-clip video (acts, shots, cast, frame handoff),
  at `/loom`. Also [Generating](Generating); full manual on [The Loom](The-Loom).
- **🏆 Folio** — [The Folio of Honors](Folio-of-Honors): achievements, points, and earnable
  skins. It opens as a maximized overlay over the gallery, not a separate page (`Esc`
  closes it). A goal you pin there, and your **Vigil**, can sit beside your credits as small chips.

The row under the banner holds the other destinations — **My Art**, **Publish**, **Train**,
**Import**, **Contests**, **Health**, **Panel** and **Log Out** — plus **✦ AI Tools** at the start
of it once **Mirror to PixAI** is armed, and **Activity** at one end. **Import** is drawn only
on the machine running the gallery (see below). **Publish** publishes a picture of yours on PixAI,
**Train** is [training your own LoRA](Generating#training-your-own-lora), and **Log Out** signs
out this device only (to sign out every device, see [Trust & Safety](Trust-and-Safety)).

- **Contests** — live PixAI contests, your entries and their verified results (see
  [Generating → Contests](Generating#contests---contests)).
- **My Art** — how your published art is doing; each
  piece shows its visibility (Public / Private) and an amber **Sensitive** mark when PixAI has
  flagged it, so a moderated work is no longer shown as a plain "Public". Every card carries
  its **♥ likes** and **💬 comments**, and every published one its **view count** with a small
  bar showing how it compares to your best. Along the top: how many pieces you have published,
  your **lifetime views**, total likes and total comments — and you can sort the whole library
  by **Most viewed** as easily as by Most liked. See
  [View counts](Backing-Up#view-counts-and-the-one-thing-worth-knowing-about-them) for where
  those numbers come from and why looking at them is not quite free.
  My Art reads your local catalog, and the titles, tags and like counts it lists arrive with
  **Sync published-artwork metadata** (Panel → Maintenance, or `--sync-artworks` — see
  [Backing Up](Backing-Up)). On a library where that has never run there is nothing for it to
  list, and it now says so and points at the sync instead of showing a bare "Nothing here yet."

  **When something takes off, Moonglade tells you.** After a run that reads view counts, if
  a published work's recent pace has left its own normal well behind, a notice appears in the
  corner — *"◈ <title> is taking off"* — with how many views it gained, over how long, and
  roughly how many times its usual pace that is. A work that had **no views at all** before
  says *"up from nothing"* instead, because there is no usual pace to compare against.
  The rule is deliberately quiet: it wants a real number of new views, not just a big-looking
  ratio on a work with three, and it subtracts the one view the reading itself adds. It fires
  **once per sweep** and names **one** work, counting any others rather than listing them —
  it is a note, not a feed. It is **announce-only**: nothing is published, changed, sorted or
  moved, and the page you are reading stays exactly where it is.
- **Followers and following** sit beside the credits figure in the header, and again in the
  Control Panel's **PixAI account** window. They are a reading, not a control — Moonglade
  never follows, unfollows or likes on your behalf, and it comments only when you write a
  reply yourself and press **Post publicly** (see [Comments](#comments-on-your-published-work)).
- **The gift box** (just left of the credits chip, shown once a PixAI account is linked) is your
  **PixAI inbox**. Its lavender badge is how many of PixAI's notifications you haven't read, plus
  any gift waiting to be claimed. Click it for the panel: tabs for **All · Comments · Likes ·
  Follows · Gifts · PixAI**, then **ON PIXAI NOW** (the event PixAI is running, when there is
  one), then one card per work of yours (*"♥ +12 · ❝ 2 new"*, with the newest unread comment
  quoted), then everything else — new followers folded per day, contest results, PixAI's news.
  Finished jobs never show here: Activity already tells you those (a job PixAI finished that the
  app never saw — one started on PixAI's own site while the app was closed — joins Activity marked
  **from PixAI**).
  - **Opening a row marks it read on PixAI** — one write, for exactly what that row or card
    gathers. Opening the panel, scrolling, switching tabs and new arrivals never mark anything.
    **⋯ → Mark all read** marks the tab's kinds read. With `READ_ONLY` set, rows still open and
    nothing is marked. If PixAI doesn't answer clearly, the row stays unread with a peach line
    saying so, and nothing is sent twice.
  - **It updates live.** A new notification bumps the badge as it arrives (the live mirror hears
    it), and the count is re-read when the app opens, when the window comes back to the front
    (at most every 30 seconds) and after the mirror reconnects. Only a **comment** raises a
    notice in the corner, with **Later** and **Open thread**.
  - **Gifts.** A gift PixAI sends you in a message shows with **Claim ▸**, which shows what it
    holds, which account it goes to and when it expires before a **Claim** button: one attempt,
    then the app reads the gift back and says *Claimed*, or in peach *Already claimed* /
    *This gift expired*. Credit-pack bonuses you hold say **Open on PixAI ↗**; the app redeems
    nothing. In the Control Panel's **PixAI account → Credit ledger**, event-gift rows show the
    gift icon.
  - **ON PIXAI NOW** shows PixAI's live event banners as cards; pressing one opens PixAI's page in
    a new tab. The app never checks in, claims or plays an event for you, and the banner list is
    read without your API key (PixAI only answers it that way), at most once an hour.
- **Free cards about to expire.** When any free card you hold expires within three days, the
  **CARDS** half of the credits chip gets a thin peach underline, and hovering the chip lists
  them first, one line per kind — *"5 Tsubaki.3 expire Oct 6 · in 3 days"*, *"… tomorrow"*,
  *"… today"*; never a countdown in hours. With nothing that close, there is no underline and
  the hover reads as it always did. Free cards aren't billing, so the mark is peach, not gold.
  The dates come from the same card summary the chip already reads. On a phone, where there is
  no hover, the **Menu**'s **Gift box** row shows the soonest one.
- **⚙ Panel** — the Control Panel overlay: maintenance jobs with live logs and progress,
  the `Runs itself` job list, server Stop/Restart, accounts, updates and **About**.
- **Health** — the [collection health](Health) dashboard, with the storage bars.
- **✦ AI Tools** — a browsable catalog of PixAI's one-click workflow tools. Each one is a
  card led by its own artwork, with a colour-coded chip on the art saying how much work the
  tool wants of you before you open it: **1-Click**, **Select**, **Text**, **Language** or
  **Dual**. Search it, or narrow it to Free / Tier 1. Picking a tool hands off to the
  Generate drawer, which is where it runs. **The entry only appears once _Mirror to PixAI_
  is armed** (Control Panel → Maintenance) — with the mirror off there is no entry and no
  hint, because none of these tools can dispatch. What they cost, why the mirror is
  required, and what each one does are on [Generating](Generating).

**Overlays reopen instantly.** Each of these remembers what it last showed for the rest of
the browser session: reopening one paints those numbers/rows in the first frame and
refreshes them behind, instead of showing an empty panel while it loads. Anything you do
that changes the library — publishing, importing, resolving duplicates, a finished
generation, a maintenance job — drops what is remembered, so a reopen after a change always
re-reads. See [Health → How fresh are these numbers?](Health).

**And the library stands still.** A generation finishing — an edit, an enhance, a fix, a
scene, a plain generate, an upscale, a video — never moves your view of it. The page you are
on, its address, the pictures on it and your place among them all stay exactly where they
were; the finished picture announces itself instead, with the notice in the corner and a row
in **Activity** whose thumbnail opens it. **Anything you are holding open is held still
too** — a picture full-screen, a **◈ Similar** view, an open session stack — at page 1 as
much as anywhere, so closing one still puts you back where you were. At page 1 with none of
those open the library does refresh where it stands, because that is where a new picture
arrives anyway: nothing moves, the new one simply appears at the top. And a page you asked
for is the page you get — turning to page 2 the instant something lands is your hand, and
your hand wins. If you had pictures ticked, any that are no longer in front of you
afterwards are un-ticked, so a bulk action can never reach something you cannot see;
ticking pictures across pages yourself is untouched.

**Everything here needs a login as of v2.0.0**, including on the machine running the server.
Once signed in, **Generate**, **The Loom**, **Panel** and the balance chip are available from
any device — generating from a tablet is exactly what the login was built for.

The stricter tier is narrower than it used to be: the destructive Panel jobs (organize,
dedup-apply, rebuild-thumbnails, cancel, schedule), cloud bulk-delete, and setting the API
key or launcher icon still require a request from the server's own machine, because they
touch local files or delete from PixAI irreversibly.

Those controls are simply **not drawn** for a browser that reached the gallery across the
network: **↑ Import**, **Delete from PixAI**, **Set launcher icon** and the destructive Panel
jobs are missing, not broken. It's easy to leave a tab open on `http://<your-pc>:5000` and
forget you're not on `localhost`, so if a button you expect is not there, check the address
bar first. Open the gallery from the serving machine's own `localhost` address and the
restriction lifts. (Earlier builds showed a **🌐 LAN session** chip naming what was hidden;
the current shell does not.)

## Help, About and the first-run guide

The round **?** in the header (or the **?** key) opens the Guide: these pages, inside the app.
How it works, **About** and the first-run guide are described on
[Help inside the app](Home#help-inside-the-app).

## The command palette

**Ctrl K** (**⌘ K** on a Mac) opens the command palette over any screen of the gallery: type a few
letters and press **Enter** on the row you want. It lists **Go to** (the Library, the Loom, the
Control Panel, Contests, My Art, Health, the Folio, and every collection — smart ones marked **⟳**),
**Layout** (masonry, grid, hero, timeline, and **Toggle Stack sessions**), **Do** (**New generation**,
**Jump to Search**, **Sync now**, **Manage collections**, **Rate 1–5**, **Browse recipes**, and **Claim**
while credits are waiting), **On this image** while a picture is open or focused (**Again — new seed**,
Remix, Send to Video, Find similar, Edit, Edit with Tsubaki, Open details, Copy id, Publish) and **Help**
(**Open the guide**, **Show keyboard shortcuts**, and — as you type — any page or heading of the
[guide](Home#help-inside-the-app)). A few rows show their own keys: **N** starts a generation, **/**
jumps to the search field, **R** re-runs the open picture with a new seed, and **G** then **L**, **S** or
**C** goes to the Library, the Loom or the Control Panel. The keys work with the palette closed, but not while you
are typing in a field.

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
- **Collection** — the chip opens the list of your [collections](Collections), hand-picked and
  smart, with Manage.
- **Sort** — newest/oldest, rating, aesthetic, likes, resolution.
- Per-page selector, thumbnail-size slider, saved filter presets, privacy blur. Saved
  views are stored server-side, so a view saved at the desktop is in the tablet's
  dropdown too. They belong to **your account**, not to the install — if someone else
  has a login here, your saved searches are yours and theirs are theirs. (Your skin
  choice, being purely cosmetic, is still install-wide.)
- **Layout** — four small marks sit beside the SIZE slider in the header: **▤** masonry,
  **▦** grid, **▣** hero, **≡** timeline. Hover one and it names itself. The layout you pick
  is remembered the same way your thumbnail size is. **A phone has no masonry / grid / hero /
  timeline switcher** — it lays the library out in two staggered columns — but it has its own
  two-way toggle, **▦ Grid | ▭ Feed**, in the pill row (see "The phone's reading feed" below).
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
keeper  reject                   your own mark on a picture (see Collections & curation)
tag:pose-study                   your own tag; tag: also still reads PixAI's published tags
note:"good hands"                words in your own note
★4+                              four stars or more (★4 means the same)
keeper -reject  -tag:draft       a leading - leaves matches out, for any of the above
ar:tall  ar:wide  ar:square      by shape: tall is 9:16 or taller, wide is 16:9 or wider
ar:portrait  ar:landscape        taller than wide / wider than tall
ar:3:2  ar:9:16  ar:1.91:1       a shape, within 3% of that ratio
ar:>2  ar:<0.5                   wider than 2:1 / narrower than 1:2 (width divided by height)
type:image  type:video  type:loom   which kind: the Loom's own renders are their own kind
```

`tag:` reads two stores: PixAI's published art tags (a substring, as it always did) and your own
personal tags (a whole tag). `art_tags:` keeps the PixAI-only reading. Your marks, tags and notes
live in your local catalog and are never sent to PixAI.

**Searching by shape.** `ar:` reads each picture's width and height, so it finds *every* matching
picture in the library, not just the ones on the page you are looking at. A picture with no size
on record (some old imports) matches no shape, and turns up under `-ar:tall` since it is not
known to be tall. Type `ar:` in the search field and it suggests the values; the ▾ **Advanced**
panel has an **Aspect** field that does the same without typing, and each card names its own
shape (`3:2`) in the row that appears when you hover it. A value the search doesn't understand
(`ar:banana`) is said out loud under the field instead of quietly finding nothing.

**Operators.** Click into the search field and its suggestion list opens with an **Operators**
group (`ar:tall`, `ar:wide`, `ar:square`, `★4+`, `keeper`, `-reject`, `type:video`, `type:loom`),
each with a word on what it does. Pick one to add it to the search and run it; pick it again (it
says *in your search*) to take it out. While you type a word, the list keeps only the operators it
begins (`ke` offers `keeper`). A shape replaces any other shape, since a picture only has one.

**`type:`** splits the library three ways with no overlap: `type:image`, `type:video`, and
`type:loom` for pictures and clips [The Loom](The-Loom) made (a shot's result, or a re-roll it
kept; footage you imported into a shot is not the Loom's). This is what the storage bars in
[Collection Health](Health) open when you click a segment.

Text operators match substrings, case-insensitively, and take the same `*` / `?`
wildcards as free text (`model:eth*mix`). An unrecognized key (or a malformed value
like `width:tall`) isn't an error — the whole token is simply searched as prompt text,
the way search engines behave. Operator searches work everywhere the search box does:
the grid, the pickers, saved views, and the filtered CSV export.

Cards show a ▶ badge on videos and **AI** / **local** badges by source. A picture PixAI no
longer has wears **ARCHIVE** in that same corner instead (hover it: *"Deleted on PixAI. This is
the only copy."*) — its task has left your PixAI history as of the last check, or PixAI dropped
that one image, so your library holds the only copy anywhere. Its detail page says the same
under **More details**. **Videos play
right in the lightbox** (and on the detail page), so you can browse a mixed grid of
images and videos with the arrow keys without leaving the overlay.

### Session stacks

The filter bar's **Stack sessions** chip folds a re-roll session — a night of dialling in
the same idea — or a lone batch's siblings into one stacked card, so the library reads as
the sessions you had rather than every frame they produced.

**Opening a stack is a window over the gallery, not a trip out of it.** The library
underneath keeps its search, its filters, its page and your place on it, and **Esc** closes
the window straight back — there is nothing to undo. Inside, the session's runs are listed
down the left with their own picture counts, headed by **All runs**; click one to see just
it. Chips for portrait, video and rated sit under them and narrow whichever run you have
picked rather than replacing it. The header sorts by **run №** or by **newest**, and every
picture is stamped with the run it came from (`r2·3` — run two, third picture), so under
either sort you can read which run a picture belongs to. An open stack has its own address,
so you can bookmark one, and the browser's Back button closes it.

## The lightbox & detail page

- **Click an image** → the lightbox overlay: swipe / `←` `→` to browse, `F`/Space
  slideshow, `Esc` or ✕ to close. Arrow keys **roll over page boundaries** — reach the
  end of a page and it loads the next one, continuing seamlessly. Its top bar says where
  the picture sits among everything your search and filters match (*101 OF 3,240*), not
  just its place on the page. Closing leaves your
  scroll and selections intact. On a still picture, **✎ Edit** (or `E`) opens a **Describe
  your edits…** bar under the picture that sends a Tsubaki.3 edit of it, priced before you send;
  ✎ Edit again or `Esc` closes it, and its **More options in the Edit drawer ↗** opens the Edit
  tab — see [Generating](Generating#tsubaki3-context-images-and-image-prompts).
- **Detail page** (via the lightbox's *Details*, or by clicking a video): full
  metadata (incl. negative + clip-skip), Copy Prompt, **Filter by model** — a filter
  link to every image from the same model — View Batch, Edit Prompt. Keys: `←` `→`
  prev-next, **`Esc` / `↑` back to gallery**, `F` focus mode. The header says where the
  picture sits among everything your search and filters match (*14 of 3,240*), not just
  among the page on screen, so it agrees with how far Prev and Next will carry you.

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
  Similar. **The mark means only this now**: the two places it used to sit as decoration — a
  model's use count in the picker, the *USER LORA* badge — wear their own drawn icons since
  2026-09-05, so seeing ◈ anywhere always means lookalikes.

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

**On a phone, the curation tools are there too.** **Advanced** has an **Aspect** row of chips (Square,
Portrait, Landscape, Tall, Wide) after Min rating, its **Collection** list marks smart collections
with ⟳, and **Save as smart collection ⟳** saves what the sheet shows. Long-press a picture to start
selecting; **Actions** then opens with the stars, a tag box and **Keeper** / **Reject** on top, with
the same honest count and 10-second **Undo** as the desktop. In the full-screen viewer a **✓** and a
**✕** sit at the right of the model line, and the stars are big enough to hit: tap the star you have
to take the rating off. **Details** carries the same **Your layer** card as the desktop. See
[Collections](Collections).

**On a phone, three more things about where you are.** Each of the three tabs —
**Gallery**, **Create**, **Control** — keeps its own scroll position, so reading deep into
your library and stepping over to the composer no longer drops you into the middle of it,
and the library is still deep when you come back. Turning the page with **‹ Prev** or
**Next ›** starts you at the top of the page you asked for, with the search box and the
media pills back on screen. And while a sheet is up — **Sort**, **Advanced Search**,
**Actions** — the library behind the dim is held still, and is exactly where you left it
when the sheet goes. See the [FAQ](FAQ) for what the phone's Back gesture closes.

### Comments on your published work

A picture you have published on PixAI shows its **COMMENTS** in Details, on the desktop and the
phone, where the ♥ / 💬 count used to carry them. They are read live from PixAI when you scroll
to them — never when Details merely opens — newest first, 50 at a time with **Load older** at
the end, and kept in memory for five minutes. They are never saved to your library, a file or a
log: they are other people's words.

- Each comment shows with its replies folded under **N replies ▸**; a chain you've replied in
  opens by itself, and so does the one you reached from a quote in the gift box. Your own
  comments wear a **you** badge. Reactions show as a count and stickers as small pictures —
  there is no like, react or report button. A comment PixAI has flagged is hidden, and one line
  at the end says how many.
- **Reply** opens a box under that comment with a counter (PixAI's limit is 4,095 characters;
  past it the counter turns peach and Send says how far over you are). **Send** asks first —
  a notice that names your PixAI name, the person and the work and quotes your text in full
  (on a phone, a sheet with two big buttons): **Back** or **Post publicly**. Only Post publicly
  sends it, once. The app then reads the thread back and says **Posted · found in the thread**,
  or — if PixAI's answer was unclear and the reply isn't there — tells you to check on PixAI,
  and keeps Send off until you change the text, so the same words are never posted twice.
  PixAI's refusals (email not verified, blocked, not eligible, restricted, too many) are shown
  in plain words.
- PixAI has no edit, so a reply you've just posted offers **Delete my reply** while the thread
  is open; it asks first (*This can't be undone*), sends once and reads back.
- With `READ_ONLY` set, the reply box shows, greyed, with the reason, and nothing is sent.

### The phone's reading feed, the new-since line, and pull to refresh

**▦ Grid | ▭ Feed.** The toggle sits in the pill row, beside **Sort**. **Feed** shows one picture per
row, edge to edge, at its own shape, with its prompt and stars over the bottom edge; tapping a
picture opens the viewer, and long-press still starts selecting. Your choice is remembered **on that
phone** (in the browser, like the popup blur), not on your account.

**"N new since 21:40".** When you leave the Gallery tab — or close or hide the page — the phone
remembers the newest picture it showed you and the time. Next time, a lavender line reading **N new
since HH:MM** marks where the new pictures end. There is no line when nothing is new, and none on a
filtered view, a later page or the lookalikes view; those never change what the phone remembers. After
one screen of scrolling a **↑ Newest** button appears (with the count) and jumps back to the top. It
steps aside at the foot of the page, while the **‹ Prev · Page … · Next ›** row is on screen, so it never
covers the pager.

**Pull to refresh.** At the very top of the Gallery, pull down: the moon fills as you pull (it is a real
fraction of the distance to the release line — a full moon means "let go now"). Release past the line
and the phone runs the same **Sync now** the Control tab has, spins the moon while it works, then
re-reads the page you are on, so anything new lands above the line. Letting go short of the line does
nothing. A pull is something you asked for, so it works even with **Data saver** on. **My Art** has
the same pull; there it just re-reads your list and totals from this library (the published-artwork sync
is the Control tab's, because it counts a view on each of your works).

**In the phone's full-screen viewer:** under the picture sits the **placard** — the catalog number and
date (*ACC. 2026·0918·4401 · 18 SEP*; the number is the last four characters of the picture's id) and
the other pictures from the same batch. Tap one to swap to it in place; the current one is ringed. A
picture on its own says *single image*. **▶ To Video** and, on a picture's record, **↻ Remix** and
**▶ Send to Video** all only open the **Create** tab already filled in — Remix fills the Image form with
the recorded prompt (or, for a picture made by a Generate run with variables, that run's template);
Send to Video puts the picture in as the start frame — and **nothing is sent** until you press
Generate. The viewer's buttons (Edit, To Video, Similar, Upscale, Details and the rest) wrap onto two or
three lines when the phone is upright, so every one is on screen without a sideways swipe.

**Where you are in the library.** A picture's record and the full-screen viewer both say where the
picture sits among everything your search and filters match (*14 of 3,240*), not just among the page
on screen, so the number agrees with how far **‹** and **›** will carry you. A picture your current
filter does not contain shows no number on its record.

**View batch** on a picture's record shows the other pictures made in the same generation. It
appears for any picture that came from a generation, not only ones filed in an old batch folder.
To get your whole library back, press **Clear** in **Advanced search**.

### The phone turned sideways

Hold the phone in **landscape** and it is still the phone app (it no longer falls over to the desktop
one), laid out for a wide, short screen:

- **The tab bar becomes a slim rail on the left** — Gallery, Create, Control as icons, the current one
  tinted. The banner at the top folds to a single bar (name, your counts, the **◐ Saver** chip when Data
  saver is on, credits and the icon buttons), and the search bar scrolls away with the list so the
  pictures get the height.
- **The gallery shows 4 columns** (3 on a screen under 700 px wide), each row lined up. **Feed** stays one
  picture per row, but no picture is drawn taller than the screen. The **N new since** line, **↑ Newest**
  and pull to refresh work exactly as upright.
- **In the viewer the picture fits the height** and the actions — Edit, To Video, Similar, Upscale, Enter
  contest, Details, Slideshow — are a column down the right edge, ahead of the placard, the prompt and the
  film strip, which scroll beneath them.
- **Sheets open from the right edge as side panels**, no wider than 380 px: Sort, Advanced, Actions, the
  model picker, Upscale and the rest. On a picture's record, the picture sits on the left and the record
  is a panel on the right that scrolls as one: **Remix**, **Send to Video** and the record's other
  buttons sit after the details and scroll with them (upright they stay pinned at the foot).
- **Turning the phone keeps your place**: the picture at the top of the list is still at the top after the
  columns re-flow, and a picture you have open stays open. Turned back upright, the gallery is two columns
  again and never scrolls sideways. A notch or the home bar on either side is left clear.

A tablet turned sideways is not a phone here and keeps the desktop layout. **The Loom** still opens its
wide board when the phone is already in landscape and its board-and-reel view when upright; nothing asks
you to turn the phone.

## Editing & curating

- **Star ratings** (0–5) per image, inline, stored in `catalog.db`. **A rating that doesn't
  reach the server now says so** rather than rolling back without a word: in the grid you get
  a "Rating not saved" notice with the reason; on the detail page, which carries no notices,
  the stars themselves turn red for a few seconds and the reason hangs off their tooltip.
  Either way the stars go back to what the catalog really holds. That mattered — a silent
  failure left the widget privately believing you'd set 4 stars while the display still read
  0, so clicking the same star again to retry was read as "you already rated it 4, clear
  it" and submitted a 0. Two clicks through one dropped connection unrated the image.
- **Rating keys** — hover a picture (or open it, or tick several) and press **1–5** to rate it,
  **0** to clear; a gold ★ flash confirms. See [Collections](Collections).
- **Keeper / Reject, tags and notes** — your own layer over each picture, local to your catalog;
  the Details page edits it. See [Collections](Collections).
- **Edit Prompt** — fix/annotate a single image's prompt on its detail page.
- **Find/Replace** — bulk substring replace across selected prompts.
- **Download ZIP** — bundle the selected full-res images (selection persists across pages).
- **[Collections](Collections)** and **Select mode** — see that page.

### Saved prompt snippets

The **Snippets** button beside a prompt box — the one with the quote-marks icon — stores
fragments you reuse. Deleting one used
to fire the moment you *pressed* the × — which sits a few pixels from Insert, in a popover
only 220–340px wide — with nothing to catch a slip and nothing to undo it. Now it fires on
**release**, so sliding off the button cancels the way it does everywhere else, and the
deletion leaves an **Undo** strip pinned to the top of the menu that puts the snippet
straight back. No confirmation dialog, deliberately: this menu exists to be used quickly, and
an undo taxes only the mistake, where a prompt would tax every delete you meant.

### Sending a selection onward

Selections persist across pages, which is the point of them — and it's also what made
**Actions → ▮ Send to The Loom · as cast** miss a video. The cast is images only, but the check
asked the *page you were looking at*, so a video ticked on page 2 and sent from page 1 was
invisible to it and went through. The kinds are now remembered alongside the selection
itself, so the exclusion holds wherever a video was picked.
