# Deleting & cloud sync

Two delete buttons appear when images are selected in the gallery:

- **Delete (local)** — removes from your backup only (catalog rows + files). The cloud
  task is untouched.
- **Delete from PixAI** — deletes the whole **task** from your account *and* locally,
  so they never drift.

> ⚠️ **"Delete from PixAI" is irreversible on the cloud side.** It's **task-level**:
> selecting one image deletes its whole batch. Gated behind a confirm dialog + typing
> `DELETE`.

## Reconcile — clean up what you deleted on the website

Deleting a task on PixAI doesn't touch your local backup (by design). To find and
prune those orphans:

1. GUI **Utilities → Reconcile Deleted** (or `--reconcile-deleted`). It pages your
   live feed (~1–2 min) and flags catalog rows whose task is gone.
2. Gallery → **Source → "Deleted on PixAI"** → select → **Delete (local)**.

It skips imports and anything generated in the last ~2 days (so a fresh generation
isn't false-flagged), and aborts if the feed comes back empty.

## CLI

```bash
python pixai_gallery_backup.py --reconcile-deleted     # flag cloud-deleted orphans
python pixai_gallery_backup.py --delete-task <taskid>  # delete one task cloud+local (irreversible)
```

`--delete-task` requires confirmation. Deletion uses a baked-in persisted hash; the
typed-`DELETE` / `--confirm` gates are the safety mechanism.
