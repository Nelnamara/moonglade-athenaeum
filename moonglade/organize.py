"""
moonglade/organize.py
=====================
The duplicate audit, dedup, quarantine check, catalog reconcile and the month-folder organize
(with its undo). Moved verbatim out of moonglade/backup.py in the 3.21.0 split (phase 1).

The names it needs from the engine (its errors, the catalog verbs, the byte and pixel
comparisons, the converters) are imported from moonglade.backup inside each function that uses
them, never at the top, so importing this module never imports the engine.
"""
import csv
import sys
import time
from collections import defaultdict, Counter

from moonglade import paths as _paths
from moonglade.scan import (_IMAGE_EXTS, bucket_of, find_files_for_media_id, media_id_of,
                            QUARANTINE_EXCLUDE, scan_library)


# ---------------------------------------------------------------------------
# Duplicate audit + dedup (filesystem-truth; independent of catalog.db)
# ---------------------------------------------------------------------------
# Keeper priority when the same image lives in several buckets: lower wins
# (i.e. we KEEP the most-organized copy and remove the rest). This reinforces
# --organize's layout instead of fighting it. "batches" ranks first as LEGACY
# ONLY -- no reachable code path creates a batches/ folder anymore (the old
# live-organize-into-batches mode lived behind an `organize_adv_live` runtime
# flag that no CLI argument has ever set since; --organize's real, current
# output is month folders only, and its own run tidies up leftover legacy
# batches/ dirs -- see below). A batches/ folder found here is pre-existing
# data from an older run, still worth preferring as a keeper if one exists.
_BUCKET_PRIORITY = {"batches": 0, "month": 1, "images": 2, "other": 3}


# The bucket classifier is `moonglade.gallery.bucket_of` -- the LIBRARY SCAN
# section's one copy. This alias keeps the private name every caller (and
# dev/tests/test_dedup.py's `core._bucket_of` assertions) already uses.
_bucket_of = bucket_of


def _scan_media_files(out_dir):
    """One walk of the tree. Yields (path, rel, bucket, media_id) for every image
    file outside gallery/, _duplicates/, and _deleted/. The audit's view (and, via
    verify_quarantine, the dedup-verify pass) onto the shared scan.

    _deleted/ exclusion is B11 (audit 2026-07-21): without it, a locally-purged
    image is a valid audit hit -- reported back as a live Class A duplicate of its
    own quarantined self, and (via verify_quarantine's survivor index) potentially
    treated as the "surviving keeper" a _duplicates/ copy is compared against.

    Deliberately does NOT drop zero-byte files (named disagreement 3): the audit
    has to SEE one in order to never choose it as a keeper -- dev/tests/test_dedup.py
    pins that, and it is why the scan reports `size` rather than deciding."""
    for e in scan_library(out_dir, kinds=("image",), exclude=QUARANTINE_EXCLUDE):
        yield e.path, e.rel, e.bucket, e.media_id


def audit_collection(out_dir, content=True, progress=None):
    """Filesystem-truth duplicate audit. Returns a dict:
        per_bucket       : {bucket: count}
        class_a          : [ {media_id, files:[(rel,bucket,size)], keeper, losers} ]
        class_b          : [ {sha, files:[(rel,bucket,size,media_id)], keeper, losers} ]
        totals           : counts + reclaimable bytes
    Class A = same media_id in >1 location (no hashing needed).
    Class B = byte-identical content under DIFFERENT media_ids (size-bucketed hash).
    """
    from moonglade.backup import _file_sha
    by_mid = defaultdict(list)      # mid -> [(path, rel, bucket, size)]
    by_size = defaultdict(list)     # size -> [(path, rel, bucket, mid)]
    per_bucket = Counter()
    all_files = list(_scan_media_files(out_dir))
    total = len(all_files)
    for i, (p, rel, bucket, mid) in enumerate(all_files):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0:
            # A 0-byte file (an interrupted download, same failure mode as invariant 3's
            # resume-index bug) must never enter by_mid/by_size: with bucket priority as
            # the ONLY keeper-selection signal, an empty file in the "batches" bucket
            # outranks a real image in "images" and gets chosen as the survivor. Under
            # plain --dedup that is recoverable (the auto-verify pass below flags it,
            # "REVIEW NEEDED"); under --dedup --apply --dedup-delete there is no verify
            # step at all, so it silently hard-deletes the only real copy. Excluding it
            # here means it can never become a keeper OR a loser -- it simply isn't part
            # of any duplicate group, which is also correct: an empty file isn't a
            # duplicate of anything.
            continue
        per_bucket[bucket] += 1
        by_mid[mid].append((p, rel, bucket, size))
        by_size[size].append((p, rel, bucket, mid))
        if progress and (i % 500 == 0 or i + 1 == total):
            progress(i + 1, total, 0)

    def _keeper(items, key_bucket):
        # items: list of tuples; key_bucket(item) -> bucket name. Prefer organized,
        # then shortest path (stable), so the canonical copy is deterministic.
        # A zero-byte item (it[3] is size on the by_mid tuple shape) can never win --
        # False < True, so "is empty" sorts before every real bucket/path comparison.
        # Defense in depth: the loop above already excludes zero-byte files from ever
        # reaching `items` at all, so this branch should be unreachable in practice.
        return min(items, key=lambda it: (it[3] == 0,
                                          _BUCKET_PRIORITY.get(key_bucket(it), 9),
                                          len(str(it[1]))))

    # ---- Class A: same media_id across >1 distinct bucket -------------------
    class_a = []
    for mid, items in by_mid.items():
        buckets = {b for (_, _, b, _) in items}
        if len(items) > 1 and len(buckets) > 1:
            keeper = _keeper(items, lambda it: it[2])
            losers = [it for it in items if it[0] != keeper[0]]
            class_a.append({"media_id": mid, "files": items,
                            "keeper": keeper, "losers": losers})

    # ---- Class B: identical bytes, different media_id -----------------------
    class_b = []
    if content:
        # Only hash within same-size groups that span >1 distinct media_id.
        candidates = [(s, grp) for s, grp in by_size.items()
                      if len({m for (_, _, _, m) in grp}) > 1]
        hashed = 0
        n_to_hash = sum(len(grp) for _, grp in candidates)
        by_sha = defaultdict(list)
        for s, grp in candidates:
            for (p, rel, bucket, mid) in grp:
                sha = _file_sha(p)
                hashed += 1
                if sha:
                    by_sha[sha].append((p, rel, bucket, s, mid))
                if progress and (hashed % 200 == 0 or hashed == n_to_hash):
                    progress(hashed, max(n_to_hash, 1), 1)
        for sha, items in by_sha.items():
            mids = {m for (_, _, _, _, m) in items}
            if len(items) > 1 and len(mids) > 1:
                keeper = _keeper(items, lambda it: it[2])
                losers = [it for it in items if it[0] != keeper[0]]
                class_b.append({"sha": sha, "files": items,
                                "keeper": keeper, "losers": losers})

    reclaim_a = sum(sz for g in class_a for (_, _, _, sz) in g["losers"])
    reclaim_b = sum(it[3] for g in class_b for it in g["losers"])
    return {
        "per_bucket": dict(per_bucket),
        "class_a": class_a,
        "class_b": class_b,
        "totals": {
            "files": total,
            "class_a_groups": len(class_a),
            "class_a_redundant": sum(len(g["losers"]) for g in class_a),
            "class_b_groups": len(class_b),
            "class_b_redundant": sum(len(g["losers"]) for g in class_b),
            "reclaimable_bytes": reclaim_a + reclaim_b,
        },
    }


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "{:.1f} {}".format(n, unit)
        n /= 1024


def cmd_audit(args, out):
    """Read-only duplicate audit. Prints a summary and writes audit_report.csv.
    Touches nothing on disk. Independent of catalog.db."""
    content = not getattr(args, "no_content", False)
    print("Auditing {} (content hashing: {})...".format(
        out, "on" if content else "off"))
    _prog = getattr(args, "progress", None)
    rep = audit_collection(out, content=content, progress=_prog)
    t = rep["totals"]

    print("\nFiles per bucket:")
    for b, c in sorted(rep["per_bucket"].items(), key=lambda kv: -kv[1]):
        print("  {:<10} {:,}".format(b, c))

    print("\nClass A  - same media_id in >1 folder : {:,} groups, {:,} redundant files"
          .format(t["class_a_groups"], t["class_a_redundant"]))
    print("Class B  - identical bytes, diff id   : {:,} groups, {:,} redundant files"
          .format(t["class_b_groups"], t["class_b_redundant"]))
    print("Reclaimable if deduped                : {}".format(
        _fmt_bytes(t["reclaimable_bytes"])))

    # Write detailed CSV
    report_path = _paths.records_path(out, "audit_report.csv")
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["class", "group_key", "role", "bucket", "media_id", "size", "path"])
        for g in rep["class_a"]:
            kp, kr, kb, ksz = g["keeper"]
            w.writerow(["A", g["media_id"], "keep", kb, g["media_id"], ksz, str(kr)])
            for (_, rel, b, sz) in g["losers"]:
                w.writerow(["A", g["media_id"], "remove", b, g["media_id"], sz, str(rel)])
        for g in rep["class_b"]:
            kp, kr, kb, ksz, kmid = g["keeper"]
            w.writerow(["B", g["sha"][:12], "keep", kb, kmid, ksz, str(kr)])
            for (_, rel, b, sz, mid) in g["losers"]:
                w.writerow(["B", g["sha"][:12], "remove", b, mid, sz, str(rel)])
    print("\nDetailed report -> {}".format(report_path.relative_to(out.parent)
                                            if out.parent else report_path))
    print("Run --dedup to act on this (quarantine by default; nothing deleted yet).")
    return rep


def cmd_dedup(args, out, db_path):
    """Act on the audit: move redundant copies to _duplicates/ (default) or delete
    them (--dedup-delete). Keeps the most-organized copy. Dry-run by default.
    Reconciles catalog.db with what's left on disk afterward."""
    from moonglade.backup import _ensure_db, PixAIError
    # Dedup is filesystem-truth: it does not need a catalog to run. Reconcile is
    # a bonus, applied only if a catalog exists.
    try:
        db_path = _ensure_db(out)
        have_catalog = True
    except PixAIError:
        have_catalog = False
    content = not getattr(args, "no_content", False)
    delete = getattr(args, "dedup_delete", False)
    apply = getattr(args, "apply", False)  # default is dry-run unless --apply

    rep = audit_collection(out, content=content, progress=getattr(args, "progress", None))
    losers = []  # (rel_path, abs_path, what it is a copy of -- the Great Sweep's key)
    for g in rep["class_a"]:
        for (p, rel, b, sz) in g["losers"]:
            losers.append((rel, p, "dup-media:%s" % g["media_id"]))
    for g in rep["class_b"]:
        for (p, rel, b, sz, mid) in g["losers"]:
            losers.append((rel, p, "dup-sha:%s" % g["sha"]))

    action = "DELETE" if delete else "quarantine to _duplicates/"
    print("\nDedup plan: {:,} redundant files to {} ({})".format(
        len(losers), action, _fmt_bytes(rep["totals"]["reclaimable_bytes"])))
    for rel, _, _ in losers[:8]:
        print("  {}".format(rel))
    if len(losers) > 8:
        print("  ... and {:,} more".format(len(losers) - 8))

    if not apply:
        print("\nDry run -- nothing changed. Re-run with --apply to perform it.")
        return rep

    quarantine_root = out / "_duplicates"
    moved = removed = failed = 0
    culled_keys = []
    _prog = getattr(args, "progress", None)
    for i, (rel, p, key) in enumerate(losers):
        try:
            if delete:
                p.unlink()
                removed += 1
            else:
                dest = quarantine_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest = dest.with_name(dest.stem + "_dup" + dest.suffix)
                p.replace(dest)
                moved += 1
            culled_keys.append(key)
        except OSError as e:
            print("  failed {} ({})".format(rel, e))
            failed += 1
        if _prog:
            _prog(i + 1, len(losers), 0)

    if delete:
        print("\nDeleted {:,} files, {:,} failed.".format(removed, failed))
    else:
        print("\nQuarantined {:,} files to {}, {:,} failed.".format(
            moved, quarantine_root.relative_to(out.parent) if out.parent else quarantine_root,
            failed))

    if culled_keys:
        try:      # The Great Sweep: each redundant copy once, keyed by what it duplicated --
            # copying a file back and deduping it again is not a second piece swept
            from moonglade.gallery import telem_set_add_many
            telem_set_add_many("culled_keys", culled_keys, out_dir=out)
        except Exception:
            pass

    if have_catalog:
        n = reconcile_catalog_with_disk(out, db_path)
        print("Reconciled catalog: updated {:,} filename/batch entries to match disk.".format(n))

    # Auto-verify after quarantining. Dedup chose losers by media_id WITHOUT
    # comparing bytes, so this is the only step that confirms each quarantined
    # file truly matches a surviving keeper. Never auto-deletes -- the human does.
    if not delete and moved:
        print("\n--- Verifying the quarantine (confirming every moved file is "
              "redundant) ---")
        vr = verify_quarantine(out, progress=getattr(args, "progress", None))
        ok = vr["safe"] + vr["meta_only"]
        print("Verify: {:,} confirmed safe ({:,} byte-identical + {:,} metadata-only), "
              "{:,} differ, {:,} orphan.".format(
                  ok, vr["safe"], vr["meta_only"], len(vr["differs"]), len(vr["orphan"])))
        if vr["differs"] or vr["orphan"]:
            print("REVIEW NEEDED before deleting _duplicates/ -- run --verify-dupes "
                  "to write verify_report.csv with the flagged items.")
        else:
            print("All quarantined files confirmed redundant -- _duplicates/ is safe "
                  "to delete to reclaim the space.")
    return rep


def verify_quarantine(out_dir, restore_orphans=False, progress=None):
    """Final-pass safety check on _duplicates/ BEFORE you delete it.

    For every quarantined file, find the surviving keeper with the same media_id
    (outside _duplicates/) and compare bytes. Classifies each as:
      * safe    - a keeper exists AND bytes are identical -> truly redundant
      * differs - a keeper exists but bytes DIFFER -> same media_id, different
                  content (a naming collision the sort/backfill missed) -> REVIEW
      * orphan  - no surviving keeper at all -> quarantining it lost the only copy
    Optionally restores orphans back to images/. Returns a result dict.
    """
    from moonglade.backup import _same_bytes, _same_pixels
    quarantine_root = out_dir / "_duplicates"
    if not quarantine_root.exists():
        return {"safe": 0, "differs": [], "orphan": [], "total": 0}

    files = [p for p in quarantine_root.rglob("*")
             if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    # Index surviving keepers (everything outside _duplicates/ and gallery/) once,
    # in a single walk, so we don't rglob the whole tree per quarantined file.
    survivors = defaultdict(list)
    for p, rel, bucket, mid in _scan_media_files(out_dir):
        survivors[mid].append(p)

    safe = 0
    meta_only = 0  # bytes differ but pixels identical (e.g. embedded PNG metadata)
    differs = []   # (quarantined_path, keeper_path) - genuinely different pixels
    orphan = []    # quarantined_path
    total = len(files)
    for i, q in enumerate(files):
        keepers = survivors.get(media_id_of(q), [])
        if not keepers:
            orphan.append(q)
        elif _same_bytes(q, keepers[0]):
            safe += 1
        else:
            # Bytes differ. Fall back to a pixel compare: identical pixels mean the
            # difference is just container/metadata (the keeper has prompt text
            # embedded), so it's still safe to delete the quarantined copy.
            px = _same_pixels(q, keepers[0])
            if px is True:
                meta_only += 1
            else:
                differs.append((q, keepers[0]))
        if progress and (i % 200 == 0 or i + 1 == total):
            progress(i + 1, total, 0)

    restored = 0
    if restore_orphans and orphan:
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        for q in orphan:
            dest = images_dir / q.name
            try:
                q.replace(dest)
                restored += 1
            except OSError as e:
                print("  restore failed {} ({})".format(q.name, e))

    return {"safe": safe, "meta_only": meta_only, "differs": differs,
            "orphan": orphan, "total": total, "restored": restored}


def cmd_verify_dupes(args, out):
    """Verify the _duplicates/ quarantine is safe to delete. Read-only unless
    --restore-orphans is passed."""
    restore = getattr(args, "restore_orphans", False)
    print("Verifying quarantine in {}/_duplicates ...".format(out))
    res = verify_quarantine(out, restore_orphans=restore,
                            progress=getattr(args, "progress", None))
    if res["total"] == 0:
        print("No _duplicates/ folder (nothing quarantined yet).")
        return res

    print("\nQuarantined files checked : {:,}".format(res["total"]))
    print("  safe - byte-identical keeper exists       : {:,}".format(res["safe"]))
    print("  safe - pixels identical (metadata-only)   : {:,}".format(res["meta_only"]))
    print("  DIFFERS - same id, DIFFERENT pixels       : {:,}".format(len(res["differs"])))
    print("  ORPHAN  - no surviving keeper             : {:,}".format(len(res["orphan"])))

    if res["differs"] or res["orphan"]:
        report = _paths.records_path(out, "verify_report.csv")
        with open(report, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["status", "quarantined_file", "surviving_keeper"])
            for q, k in res["differs"]:
                w.writerow(["differs", str(q.relative_to(out)), str(k.relative_to(out))])
            for q in res["orphan"]:
                w.writerow(["orphan", str(q.relative_to(out)), ""])
        print("\nFlagged items written to {}".format(report.relative_to(out.parent)
                                                     if out.parent else report))

    if res.get("restored"):
        print("Restored {:,} orphaned files to images/.".format(res["restored"]))

    if not res["differs"] and not res["orphan"]:
        print("\nAll clear: every quarantined file is byte-identical to a surviving "
              "copy. Safe to delete _duplicates/.")
    else:
        print("\nDo NOT blanket-delete yet -- review the flagged items above first.")
        if res["orphan"] and not restore:
            print("Re-run with --restore-orphans to move orphans back to images/.")
    return res


def reconcile_catalog_with_disk(out_dir, db_path):
    """After files move/disappear, point each catalog row's filename+batch at the
    surviving on-disk file for that media_id. Rows whose file is gone keep their
    last-known filename but are left intact (the image may be re-downloadable)."""
    from moonglade.backup import load_catalog, save_catalog
    rows = load_catalog(db_path)
    updated = 0
    for r in rows:
        mid = r.get("media_id")
        if not mid:
            continue
        matches = find_files_for_media_id(out_dir, mid)
        if not matches:
            continue
        survivor = matches[0]
        rel = survivor.relative_to(out_dir)
        bucket = _bucket_of(rel)
        new_batch = rel.parts[1] if bucket == "batches" and len(rel.parts) > 2 else (
            "" if bucket != "batches" else r.get("batch", ""))
        if r.get("filename") != survivor.name or r.get("batch", "") != new_batch:
            r["filename"] = survivor.name
            r["batch"] = new_batch
            updated += 1
    if updated:
        save_catalog(db_path, rows)
    return updated


ORGANIZE_MANIFEST = "organize_manifest.csv"


def cmd_organize(args, out, img_dir, db_path):
    """Normalize PixAI images into YYYY-MM/ month folders with descriptive,
    readable filenames (prompt_taskid_mediaid) -- one flat scheme, NO batch
    subfolders. Scans the WHOLE backup (flat images/, existing month folders, and
    any legacy batches/), so a single run brings everything to the same layout for
    easy Explorer browsing.

    Safety: writes a reversible move-manifest (organize_manifest.csv: old->new) so
    every move can be undone with --undo-organize. Idempotent (files already at
    their target are skipped), byte-safe (never overwrites a differing file), and
    dry-runnable. Metadata embedding (--embed-metadata) and conversion (--convert)
    are opt-in. Imported (source='local') files, videos, and _deleted/ quarantine
    are left untouched (B11, audit 2026-07-21: this is the only one of B11's five
    quarantine-blind walks that actually MOVES files -- a stale _deleted/ remnant
    sharing a media_id with the live catalogued copy collided with it in the move
    plan, either hard-deleting one outright as a spurious "redundant" duplicate or
    resurrecting the quarantined copy into the organized tree in its place)."""
    from moonglade.backup import (build_stem_name, convert_image, embed_metadata, _ensure_db,
                                  load_catalog, PixAIError, _same_bytes, save_catalog)
    db_path = _ensure_db(out)
    meta_by_mid = {}
    for row in load_catalog(db_path):
        mid = row.get("media_id")
        if mid:
            meta_by_mid[mid] = row

    # This walker's own exclusion (named disagreement 6): the shared quarantine set
    # plus videos/ and imported/, which organize must leave alone because they are
    # not PixAI images to normalize.
    skip_dirs = QUARANTINE_EXCLUDE + ("videos", "imported")

    def _target(mid, row, ext):
        month = (row.get("created_at") or "")[:7] or "unknown-date"
        stem = build_stem_name(row.get("prompt_preview", ""), row.get("task_id", ""),
                               mid, args.name_length, args.name_sep)
        return out / month / (stem + ext)

    # Sources: every PixAI image on disk (catalog media), wherever it currently is.
    plan, in_place = [], 0
    for e in scan_library(out, kinds=("image",), exclude=skip_dirs):
        p = e.path
        if p.name.startswith("_"):
            continue                       # organize's own rule, about files not folders
        row = meta_by_mid.get(e.media_id)
        if not row or (row.get("source") or "") == "local":
            continue                       # unknown file or user import: leave it
        dst = _target(e.media_id, row, p.suffix.lower())
        if p.resolve() == dst.resolve():
            in_place += 1
            continue
        plan.append((p, dst, e.media_id, row))

    print("Organize plan: {} file(s) -> YYYY-MM/ with descriptive names; "
          "{} already in place.".format(len(plan), in_place))
    for src, dst, mid, row in plan[:6]:
        print("  {}  ->  {}".format(src.relative_to(out), dst.relative_to(out)))
    if len(plan) > 6:
        print("  ... and {} more".format(len(plan) - 6))
    if args.convert:
        print("Will also convert to {}.".format(args.convert))
    if getattr(args, "embed_metadata", False):
        print("Will embed prompt metadata into PNG/JPEG (WebP skipped).")

    if args.dry_run:
        print("\nDry run -- nothing moved. Re-run without --dry-run to apply.")
        return
    if not plan:
        print("Nothing to do -- everything already organized.")
        return

    manifest_path = _paths.decisions_path(out, ORGANIZE_MANIFEST)
    mf_new = not manifest_path.exists()
    mf = open(manifest_path, "a", newline="", encoding="utf-8")
    mw = csv.writer(mf)
    if mf_new:
        mw.writerow(["old_path", "new_path", "ts"])
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    moved = converted = embedded = skipped = deduped = 0
    catalog_updates = {}                   # media_id -> new basename
    month_index = defaultdict(list)
    _prog = getattr(args, "progress", None)

    for n, (src, dst, mid, row) in enumerate(plan):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.resolve() != src.resolve():
            # Target already holds this media. Byte-identical -> drop the redundant
            # source (this is the INVARIANT-7 protection). Differ -> keep both.
            if _same_bytes(src, dst):
                try:
                    src.unlink(); deduped += 1
                except OSError:
                    pass
            else:
                print("  KEPT both (differ): {} vs {}".format(src.name, dst.relative_to(out)))
            skipped += 1
            final = dst
        else:
            try:
                src.replace(dst)
                mw.writerow([str(src.relative_to(out)).replace("\\", "/"),
                             str(dst.relative_to(out)).replace("\\", "/"), ts])
                mf.flush()
                moved += 1
                final = dst
                catalog_updates[mid] = final.name
            except OSError as e:
                print("  move failed {} ({})".format(src.name, e))
                continue
        if args.convert:
            final, note = convert_image(final, args.convert, args.jpeg_quality,
                                        args.jpeg_bg, keep_original=args.keep_webp)
            if note == "pillow-missing":
                raise PixAIError("--convert needs Pillow:  pip install pillow")
            if note == "ok":
                converted += 1
            catalog_updates[mid] = final.name
        if getattr(args, "embed_metadata", False):
            note = embed_metadata(final, {
                "prompt": row.get("prompt_preview", ""), "task_id": row.get("task_id", ""),
                "media_id": mid, "width": row.get("width", ""), "height": row.get("height", ""),
                "created_at": row.get("created_at", ""), "status": row.get("status", ""),
                "source": "PixAI"})
            if note == "ok":
                embedded += 1
        month_index[final.parent.name].append({
            "filename": final.name, "media_id": mid, "task_id": row.get("task_id", ""),
            "prompt_preview": row.get("prompt_preview", ""), "width": row.get("width", ""),
            "height": row.get("height", ""), "created_at": row.get("created_at", ""),
            "status": row.get("status", "")})

        if _prog:
            _prog(n + 1, len(plan), 0)
        else:
            sys.stdout.write("\r  {:,}/{:,}  moved {:,}  ".format(n + 1, len(plan), moved))
            sys.stdout.flush()
    mf.close()
    if not _prog:
        print()

    for month, entries in month_index.items():
        idx_path = out / month / "_index.csv"
        new = not idx_path.exists()
        with open(idx_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["filename", "media_id", "task_id",
                                              "prompt_preview", "width", "height",
                                              "created_at", "status"])
            if new:
                w.writeheader()
            for e in entries:
                w.writerow(e)

    # Tidy up now-empty legacy batches/ folders (drop their _prompt.txt first).
    batches_root = out / "batches"
    if batches_root.exists():
        for f in batches_root.rglob("_prompt.txt"):
            try:
                f.unlink()
            except OSError:
                pass
        for d in sorted([p for p in batches_root.rglob("*") if p.is_dir()],
                        key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            batches_root.rmdir()
        except OSError:
            pass

    if catalog_updates:
        rows = load_catalog(db_path)
        for r in rows:
            if r["media_id"] in catalog_updates:
                r["filename"] = catalog_updates[r["media_id"]]
                r["batch"] = ""            # batches are gone
        save_catalog(db_path, rows)
        print("Updated {:,} catalog entries.".format(len(catalog_updates)))

    print("\nOrganized: moved {:,}, already-in-place {:,}.".format(moved, in_place))
    if deduped:
        print("Removed {:,} redundant byte-identical copies.".format(deduped))
    if args.convert:
        print("Converted to {}: {:,}.".format(args.convert, converted))
    if embedded:
        print("Embedded metadata into {:,} images.".format(embedded))
    print("Reversible manifest: {}  (run --undo-organize to revert)".format(manifest_path))
    try:      # Keeper of Order: a real (non-dry-run) organize completed
        from moonglade.gallery import telem_bump
        telem_bump("organize_runs", out_dir=out)
    except Exception:
        pass


def cmd_undo_organize(args, out):
    """Reverse the moves recorded in organize_manifest.csv (newest run first):
    each new_path is moved back to its old_path. Safe (skips already-reverted),
    then clears the manifest. Lets a re-normalize be undone if you don't like it."""
    from moonglade.backup import _ensure_db
    db_path = _ensure_db(out)
    manifest_path = _paths.decisions_path(out, ORGANIZE_MANIFEST)
    if not manifest_path.exists():
        print("No organize manifest found ({}); nothing to undo.".format(manifest_path))
        return
    with open(manifest_path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("new_path")]
    print("Reverting {} recorded move(s)...".format(len(rows)))
    if getattr(args, "dry_run", False):
        for r in rows[:8]:
            print("  {}  ->  {}".format(r["new_path"], r["old_path"]))
        print("\nDry run -- nothing moved.")
        return
    reverted = miss = 0
    for r in reversed(rows):               # undo newest first
        new_p, old_p = out / r["new_path"], out / r["old_path"]
        if old_p.exists() and not new_p.exists():
            continue                       # already reverted
        if not new_p.exists():
            miss += 1
            continue
        old_p.parent.mkdir(parents=True, exist_ok=True)
        try:
            new_p.replace(old_p)
            reverted += 1
        except OSError as e:
            print("  revert failed {} ({})".format(new_p, e))
    # The gallery resolves files by media id (find_files_for_media_id matches both
    # naming layouts), so restored files still resolve without rewriting the
    # catalog. Clear the manifest now that it's been applied.
    manifest_path.unlink()
    print("Reverted {} file(s); {} already gone. Manifest cleared.".format(reverted, miss))
