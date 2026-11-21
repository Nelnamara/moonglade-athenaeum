"""
moonglade/dupe_review.py
========================
Duplicate Review's destructive half: quarantining a duplicate file (with an undo record beside
it), restoring it to exactly where it came from, and `_validate_duplicate_pair`, which
re-checks a group before anything moves. The read-only half (GET /api/duplicates) is
moonglade/routes_library.py's and the matcher is moonglade/dupes.py. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It reads the catalog through moonglade.catalog, and nothing from the gallery or the engine.
"""
import json
from pathlib import Path

from moonglade import catalog as _catalog
from moonglade import dupes as _dupes
from moonglade import organize as _organize
from moonglade import scan as _scan
from moonglade import history as _history


# ---------------------------------------------------------------------------
# Duplicate Review -- resolve/undo (the destructive half of GET /api/duplicates
# above, which stays read-only). Mirrors the trash panel's own shape immediately
# above -- a moved file plus a JSON sidecar recording enough to undo it -- rather
# than inventing a new pattern, but keyed by the file's OWN quarantine location,
# not media_id: a same_media group can quarantine more than one copy of the SAME
# media_id in a single resolve, so media_id alone is not a unique key here the
# way it is for trash (purge_media_local never has two files under one media_id
# to quarantine at once -- the live catalog holds exactly one file per media_id).
# The original path is recorded EXPLICITLY and undo restores to that EXACT
# location -- unlike trash's restore, which only ever remembered a bare filename
# and always restores into a flat images/ folder -- because cmd_dedup's own
# quarantine (moonglade/organize.py's cmd_dedup) preserves the source's
# real subfolder structure under _duplicates/, and this feature's undo is
# specified to put a file back exactly where it came from.
# ---------------------------------------------------------------------------
# DUPLICATES_DIRNAME (the dedup quarantine folder) is defined in the LIBRARY SCAN
# section above, beside the other directory names every walker shares.


def _quarantine_meta_path(dest):
    """Sidecar path for one quarantined duplicate's undo record, living beside
    the moved file itself (same 'metadata rides next to the file' idea as
    trash's _trash_meta_path above)."""
    return dest.with_name(dest.name + ".undo.json")


def _resolve_under(out_dir, rel_path):
    """A client-submitted relative path, turned into a real absolute Path
    strictly inside out_dir -- or None if it's blank, absolute, or escapes via
    '..'/a symlink. Every client-supplied path this feature touches goes
    through this before it is ever stat'd or moved."""
    rel_path = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel_path:
        return None
    out_dir = Path(out_dir).resolve()
    candidate = (out_dir / rel_path).resolve()
    return candidate if _scan._is_under(candidate, out_dir) else None


def _reconcile_one_row_after_move(out_dir, db_path, media_id, row):
    """Targeted, single-row version of moonglade.organize.reconcile_catalog_with_disk
    -- point media_id's catalog row at whatever copy is still actually on disk,
    without rescanning/rewriting the whole catalog (that function's own approach,
    fine for a batch CLI run, is wasteful for a single synchronous HTTP request).
    Used when a duplicate quarantine or undo changes what's on disk for a
    media_id whose row is being KEPT (e.g. a same_media loser's row, still
    pointing at a keeper that survives elsewhere). No-op if nothing changed, and
    a no-op if the media_id has no surviving file at all (that case is the
    caller's row-delete branch instead, not this function's job)."""
    matches = _scan.find_files_for_media_id(out_dir, media_id)
    if not matches:
        return
    survivor = matches[0]
    rel_surv = survivor.relative_to(out_dir)
    bucket = _organize._bucket_of(rel_surv)
    new_batch = (rel_surv.parts[1] if bucket == "batches" and len(rel_surv.parts) > 2
                else ("" if bucket != "batches" else row.get("batch", "")))
    if row.get("filename") != survivor.name or row.get("batch", "") != new_batch:
        row = dict(row)
        row["filename"] = survivor.name
        row["batch"] = new_batch
        _catalog.save_catalog(db_path, [row])


def quarantine_duplicate_file(out_dir, thumb_dir, db_path, media_id, rel_path, group_id):
    """Move ONE duplicate loser out of the live tree into out_dir/_duplicates/,
    mirroring cmd_dedup()'s DEFAULT (--apply without --dedup-delete) behavior at
    moonglade/organize.py's cmd_dedup -- quarantine, never hard-delete,
    same collision-suffix rule (dest already exists -> "_dup" inserted before the
    extension). Called once per file by the /api/duplicates/resolve route, which
    has already re-verified the (group_id, media_id, path) triple names a real
    duplicate pair (see _validate_duplicate_pair) -- this function trusts that
    and only handles the mechanics: the move, the catalog reconciliation, and
    the undo sidecar. --dedup-delete's hard-delete behavior is not reachable
    through this function under any argument.

    _check_read_only() fires FIRST, before any path is even resolved -- the same
    position submit_generation/submit_fixer/delete_task/claim_reward give it
    (moonglade/backup.py's own contract for every account/filesystem mutation
    this app makes). READ_ONLY in config.json refuses this the same way it
    refuses those.

    Catalog handling depends on whether media_id has ANY other live copy left
    after the move (find_files_for_media_id, which already excludes
    _duplicates/_deleted -- invariant 6):
      * no survivor  -> same situation as a trash purge: the row is removed
        (delete_from_catalog) and a FULL snapshot goes into the sidecar so
        undo can reinsert it, exactly like purge_media_local/
        restore_quarantined_media above.
      * a survivor exists (e.g. the keeper of a same_media group, still on disk
        under the SAME media_id) -> the row must NOT be deleted -- the media_id
        is still alive. Only a targeted filename/batch reconcile runs
        (_reconcile_one_row_after_move), the same fix
        reconcile_catalog_with_disk applies after a CLI --dedup, just scoped to
        this one row instead of a full rescan.

    Returns {"ok": True, "media_id", "original_path", "quarantine_path", "size",
    "row_deleted"} or {"ok": False, "error": "..."} -- never raises."""
    from moonglade import backup as core
    try:
        core._check_read_only("quarantine a duplicate file (Duplicate Review resolve)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    # .resolve() to match exactly what _resolve_under() resolved `src` against below --
    # otherwise a caller passing an out_dir that differs from its own .resolve() (a
    # symlink, a trailing slash) makes src.relative_to(out_dir) raise ValueError even
    # though src is genuinely inside it.
    out_dir = Path(out_dir).resolve()
    src = _resolve_under(out_dir, rel_path)
    if src is None:
        return {"ok": False, "error": "invalid path"}
    quarantine_root = out_dir / _scan.DUPLICATES_DIRNAME
    deleted_root = out_dir / _scan.DELETED_DIRNAME
    if _scan._is_under(src, quarantine_root) or _scan._is_under(src, deleted_root):
        return {"ok": False, "error": "already quarantined"}
    if not src.is_file():
        return {"ok": False, "error": "file not found: {}".format(rel_path)}

    rel = src.relative_to(out_dir)
    try:
        size = src.stat().st_size
    except OSError:
        size = 0
    row_before = _catalog.get_row(db_path, media_id) if media_id else None

    dest = quarantine_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():                                   # don't clobber an earlier quarantine
        dest = dest.with_name(dest.stem + "_dup" + dest.suffix)
    try:
        src.replace(dest)                                # atomic move, same volume
    except OSError as e:
        return {"ok": False, "error": str(e)}

    row_deleted = False
    if row_before:
        survivors = _scan.find_files_for_media_id(out_dir, media_id)
        if not survivors:
            _catalog.delete_from_catalog(db_path, media_id)
            row_deleted = True
            tp = Path(thumb_dir) / "{}.jpg".format(media_id)
            if tp.exists():
                try:
                    tp.unlink()
                except OSError:
                    pass
        else:
            _reconcile_one_row_after_move(out_dir, db_path, media_id, row_before)

    rel_dest = str(dest.relative_to(out_dir)).replace("\\", "/")
    rel_orig = str(rel).replace("\\", "/")
    import time
    sidecar = {
        "media_id": str(media_id),
        "original_path": rel_orig,
        "quarantine_path": rel_dest,
        "group_id": group_id,
        "quarantined_at": time.time(),
        "row_deleted": row_deleted,
        "catalog_row": row_before if row_deleted else None,
    }
    try:
        _quarantine_meta_path(dest).write_text(json.dumps(sidecar), encoding="utf-8")
    except OSError:
        pass    # best-effort, same fail-soft contract as trash's own snapshot write

    return {"ok": True, "media_id": str(media_id), "original_path": rel_orig,
            "quarantine_path": rel_dest, "size": size, "row_deleted": row_deleted}


def restore_quarantined_duplicate(out_dir, thumb_dir, db_path, quarantine_path):
    """Reverse ONE quarantine_duplicate_file() call: move the file back to its
    EXACT original recorded location (not a generic default folder -- unlike
    trash's restore_quarantined_media, this tier's undo is specified to put a
    file back exactly where it came from) and restore whatever the catalog
    snapshot says.

    Fails honestly -- never a silent no-op, never a write to some OTHER
    location -- when:
      * no sidecar/file exists for quarantine_path (missing/stale record, or it
        was never a real quarantined duplicate to begin with)
      * the original location is occupied by a DIFFERENT file that showed up
        there since (a re-download, a re-organize, a fresh import)

    Same _check_read_only() gate, in the same first-statement position, as
    quarantine_duplicate_file().

    Returns {"ok": True, "media_id", "restored_path"} or
    {"ok": False, "error": "..."} -- never raises."""
    from moonglade import backup as core
    try:
        core._check_read_only("undo a duplicate quarantine (Duplicate Review undo)")
    except core.PixAIError as e:
        return {"ok": False, "error": str(e)}

    out_dir = Path(out_dir).resolve()   # match _resolve_under()'s own resolution -- see
                                        # quarantine_duplicate_file()'s identical comment
    quarantine_root = out_dir / _scan.DUPLICATES_DIRNAME
    src = _resolve_under(out_dir, quarantine_path)
    if src is None or not _scan._is_under(src, quarantine_root):
        return {"ok": False, "error": "not a quarantined-duplicate path"}
    meta_path = _quarantine_meta_path(src)
    if not src.is_file() or not meta_path.exists():
        return {"ok": False, "error": "no undo record for this file "
                                      "(missing, already restored, or stale)"}
    try:
        sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": "undo record is unreadable/corrupt"}

    original_path = str(sidecar.get("original_path") or "")
    dest = _resolve_under(out_dir, original_path)
    if dest is None:
        return {"ok": False, "error": "recorded original path is invalid"}
    if dest.exists():
        return {"ok": False, "error": "original location is occupied by another "
                                      "file now -- refusing to overwrite it"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    media_id = str(sidecar.get("media_id") or "")
    if sidecar.get("row_deleted") and sidecar.get("catalog_row"):
        _catalog.save_catalog(db_path, [sidecar["catalog_row"]])
    elif media_id:
        row = _catalog.get_row(db_path, media_id)
        if row:
            _reconcile_one_row_after_move(out_dir, db_path, media_id, row)

    try:
        meta_path.unlink()
    except OSError:
        pass

    return {"ok": True, "media_id": media_id,
            "restored_path": str(dest.relative_to(out_dir)).replace("\\", "/")}


def _validate_duplicate_pair(out_dir, db_path, match_type, keep, remove):
    """Re-verify, at request time, that `keep` and every item in `remove`
    genuinely form the duplicate relationship match_type claims -- never trust
    the client's group_id/keep/remove alone; a client could otherwise pair a
    real duplicate's catalog metadata with an unrelated file path and use this
    route to quarantine anything. Cheap and TARGETED (touches only the specific
    files/rows named, never a full-library rescan) rather than recomputing GET
    /api/duplicates' whole detection pass. Returns (True, "") or
    (False, "<reason>") -- the whole group is refused together on failure,
    since a partially-verified group is not a safe partial resolve.

    near_duplicate is checked as a direct keep<->remove pairwise Hamming
    distance, not full group membership: near_duplicate_groups() can chain a
    group together transitively (A near B, B near C, but A and C individually
    over threshold) via union-find. A remove item that is only transitively
    linked to the chosen keeper is refused here as a known, documented
    simplification -- resolving it means picking a keeper it IS directly close
    to, not a gap in the detection logic."""
    out_dir = Path(out_dir)

    def _real(entry):
        """Resolve+validate one {media_id, path} member: a real file, strictly
        inside out_dir, whose OWN filename encodes the claimed media_id."""
        if not isinstance(entry, dict):
            return None
        mid = str(entry.get("media_id") or "").strip()
        path = _resolve_under(out_dir, entry.get("path"))
        if not mid or path is None or not path.is_file():
            return None
        if _scan.media_id_of(path) != mid:
            return None
        return mid, path

    k = _real(keep)
    if k is None:
        return False, "keeper does not resolve to a real file"
    keep_mid, keep_path = k

    checked = []
    for item in remove:
        r = _real(item)
        if r is None:
            return False, "a remove item does not resolve to a real file"
        checked.append(r)
    if not checked:
        return False, "nothing to remove"

    if match_type == "same_media":
        if any(mid != keep_mid for mid, _ in checked):
            return False, "same_media resolve must keep and remove copies of the SAME media_id"
        return True, ""

    if match_type == "identical_file":
        for mid, path in checked:
            if not _history._same_bytes(keep_path, path):
                return False, "keeper and {} are no longer byte-identical".format(mid)
        return True, ""

    if match_type == "same_seed":
        keep_row = _catalog.get_row(db_path, keep_mid)
        if not keep_row or not keep_row.get("seed") or not keep_row.get("prompt_full"):
            return False, "keeper has no seed/prompt to match against"
        for mid, _ in checked:
            row = _catalog.get_row(db_path, mid)
            if not row or row.get("seed") != keep_row.get("seed") \
                    or row.get("prompt_full") != keep_row.get("prompt_full"):
                return False, "{} no longer shares (seed, prompt) with the keeper".format(mid)
        return True, ""

    if match_type == "near_duplicate":
        keep_row = _catalog.get_row(db_path, keep_mid)
        keep_phash = (keep_row or {}).get("phash") or ""
        try:
            keep_bits = int(keep_phash, 16)
        except ValueError:
            return False, "keeper has no usable phash"
        for mid, _ in checked:
            row = _catalog.get_row(db_path, mid)
            phash = (row or {}).get("phash") or ""
            try:
                dist = bin(keep_bits ^ int(phash, 16)).count("1")
            except ValueError:
                return False, "{} has no usable phash".format(mid)
            if dist > _dupes.NEAR_DUP_HAMMING_THRESHOLD:
                return False, ("{} is no longer within the near-duplicate threshold "
                              "of the keeper").format(mid)
        return True, ""

    return False, "unknown group type '{}'".format(match_type)
