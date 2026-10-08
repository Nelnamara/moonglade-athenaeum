# Where Things Live

Moonglade keeps its files in two places, each with one job. **Your library** holds everything
you made and earned. **The program's folder** (the one with `Moonglade Launcher` in it) holds
the app and this PC's own machinery. Since 3.20 every file has one home, and the app never keeps
a second copy of anything for you to clean up.

## The program's folder

```
<the program's folder>\
  Moonglade Launcher.pyw   double-click this to start Moonglade
  config.json              what you type by hand: your PixAI key, the logins, READ_ONLY, overrides
  moonglade\               the app's code
  local\                   this PC's things:
    settings.json          everything the app sets for you: the library folder, the port and LAN
                           discovery, the Mirror to PixAI switch, your branding picks
    mirror_session.json    the Mirror's sign-in
    moonglade.mgpack       the art pack (and its .version note)
    icons\                 the icons your Desktop and Start-menu shortcuts show
    banners\               a banner you wear that can't be drawn again
    cache\                 things the app makes again whenever it needs them
    logs\                  serve.log (the server's console) and moonglade.log (the app's log)
  gallery\  loom\  wiki\  static\   the rest of the app
  dev\                     developer files (the tests and tools); an install never needs them
```

`config.json` is only for what you edit yourself. Anything you change in the Control Panel
lands in `local\settings.json` instead.

## Your library

```
<your library>\              pixai_backup\ unless you chose another folder
  2024-03\  images\  videos\  imported\   your pictures and videos
  catalog.db                 the catalog: the source of truth
  gallery\                   thumbnails
  _deleted\  _duplicates\    what you sent to the Trash, and what --dedup set aside
  _moonglade\                your stuff, kept by the app:
    accounts\                each login's presets, snippets, saved views and settings
    loom\                    the Loom's boards
    records\                 achievements and skin, the Runs, the job list, the schedule, the
                             spend guards, the counters and the reports
    decisions\               choices the app must never lose: what you marked lost, the
                             --organize undo list, a curation import's undo
```

Every scan of the library skips `_moonglade`, so nothing in it is ever mistaken for a picture.

## Answers for users

**Where do I put my PixAI key?**
In `config.json` in the program's folder, as before. Copy `config.example.json` to start one, or
paste the key into the setup screen in the browser.

**Will an update or `git pull` overwrite my settings?**
No. `config.json`, `local\` and your library are never part of an update.

**What do I back up?**
Your library folder: it holds everything you made and earned. Add `config.json` for your key and
logins, and the art tree if you uploaded branding art. Everything else rebuilds itself.

**What happens if I delete `local\`?**
Moonglade makes it again at the next start. The art pack downloads again and you sign the
Mirror in again. You'd also re-pick what you'd changed in the Control Panel: the port, the
library folder, LAN discovery, the Mirror switch and your branding picks. A banner you wear that
can't be drawn again lives there too, so it would go. The caches and logs simply start fresh.

**I moved my library to another drive.**
Point the Control Panel's library folder at it. Your presets, boards and achievements go with it,
because they live inside the library.

**How do I know the move finished?**
The log says so. `local\logs\moonglade.log` has a line for each file brought across (moved,
merged, set aside or removed), and says when the program's folder and the library are tidy. If a
start was interrupted, the next one finishes it.

**A command or the Claude tools say my library is "still in an older Moonglade's layout".**
Only a start of the gallery moves a library's files: the launcher, or `python -m moonglade.gallery`
without `--out`. A command line, the Claude tools and a run that names its own library (`--out`)
never pull a library out from under an older install that may still be using it. Open the
library once with its own install's launcher (updated to 3.20), then run the command again.

**It says an older Moonglade is still using the library.**
Something wrote to the library's old places after the move: usually an older install pointed at
the same library. Close it (its window, its scheduled tasks and its Claude tools), then start this
one again. It brings in what the older one wrote, and nothing is lost.

## Updating from 3.19 or older

The first start of 3.20 moves everything into the homes above by itself. On the same drive each
file is moved in one step; across drives it is copied, checked byte for byte, and only then
deleted from its old place. Before it moves anything it keeps a safety copy of the small files it
moves (never your pictures, the catalog or the art pack), and it deletes that safety copy by itself
after five clean starts: a start counts once the gallery has run for ten minutes or was stopped
from the Control Panel. You never need to delete anything.

Once the update is in, the app closes: the launcher that was running can't find the files it
used to start. Double-click **Moonglade Launcher** in the program's folder once. That start
re-points your Desktop and Start-menu shortcuts to it, icon and all. A Windows Task Scheduler job
or a Claude tools registration that still names an old file is found too, and the notice in the
corner offers **Fix it** (or **Fix them**). More in [Troubleshooting](Troubleshooting#after-updating-to-320-where-did-my-files-go).

Any install from 3.10 onward updates this way.

- **Only Moonglade's own files move.** A folder that just shares an old name, such as `logs` or
  `branding`, is moved only when its contents are Moonglade's. Anything else stays where it is, and
  the log says so.
- **Linked folders move as links.** A Windows junction or folder link you made (for example, Loom
  exports kept on another drive) is moved as the link itself. Its target is never copied, moved or
  deleted.
- **A library two installs share:** update both before using it again. If an older Moonglade is
  still open on the library, the first start of 3.20 stops and asks you to close it. Windows can
  tell; on Linux and macOS, close every older install yourself first. If an older install writes
  to the library later, the next start keeps everything already in the new homes and merges in what
  the older one added.

Going back to an earlier version after 3.20 isn't supported, because it won't find your records
or settings.
