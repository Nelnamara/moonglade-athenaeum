"""
moonglade/dupes.py
==================
The duplicate groups behind GET /api/duplicates and the MCP's find_duplicates: Class A (one
media id in several folders), same-seed rows and near duplicates by dHash. Moved verbatim out of
moonglade/gallery.py in the 3.21.0 split (phase 1), with `DHASH_SIZE`, which
near_duplicate_groups reads as a default argument at import time.

Imports the gallery only inside the functions that need its catalog.
"""
from moonglade import scan as _scan

DHASH_SIZE = 8  # compute_dhash()'s hash dimension: 8x8 -> 64-bit hash, 16 hex chars


def duplicate_groups(out_dir, limit=300):
    """Class-A duplicates for the gallery review browser: media_ids whose file
    exists in more than one folder bucket. Cheap (no hashing). Returns a list of
    {media_id, keeper(rel), copies:[{rel,bucket,size}]} sorted keeper-first.

    Excludes gallery/, _duplicates/, AND _deleted/ (B11, audit 2026-07-21) -- a
    locally-purged image must not be reported back as a live duplicate of its own
    quarantined self."""
    from collections import defaultdict
    prio = {"batches": 0, "month": 1, "images": 2, "other": 3}
    locs = defaultdict(list)
    for e in _scan.scan_library(out_dir, kinds=("image",), exclude=_scan.QUARANTINE_EXCLUDE):
        locs[e.media_id].append({"rel": str(e.rel), "bucket": e.bucket,
                                 "size": e.size or 0})

    groups = []
    for mid, items in locs.items():
        if len(items) > 1 and len({it["bucket"] for it in items}) > 1:
            ordered = sorted(items, key=lambda it: (prio.get(it["bucket"], 9), len(it["rel"])))
            groups.append({"media_id": mid, "keeper": ordered[0]["rel"], "copies": ordered})
            if len(groups) >= limit:
                break
    return groups


def same_seed_groups(db_path, limit=1000):
    """Class-C duplicates (2026-08-02, moonglade-internal/DECISIONS.md): catalog rows sharing the
    same non-blank (seed, prompt_full) pair -- almost certainly the same generation
    re-rolled or resubmitted. A cheap SQL GROUP BY, not a new detection algorithm; no
    filesystem access, no hashing. Returns [{seed, prompt_hash, media_ids:[...]}],
    most-duplicated first, capped at `limit` groups. `prompt_hash` is a short digest
    of the grouped prompt_full (NOT the seed's own identity) so callers get a stable,
    compact per-group key without echoing the full prompt text into an id string."""
    from moonglade.gallery import catalog
    import hashlib
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT seed, prompt_full, GROUP_CONCAT(media_id) AS ids, COUNT(*) AS n "
            "FROM catalog "
            "WHERE COALESCE(seed,'') != '' AND COALESCE(prompt_full,'') != '' "
            "GROUP BY seed, prompt_full "
            "HAVING COUNT(*) > 1 "
            "ORDER BY n DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            phash = hashlib.sha1((r["prompt_full"] or "").encode("utf-8", "ignore")).hexdigest()[:10]
            out.append({"seed": r["seed"], "prompt_hash": phash,
                        "media_ids": [m for m in (r["ids"] or "").split(",") if m]})
        return out


# Hamming distance threshold (out of 64 bits) below which two dHashes count as a
# near-duplicate pair. 10/64 (~84% bit agreement) is the commonly-cited rule of thumb
# for 64-bit perceptual hashes -- comfortably wide enough to catch recompression/
# upscaling noise (measured well under 10 in practice: see dev/tests/test_phash.py) while
# staying far from the ~32/64 (50%) two UNRELATED images land near.
NEAR_DUP_HAMMING_THRESHOLD = 10


def near_duplicate_groups(db_path, threshold=NEAR_DUP_HAMMING_THRESHOLD, hash_size=DHASH_SIZE):
    """Class-D duplicates (the perceptual-hash follow-up named in the original
    api_duplicates() docstring/DECISIONS.md): catalog rows whose dHash `phash` column
    (compute_dhash(), populated by `--backfill-phash`) is within `threshold` Hamming-
    distance bits of another row's -- catches an upscaled or recompressed copy of the
    same image, which Class B (identical_file, a byte hash) cannot, because the bytes
    genuinely differ. Image rows only (is_video='1' rows and blank-phash rows are
    skipped -- a row with no phash yet is "unknown", never treated as "no match").

    NOT a naive O(n^2) pairwise scan across the whole library (mirrors Class B's
    same-size-bucket trick in audit_collection()): the 64-bit hash is split into 4
    non-overlapping 16-bit bands, and rows are grouped by (band_index, band_value).
    Only rows that land in the SAME band bucket are ever Hamming-compared. This is a
    standard LSH ("banding") trick -- any pair within `threshold` bits of each other is
    near-certain to still agree exactly on at least one 16-bit band (a handful of
    scattered bit flips is very unlikely to touch all 4 bands at once), so real near-
    duplicates are still found; only far-apart pairs that would fail the threshold check
    anyway are skipped from ever being compared. Comparisons are deduped (a pair sharing
    2+ bands is only Hamming-checked once).

    Matching pairs are merged with union-find so a visual chain (A near B, B near C)
    lands in ONE group even if A and C individually exceed `threshold` -- same "keeper
    emerges from the group" shape the other three tiers already return, not a flat pair
    list.

    Returns [{media_ids:[...], closeness_pct}], most-similar-group first. closeness_pct
    is this tier's one deliberate departure from the other three (which carry no
    percentage/confidence by design, per DECISIONS.md) -- it is not invented: for each
    final group it takes the WORST (largest) pairwise Hamming distance among that
    group's own members (recomputed exactly now that the group is small, not estimated
    from the banding pass) and reports 100 * (1 - worst_distance / total_bits), i.e. "the
    two least-alike members in this group still agree on at least this share of the
    hash" -- a conservative, real number derived from the actual bits, never a fabricated
    confidence score."""
    from moonglade.gallery import catalog
    from collections import defaultdict
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, phash FROM catalog "
            "WHERE COALESCE(phash,'') != '' AND COALESCE(is_video,'') != '1'"
        ).fetchall()

    total_bits = hash_size * hash_size
    n_bands = 4
    band_bits = total_bits // n_bands
    band_mask = (1 << band_bits) - 1

    ints = {}
    for r in rows:
        try:
            ints[str(r["media_id"])] = int(r["phash"], 16)
        except (TypeError, ValueError):
            continue          # a corrupt/non-hex phash value -- skip rather than crash

    by_band = [defaultdict(list) for _ in range(n_bands)]
    for mid, v in ints.items():
        for b in range(n_bands):
            by_band[b][(v >> (b * band_bits)) & band_mask].append(mid)

    parent = {mid: mid for mid in ints}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, c):
        ra, rc = _find(a), _find(c)
        if ra != rc:
            parent[ra] = rc

    compared = set()
    for band in by_band:
        for mids in band.values():
            if len(mids) < 2:
                continue
            for i in range(len(mids)):
                for j in range(i + 1, len(mids)):
                    a, c = mids[i], mids[j]
                    key = (a, c) if a < c else (c, a)
                    if key in compared:
                        continue
                    compared.add(key)
                    dist = bin(ints[a] ^ ints[c]).count("1")
                    if dist <= threshold:
                        _union(a, c)

    grouped = defaultdict(set)
    for mid in ints:
        grouped[_find(mid)].add(mid)

    out = []
    for mids in grouped.values():
        if len(mids) < 2:
            continue
        mids = sorted(mids)
        worst = max(bin(ints[mids[i]] ^ ints[mids[j]]).count("1")
                    for i in range(len(mids)) for j in range(i + 1, len(mids)))
        out.append({"media_ids": mids,
                    "closeness_pct": round(100 * (1 - worst / total_bits), 1)})
    out.sort(key=lambda g: -g["closeness_pct"])
    return out
