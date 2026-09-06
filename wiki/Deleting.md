# Deleting & cloud sync

Two delete actions live in the **Actions** dropdown that appears when images are selected
in the gallery:

- **Delete locally** — removes from your local catalog only (the cloud task is
  untouched).
- **Delete from PixAI** — deletes the whole **task** from your account *and* removes it
  locally, so they never drift. Requires a request from the machine running the server, even
  for a signed-in account on another device: this one is irreversible on PixAI's side, so it
  stays stricter than "signed in".

> 🛟 **Local files are recoverable, from inside the app.** Both buttons *move* your files
> to a `_deleted/` folder inside your backup rather than destroying them, and clear the
> catalog row. To get something back, open the **Control Panel → Trash** panel: it lists
> everything in `_deleted/` with thumbnails, and **Restore selected** puts the files back
> and re-catalogs them for you. Restoring works from any signed-in device; *Delete forever*
> and *Empty trash* are localhost-only and ask you to type `DELETE` first.
>
> (Hand-copying files out of `_deleted/` and re-running `--import-local` still works as a
> fallback, but you shouldn't need it.)

> ⚠️ **The cloud side of "Delete from PixAI" is irreversible.** From the gallery's
> Actions dropdown it is **task-level**: selecting one image deletes its whole batch on
> PixAI. Gated behind a confirm dialog + typing `DELETE`. Only the *local* part is
> recoverable via `_deleted/`.

**The Actions dropdown's confirm dialog shows you the batch.** Because one selected image
takes its whole task with it, the dialog leads with the real total — *"7 files across 2 tasks
will be deleted from your PixAI account and from your backup. You picked 3; the other 4 come
with their batches."* — and then shows every one of those files as a thumbnail, grouped by
task, with the ones you actually selected outlined in gold. Anything you imported locally (no
PixAI task) is listed separately as a local-only removal, so the count adds up. Nothing is
sent until you press **Continue…** and type `DELETE`.

## Deleting just one image from a batch

The gallery's bulk action takes whole tasks. When you want to remove **one** picture from a
batch and keep its siblings, open that image and use the buttons on its own page:

- **Delete locally** — moves the file to `_deleted/` and clears the catalog row. PixAI
  still has the image, so a later sync brings it back. This is the recoverable one.
- **Delete from PixAI** — removes the image from your account. Irreversible on their side,
  and it removes the local copy too, so the two never drift. **How much it removes depends
  on what PixAI still has of that generation** — read the next section before you use it.

### What "Delete from PixAI" actually removes

PixAI will only remove one picture out of a generation while that generation still has
another picture left. So there are two cases, and the button tells you which one you are in
*before* you commit:

- **Other images of the batch are still on PixAI.** Only this image goes. The dialog says
  how many stay — *"This removes only this image from PixAI. 3 other images in its batch
  stay."* Locally, only this one file moves to your trash folder.
- **This is the last image of that generation still on PixAI.** PixAI has no way to leave a
  generation with nothing in it, so it removes the **whole generation record** — which is
  also what happens when a generation only ever made one image. The dialog says so, and
  **names every local file that will move to your trash folder** with it.

The count comes from PixAI, asked fresh at the moment you click. It is not a count of what
your library holds: a sibling you deleted from PixAI's own website is gone there while its
row is still here, and the dialog has to tell you the truth about *their* copy.

Then it asks you to type `DELETE`, the same gate the bulk action uses. If the generation
changes between the dialog appearing and you typing, the delete is refused rather than
doing the other thing — open it again to see where the image stands.

**One local file is deliberately kept back.** If an image of that generation was already
deleted on PixAI, your copy of it is the only copy left anywhere. A whole-generation delete
leaves that file and its catalog row exactly where they are, and the dialog says so.

Two more answers you may get instead of a dialog:

- **"This image is already deleted on PixAI."** Nothing is sent and nothing local is
  touched — your copy is now the only one. The row is marked so the library stops offering
  the button for it.
- **"Video clips are deleted from the task's page on PixAI."** Deleting a clip is not
  something this app does yet; do it on PixAI's own page for that generation.

Two cases where the button is simply not there:

- **A file you imported from your own computer.** PixAI has no copy of it, so there is
  nothing on their side to delete. Use **Delete locally**.
- **A session on another device.** Irreversible cloud deletion needs a request from the
  machine running the server, even for your own signed-in account — the same rule the
  bulk action follows.

The cloud call happens first and the local copy is only removed once it succeeds. If PixAI
refuses or the network drops, the image is left exactly where it was on both sides, and you
can try again.

## Reconcile — clean up what you deleted on the website

Deleting a task on PixAI doesn't touch your local backup (by design). To find and
prune those orphans:

1. Run **`python moonglade_backup.py --reconcile-deleted`** (it's also the last step of
   `--sync`, and a scheduler action). It pages your live feed (~1–2 min) and flags catalog
   rows whose task is gone.
2. Gallery → **Source → "Deleted on PixAI"** → select → **Delete locally**.

It skips imports and anything generated in the last ~2 days (so a fresh generation
isn't false-flagged), and aborts if the feed comes back empty.

## CLI

```bash
python moonglade_backup.py --reconcile-deleted     # flag cloud-deleted orphans
python moonglade_backup.py --delete-task <taskid>  # DEPRECATED -- use the gallery's Delete from PixAI
```

**`--delete-task` is deprecated.** It still works this release and it still prints its own
notice saying so, but it is no longer the way to delete. Use the gallery's **Delete from
PixAI** — on one image for a single picture, or from the **Actions** dropdown for a
selection. Those check with PixAI first and keep your library in step; `--delete-task`
does neither.

While it lasts, it behaves as it always has: dry-run until `--apply`, and **cloud-only** —
your local files and `catalog.db` are untouched, so a task deleted this way leaves orphan
rows behind for `--reconcile-deleted` to find. The `--apply` flag plus typing `delete` at the
confirmation prompt (case-insensitive; skippable with `--yes`) are the safety mechanism.
Uppercase `DELETE` is the *gallery's* gate (that one **is** case-sensitive); `--confirm` is a
different flag entirely — it gates credit-spending generation, not deletion.

`READ_ONLY: true` in `config.json` blocks every one of these outright, regardless of `--yes`
or the typed confirm — see [Trust & Safety](Trust-and-Safety#the-read_only-flag).
