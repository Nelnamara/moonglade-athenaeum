"""
moonglade/health.py
===================
Collection Health: the one-walk metrics behind the health dashboard, the storage breakdown
(by type, model and collection) and the health memo that keeps an overlay open a memory read.
Moved verbatim out of moonglade/gallery.py in the 3.21.0 split (phase 2).

The names it needs from the gallery (the catalog, the collection splitter, the Loom render ids,
the prompt word counter) are imported from moonglade.gallery inside each function that uses
them, never at the top, so importing this module never imports the gallery.
"""
import os
import threading
import time

from moonglade import scan as _scan


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "{:.1f} {}".format(n, unit)
        n /= 1024


def collection_health(out_dir, db_path):
    """Compute at-a-glance metrics for the health dashboard. One disk walk
    (sizes + buckets + Class-A duplicate detection) plus a few catalog queries.

    Returns a dict consumed by the /health route. Cheap (no content hashing) so
    it's safe to render on every page load.
    """
    from moonglade.gallery import catalog, loom_render_ids, _prompt_word_counter
    from collections import defaultdict, Counter

    per_bucket = Counter()
    total_files = 0
    total_bytes = 0
    on_disk_ids = set()
    on_disk_rels = set()      # relative paths of every media file (incl. videos)
    locs = defaultdict(set)   # media_id -> set of bucket names (Class A dup detection)
    dup_redundant = 0
    dup_bytes = 0
    mid_sizes = defaultdict(list)  # media_id -> [sizes] to estimate reclaimable

    # The walk is the panel's cost at scale (owner report 2026-08-06: "VERY slow" at
    # 35k images), which is why the shared scan_library PRUNES the excluded subtrees
    # (gallery/, _duplicates/, _deleted/, legacy branding/) instead of enumerating
    # their thousands of entries only to drop each one by path-prefix afterward, and
    # reads is_file/size straight off the DirEntry. branding/ is this walker's own
    # extra exclusion (named disagreement 5) and videos are its own extra kind
    # (named disagreement 4) -- both asked for here, neither imposed on the others.
    # Guarded by dev/tests/test_gallery_filters.py's existing health tests.
    #
    # HEALTH_EXCLUDE is a named constant rather than the tuple spelled inline because
    # _health_dir_key() has to prune the SAME set: the memo's disk-side signal only means
    # anything if it watches exactly the roots this walk descends into.
    size_by_rel = {}          # relative path -> bytes, images AND videos (the Storage bars)
    size_by_mid = {}          # (kind, media_id) -> bytes of its largest copy (the Storage bars)
    # Empty files, images and videos (the "Zero-byte files" tile). Counted here for free; they
    # still count in total_files and keep a row out of `missing`, exactly as before -- the
    # tile says it plainly instead of moving a number the owner already knows (scope 2+3,
    # owner question 1, option a).
    zero_byte = 0
    for e in _scan.scan_library(out_dir, kinds=("image", "video"), exclude=_scan.HEALTH_EXCLUDE):
        _rel = str(e.rel).replace("\\", "/")
        on_disk_rels.add(_rel)
        if e.size == 0:
            zero_byte += 1
        if e.size is not None:
            size_by_rel[_rel] = e.size
            _k = (e.kind, e.media_id)
            if e.size > size_by_mid.get(_k, -1):
                size_by_mid[_k] = e.size
        if e.kind != "image":
            continue          # videos: track the path only; skip image-centric stats
        if e.size is None:
            continue          # stat() failed -- same skip the per-file stat() had
        total_files += 1
        total_bytes += e.size
        per_bucket[e.bucket] += 1
        on_disk_ids.add(e.media_id)
        locs[e.media_id].add(e.bucket)
        mid_sizes[e.media_id].append(e.size)

    for mid, buckets in locs.items():
        if len(buckets) > 1:
            extra = len(mid_sizes[mid]) - 1
            dup_redundant += extra
            sizes = sorted(mid_sizes[mid])
            dup_bytes += sum(sizes[:-1])  # all but the largest counted as reclaimable

    with catalog(db_path) as con:
        def _scalar(sql):
            return con.execute(sql).fetchone()[0]
        total_rows   = _scalar("SELECT COUNT(*) FROM catalog")
        with_image   = _scalar("SELECT COUNT(*) FROM catalog WHERE filename != ''")
        with_full    = _scalar("SELECT COUNT(*) FROM catalog WHERE COALESCE(prompt_full,'') != ''")
        # prompt_full alone overstates it badly. A row can hold a prompt and a seed while
        # holding no model, steps, sampler or CFG -- so this panel read 98% on a catalog
        # where 1% of rows could say which model made them. model_id is the honest second
        # number: it comes only from a task-detail fetch, and it is what an image-view
        # upscale needs. Locally imported rows have no PixAI task and so can never carry
        # one; they are excluded rather than counted as a permanent shortfall.
        with_model   = _scalar("SELECT COUNT(*) FROM catalog WHERE COALESCE(model_id,'') != ''")
        model_base   = _scalar("SELECT COUNT(*) FROM catalog "
                               "WHERE COALESCE(source,'') != 'local'")
        rated        = _scalar("SELECT COUNT(*) FROM catalog "
                               "WHERE COALESCE(NULLIF(rating,''),'0') NOT IN ('0')")
        by_month = con.execute(
            "SELECT SUBSTR(created_at,1,7) AS m, COUNT(*) FROM catalog "
            "WHERE created_at != '' GROUP BY m ORDER BY m"
        ).fetchall()
        top_models = con.execute(
            "SELECT COALESCE(NULLIF(model_name,''), NULLIF(model_id,''), 'unknown') AS mdl, "
            "COUNT(*) AS c FROM catalog WHERE filename != '' GROUP BY mdl ORDER BY c DESC LIMIT 8"
        ).fetchall()
        # Published-artwork analytics (populated by --sync-artworks)
        published = _scalar("SELECT COUNT(*) FROM catalog WHERE is_published = '1'")
        total_likes = _scalar(
            "SELECT COALESCE(SUM(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)),0) "
            "FROM catalog WHERE is_published = '1'")
        tag_rows = con.execute(
            "SELECT art_tags FROM catalog WHERE COALESCE(art_tags,'') != ''").fetchall()
        lora_rows = con.execute(
            "SELECT loras FROM catalog WHERE COALESCE(loras,'') != ''").fetchall()
        prompt_rows = con.execute(
            "SELECT prompt_preview FROM catalog WHERE COALESCE(prompt_preview,'') != ''"
        ).fetchall()
        # catalog rows that claim a file but whose media_id isn't on disk
        cat_rows = con.execute(
            "SELECT media_id, filename FROM catalog WHERE filename != ''").fetchall()
        # every media_id the catalog knows about at all (regardless of filename) --
        # the same "already cataloged" definition run_import_local() uses, so the
        # health count and what --import-local/Import would actually do stay in sync
        catalog_ids = {mid for (mid,) in con.execute(
            "SELECT media_id FROM catalog WHERE media_id != ''").fetchall()}
        # what the Storage bars group by (Session N6): one small row per picture that has a file
        storage_rows = con.execute(
            "SELECT media_id, filename, is_video, model_name, collections FROM catalog "
            "WHERE filename != ''").fetchall()

    tag_counter = Counter()
    for (tags,) in tag_rows:
        for t in (tags or "").split(","):
            t = t.strip()
            if t:
                tag_counter[t] += 1
    top_tags = tag_counter.most_common(10)

    lora_counter = Counter()
    for (loras,) in lora_rows:
        for part in (loras or "").split(","):
            name = part.strip().rsplit(":", 1)[0].strip()  # drop ":weight"
            if name:
                lora_counter[name] += 1
    top_loras = lora_counter.most_common(10)

    # Prompt word-cloud: most common meaningful words across prompt previews. Shared with the
    # Watchword achievement via _prompt_word_counter() so the two can never drift.
    word_counter = _prompt_word_counter(prompt_rows)
    top_words = word_counter.most_common(40)

    # A row is "missing" only if NEITHER its media id is on disk (the PixAI
    # naming path) NOR its filename resolves to a real file (the imported/local
    # path, whose media_id is a synthetic local_<hash> that never matches a file).
    missing = sum(
        1 for mid, fn in cat_rows
        if (not mid or mid not in on_disk_ids)
        and (fn or "").replace("\\", "/") not in on_disk_rels)

    # Integrity job (audit 2026-07-21, Curator #9): on-disk media with NO catalog
    # row at all -- the mirror image of `missing` above. Scoped exactly like
    # on_disk_ids is scoped throughout this function (images only; gallery/
    # _duplicates/_deleted/branding already excluded from the disk walk).
    uncataloged = on_disk_ids - catalog_ids

    # The last integrity pass (--verify-library / the Panel's "Verify library integrity"):
    # a read of its integrity_report.json, never a walk of its own. None until one has run.
    try:
        from moonglade import integrity as moonglade_integrity
        _last = moonglade_integrity.read_summary(out_dir)
    except Exception:                                    # noqa: BLE001 -- Health never fails on it
        _last = None
    integrity = ({k: _last.get(k) for k in ("verified_at", "deep", "rows", "counts", "lost")}
                 if _last else None)

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_size_h": _fmt_size(total_bytes),
        "per_bucket": dict(per_bucket),
        "dup_redundant": dup_redundant,
        "dup_bytes": dup_bytes,
        "dup_bytes_h": _fmt_size(dup_bytes),
        "catalog_rows": total_rows,
        "with_image": with_image,
        "with_full_meta": with_full,
        "full_meta_pct": round(100 * with_full / with_image) if with_image else 0,
        "with_model": with_model,
        "model_pct": round(100 * with_model / model_base) if model_base else 0,
        "rated": rated,
        "missing": missing,
        "uncataloged": len(uncataloged),
        "zero_byte": zero_byte,
        "integrity": integrity,
        "by_month": [(m, c) for (m, c) in by_month],
        "top_models": [(m, c) for (m, c) in top_models],
        "published": published,
        "total_likes": total_likes,
        "top_tags": top_tags,
        "top_loras": top_loras,
        "top_words": top_words,
        "storage": storage_breakdown(storage_rows, size_by_rel, loom_render_ids(out_dir),
                                     size_by_mid),
    }


# ---------------------------------------------------------------------------
# STORAGE BREAKDOWN (Session N6). Collection Health's one "Storage used" number became three
# stacked bars: by TYPE (images, videos, Loom renders), by MODEL, and by COLLECTION. Sizes are
# the bytes each catalogued picture's file takes on disk (the health walk already stats every
# file; it just kept only the images' before). A picture whose file is not on disk is left out
# -- it takes no space we can measure -- so the bars total what is really there, catalogued
# pictures only, which can be less than the folder (an uncataloged file counts in the folder
# and in no bar).
#
# FINDING A ROW'S FILE. The catalog's `filename` is a path relative to the library only on
# newer rows (videos/..., images/..., imported/...); every older row holds the bare file name
# while the file sits in images/. Matching on `filename` alone therefore measured 263 of a
# 37,535-picture library (owner walk, 2026-09-29). So a row is found the way the rest of the
# app finds a file: its relative path first, else its media id through the walk's own
# media_id_of (INVARIANT 1), in the same kind (a video row never borrows an image's bytes).
# Both lookups come off the health walk that already ran -- no second walk, no stat per row.
# A media id on disk twice counts once, at its larger copy (the Duplicates tile's own keeper
# rule; the other copy is what Reclaimable counts).
#
#   type        an exclusive split: a Loom render (a board's shot result or a kept re-roll) is
#               "loom" whether it is a clip or a still, else "video", else "image". It is the
#               same partition `type:` searches by, so a segment's click lands on exactly it.
#   model       the model name on the row; the top four by bytes, the rest (and any picture
#               with no model recorded) folded into "Other", which is not a filter.
#   collection  hand-picked collections only (a smart one is a search, it owns no bytes). A
#               picture in two collections counts in both, so this bar can overlap and says
#               so; its segments are shares of their own sum, not of the library. Top four by
#               bytes plus "Other" for the rest.
STORAGE_TOP = 4
_STORAGE_TYPES = (("image", "Images"), ("video", "Videos"), ("loom", "Loom renders"))


def storage_breakdown(rows, size_by_rel, loom_ids, size_by_mid=None):
    """Pure: catalog rows (media_id, filename, is_video, model_name, collections), the walk's
    {relative path: bytes}, the Loom's render ids and the walk's {(kind, media_id): bytes}
    -> the payload's `storage` block. A row is measured by its relative path, else by its
    media id in its own kind (see the section comment: most rows hold a bare file name)."""
    from moonglade.gallery import _split_collections
    size_by_mid = size_by_mid or {}
    by_type = {k: [0, 0] for k, _ in _STORAGE_TYPES}          # key -> [bytes, count]
    by_model, by_coll = {}, {}                                 # name -> [bytes, count]
    total, files = 0, 0
    for r in rows:
        fn = str(r["filename"] or "").replace("\\", "/")
        mid = str(r["media_id"] or "")
        is_video = str(r["is_video"] or "") == "1"
        size = size_by_rel.get(fn)
        if size is None and mid:
            size = size_by_mid.get(("video" if is_video else "image", mid))
        if size is None:
            continue
        total += size
        files += 1
        kind = "loom" if mid in loom_ids else ("video" if is_video else "image")
        by_type[kind][0] += size
        by_type[kind][1] += 1
        name = str(r["model_name"] or "").strip()
        m = by_model.setdefault(name, [0, 0])
        m[0] += size
        m[1] += 1
        for c in _split_collections(r["collections"]):
            cc = by_coll.setdefault(c, [0, 0])
            cc[0] += size
            cc[1] += 1

    def seg(name, b, n, **extra):
        return dict({"name": name, "bytes": b, "h": _fmt_size(b), "count": n}, **extra)

    def top_plus_other(table, skip_blank):
        named = sorted(((k, v) for k, v in table.items() if not (skip_blank and not k)),
                       key=lambda kv: (-kv[1][0], kv[0].lower()))
        segs = [seg(k, v[0], v[1], other=False) for k, v in named[:STORAGE_TOP]]
        rest = named[STORAGE_TOP:]
        rb = sum(v[0] for _, v in rest) + (table.get("", [0, 0])[0] if skip_blank else 0)
        rn = sum(v[1] for _, v in rest) + (table.get("", [0, 0])[1] if skip_blank else 0)
        if rb:
            segs.append(seg("Other", rb, rn, other=True))
        return segs

    coll_segs = top_plus_other(by_coll, False)
    return {
        "total_bytes": total, "total_h": _fmt_size(total), "files": files,
        "by_type": [seg(label, by_type[k][0], by_type[k][1], key=k) for k, label in _STORAGE_TYPES],
        "by_model": top_plus_other(by_model, True),
        "by_collection": {"sum_bytes": sum(sg["bytes"] for sg in coll_segs), "segments": coll_segs},
    }


# ---------------------------------------------------------------------------
# THE HEALTH MEMO -- the same treatment achievement_metrics() got in 49a646b, applied to
# the other walk every overlay open was paying for.
#
# collection_health() walks the ENTIRE library off disk (sizes, buckets, Class-A duplicate
# detection) plus a handful of catalog queries. At 35k images that is seconds, and the owner
# reported it as "VERY slow" back on 2026-08-06. The route has had a 120s TTL cache since
# then, which helped and was wrong in two directions at once: a change made 5s ago was
# invisible for two minutes, and a first open after two idle minutes paid the full walk with
# the user watching.
#
# KEYED ON THE CATALOG FILE, NO TIME FLOOR -- the same ruling as _ACH_METRICS_CACHE, for the
# same reason (see its comment: a floor makes a real change bounded-stale, and that is what
# broke dev/tests/test_unlock_split.py's earn-then-read). Half the key is the catalog's
# (mtime_ns, size): every write to the library goes through that file, so the instant it
# changes the memo is invalid, and a catalog nobody is writing to -- which is every open
# outside a sync -- is served from memory. os.stat is microseconds; the walk is seconds.
#
# ...AND ON THE DISK, because half of what is memoized never touches the catalog. What
# collection_health() returns is not a catalog summary: total_files, total_bytes, per_bucket
# and dup_redundant/dup_bytes come off the WALK, and `missing`/`uncataloged` are the DIFF
# between the walk and the catalog. A file deleted or dropped in by hand moves every one of
# those and writes nothing to catalog.db, so a catalog-only key served a payload that was
# provably wrong until some unrelated write happened to move the db file. _health_dir_key()
# is the cheap disk-side half: the mtimes of the walk's own roots.
#
# THE PERIODIC BACKSTOP (HEALTH_MAX_AGE). Directory mtimes catch an add or a delete in the
# directories themselves, not one nested deeper (batches/<name>/x.png), and not an in-place
# rewrite that leaves a file's name alone. So the memo also carries a CEILING on age -- a
# ceiling, never a floor: a catalog write still invalidates in the same instant it lands.
# Past the ceiling the reader is still served immediately, the recompute just happens behind
# it, which is the same serve-stale path a moved key already takes.
#
# SERVE-STALE-WHILE-RECOMPUTING. When the key HAS moved, the request that notices does not
# pay for the new walk: it gets the previous payload immediately and a single background
# thread recomputes for whoever asks next. Only two callers ever block -- the first read of a
# process (nothing to serve yet) and an explicit ?fresh=1 -- and _HEALTH_BUSY makes the
# refresh single-flight, so a burst of opens cannot start a walk each.
#
# BOOT PRIME (_health_prime, called from main()). Even a perfect memo leaves the FIRST open
# of a session slow, which is the one actually noticed. Priming it off-thread just after the
# server binds makes that open a memory read too. Prime + mtime key is what makes good on the
# owner's "loaded periodically and cached" -- with no timer and no staleness window.
_HEALTH_CACHE = {"key": None, "payload": None, "at": 0.0}
_HEALTH_LOCK = threading.Lock()
_HEALTH_BUSY = {"on": False}

# How long a snapshot may be served before a recompute is kicked off behind it, EVEN when
# neither half of the key moved. Ten minutes: long enough that an idle session never pays
# the walk twice over, short enough that the drift the key cannot see (a file swapped inside
# batches/<name>/, an in-place rewrite) is bounded instead of permanent. This is the owner's
# own "loaded periodically and cached", and it is a ceiling on staleness, not a floor on
# freshness -- a catalog write still invalidates in the instant it lands.
HEALTH_MAX_AGE = 600.0


def _health_key(db_path):
    """The cheap invalidation key: what the catalog file looks like right now. None when it
    does not exist yet -- a library with no catalog is still a valid thing to report on, and
    None compares equal to None, so it memoizes like any other key."""
    try:
        st = os.stat(str(db_path))
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _health_dir_key(out_dir):
    """The cheap DISK-side key: the mtimes of the roots collection_health() actually walks.

    A directory's own mtime moves whenever an entry is added to or removed from it, so one
    scandir of out_dir plus the mtime of each immediate subdirectory the walk descends into
    (HEALTH_EXCLUDE pruned, the same set scan_library() is handed) notices a file deleted
    from or dropped into any month folder, images/, imported/ or the root itself -- exactly
    the buckets bucket_of() names and per_bucket/total_files/missing/uncataloged are built
    from. Cost is ONE directory listing plus one stat per top-level directory -- dozens of
    syscalls against a library of tens of thousands of files, and flat in that count, which
    is the whole point of not re-walking.

    THE STAT HAS TO BE os.stat(e.path), NOT e.stat(). scan_library() reads size straight off
    the DirEntry for exactly the reason that would tempt someone here -- on Windows a
    DirEntry is already populated by the directory read, so e.stat() is free. For a
    SUBDIRECTORY it is also WRONG: what NTFS hands back there is the duplicated timestamp
    copy held in the parent's index entry, and that copy is not refreshed when a file inside
    the subdirectory is added or deleted. Measured on this box: after `unlink()` of a file in
    2026-01/, os.stat("2026-01") moved and the scandir DirEntry did not. The free stat would
    have made this whole key silently never fire, which is the bug it exists to fix.

    What it does NOT see: a change nested deeper than one level (batches/<name>/x.png) or a
    same-name in-place rewrite. HEALTH_MAX_AGE is the backstop for those, not this.

    None when out_dir cannot be listed at all (a disconnected drive) -- the same shape
    _health_key uses for a missing catalog, and it memoizes the same way.
    """
    root = str(out_dir)
    top_names, any_names = _scan._split_exclusions(_scan.HEALTH_EXCLUDE)
    skip = {n.lower() for n in top_names} | set(any_names)
    try:
        marks = [os.stat(root).st_mtime_ns]
    except OSError:
        return None
    subs = []
    try:
        with os.scandir(root) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name.lower() in skip:
                        continue
                    subs.append((e.name, os.stat(e.path).st_mtime_ns))
                except OSError:
                    continue          # vanished mid-listing: the next read will see it
    except OSError:
        return None
    # Sorted so the key does not depend on the order the filesystem hands entries back.
    return (marks[0], tuple(sorted(subs)))


def _health_memo_key(out_dir, db_path):
    """Both halves. The catalog file AND the walk's roots -- either one moving invalidates."""
    return (_health_key(db_path), _health_dir_key(out_dir))


def health_snapshot(out_dir, db_path):
    """collection_health(), memoized. Reads the key BEFORE the walk and stores the payload
    under that one: a catalog (or a file) written DURING the walk therefore leaves a key that
    no longer matches, and the next reader recomputes rather than trusting a half-old
    answer."""
    key = _health_memo_key(out_dir, db_path)
    payload = collection_health(out_dir, db_path)
    with _HEALTH_LOCK:
        _HEALTH_CACHE.update(key=key, payload=payload, at=time.time())
    return payload


def _health_refresh_async(out_dir, db_path):
    """Recompute behind a stale answer, once. Returns the thread (or None when one was
    already running) so a test can join it instead of sleeping."""
    with _HEALTH_LOCK:
        if _HEALTH_BUSY["on"]:
            return None
        _HEALTH_BUSY["on"] = True

    def _run():
        try:
            health_snapshot(out_dir, db_path)
        except Exception:
            pass                      # a background nicety must never take the server down
        finally:
            with _HEALTH_LOCK:
                _HEALTH_BUSY["on"] = False
    t = threading.Thread(target=_run, daemon=True, name="moonglade-health-refresh")
    t.start()
    return t


def health_cached(out_dir, db_path, fresh=False):
    """What /api/health answers with. Five ways out, in order:
       1. ?fresh=1 -- walk now, block, store. The explicit user refresh.
       2. nothing cached at all -- the blocking walk. This is the first read of a process,
          and it is what _health_prime pre-pays off-thread at boot.
       3. the key matches and the snapshot is younger than HEALTH_MAX_AGE -- the memo, free.
       4. the key moved (catalog file OR the walk's own directories) -- hand back the STALE
          payload now and recompute behind it.
       5. the key matches but the snapshot has aged past HEALTH_MAX_AGE -- same serve-stale
          path, because drift deeper than the directory mtimes see must still be bounded."""
    if fresh:
        return health_snapshot(out_dir, db_path)
    key = _health_memo_key(out_dir, db_path)
    with _HEALTH_LOCK:
        payload = _HEALTH_CACHE["payload"]
        fresh_enough = (time.time() - _HEALTH_CACHE["at"]) <= HEALTH_MAX_AGE
        hit = payload is not None and _HEALTH_CACHE["key"] == key and fresh_enough
    if payload is None:
        return health_snapshot(out_dir, db_path)
    if hit:
        return payload
    _health_refresh_async(out_dir, db_path)
    return payload


def health_avg_file_bytes():
    """The library's average image size from the LAST Health measurement, or None before
    there is one. A memory read, never a walk: the Broken files list sizes its re-download
    estimate with it ("~9 MB"), and a cut-short file says nothing about how big it should be."""
    with _HEALTH_LOCK:
        payload = _HEALTH_CACHE["payload"]
    if not payload:
        return None
    n, total = payload.get("total_files"), payload.get("total_bytes")
    return int(total / n) if n and total else None


def _health_prime(out_dir, db_path):
    """Warm the memo off-thread at boot so the first Health open of a session is a memory
    read too. Daemon, so it can never hold up an exit; fail-soft, so a broken library still
    starts a server. Returns the thread for the test that asserts it really primes."""
    def _run():
        try:
            health_snapshot(out_dir, db_path)
        except Exception:
            pass
    t = threading.Thread(target=_run, daemon=True, name="moonglade-health-prime")
    t.start()
    return t
