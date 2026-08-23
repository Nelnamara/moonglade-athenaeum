"""The one library scan (moonglade_gallery.py's "LIBRARY SCAN" section).

Ten walkers used to carry a private copy of the exclusion set, the `.part` skip,
the extension set and the bucket classifier, and they drifted twice (B11 taught
`_deleted/` to five of them one at a time; `_count_backup_images` only caught up
at M06). They now all ride `scan_library`/`files_for`, each asking for its own
`kinds`/`exclude`.

The centrepiece is TABLE below: one real tmp_path library holding every directory
the ten exclusion sets between them mention, plus `.part`, zero-byte, both naming
layouts, videos, imported, duplicates and a NESTED `gallery/` -- and, per former
walker BY NAME, the exact set of relative paths the scan yields under that
walker's arguments. If someone widens one caller's exclusions and not another's,
the row for the caller they forgot fails by name.

No monkeypatches, no mocks: a real tree on disk and the real walk over it.
"""
from pathlib import Path

import pytest

import moonglade_gallery as g
from moonglade_gallery import (scan_library, files_for, media_id_of, bucket_of,
                               find_files_for_media_id, MediaEntry,
                               QUARANTINE_EXCLUDE, QUARANTINE_EXCLUDE_ANYWHERE,
                               IMPORT_EXCLUDE, BRANDING_DIRNAME)


# ---------------------------------------------------------------------------
# The library. Every directory the ten exclusion sets mention, both naming
# layouts, a .part, a zero-byte file, a video, and one NESTED gallery/ -- the
# discriminator between the eight walkers that exclude the top-level subtree and
# the two that prune the name at any depth.
# ---------------------------------------------------------------------------
TREE = {
    # images/ -- the flat bucket
    "images/prompt_t1_100.png":        b"AAAA",
    "images/_hidden_101.png":          b"BBBB",   # leading _ : only organize skips it
    "images/102.gif":                  b"CCCC",   # image, but NOT embeddable
    "images/103.avif":                 b"DDDD",   # image, but NOT embeddable
    "images/empty_104.png":            b"",       # zero-byte: an interrupted download
    "images/partial_105.png.part":     b"EEEE",   # .part: nobody ever sees this
    # month buckets -- 100 lives here too, in the BARE layout
    "2024-01/100.png":                 b"AAAA",
    "2024-01/106.webp":                b"FFFF",
    "unknown-date/107.jpeg":           b"GGGG",
    # legacy batches/
    "batches/batch_a/01_108.png":      b"HHHH",
    "batches/loose_109.png":           b"IIII",   # loose in batches/: no batch dir
    # non-PixAI trees
    "videos/clip_200.mp4":             b"VVVV",
    "imported/ref_201.png":            b"JJJJ",
    # derived + quarantined
    "gallery/thumbs/100.jpg":          b"tttt",
    "_duplicates/dupe_100.png":        b"AAAA",
    "_deleted/purged_300.png":         b"KKKK",
    "branding/marks/mark_400.png":     b"LLLL",
    # a directory named gallery/ that is NOT out_dir/gallery
    "misc/nested/gallery/deep_500.png": b"MMMM",
    "misc/other_501.png":              b"NNNN",
    # a longer id ending in the digits of another: 1100 must never answer for 100
    "misc/1100.png":                   b"OOOO",
}

# Everything of kind "image" in TREE, by relative posix path (the .part is never
# in any answer, so it never appears in an expectation below).
_ALL_IMAGES = {
    "images/prompt_t1_100.png", "images/_hidden_101.png", "images/102.gif",
    "images/103.avif", "images/empty_104.png",
    "2024-01/100.png", "2024-01/106.webp", "unknown-date/107.jpeg",
    "batches/batch_a/01_108.png", "batches/loose_109.png",
    "imported/ref_201.png", "gallery/thumbs/100.jpg", "_duplicates/dupe_100.png",
    "_deleted/purged_300.png", "branding/marks/mark_400.png",
    "misc/nested/gallery/deep_500.png", "misc/other_501.png", "misc/1100.png",
}
_VIDEO = {"videos/clip_200.mp4"}
_QUARANTINED = {"gallery/thumbs/100.jpg", "_duplicates/dupe_100.png",
                "_deleted/purged_300.png"}
_NESTED_GALLERY = {"misc/nested/gallery/deep_500.png"}
_NOT_EMBEDDABLE = {"images/102.gif", "images/103.avif"}


@pytest.fixture
def library(tmp_path):
    for rel, data in TREE.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return tmp_path


def _rels(entries):
    return {str(e.rel).replace("\\", "/") for e in entries}


# ---------------------------------------------------------------------------
# THE TABLE: former walker -> the arguments it now asks for -> the exact set.
# ---------------------------------------------------------------------------
# Each row is (walker name, kwargs for scan_library, expected relative paths).
WALKER_TABLE = [
    (
        # moonglade_gallery.duplicate_groups -- Class-A duplicate review
        "gallery.duplicate_groups",
        dict(kinds=("image",), exclude=QUARANTINE_EXCLUDE),
        _ALL_IMAGES - _QUARANTINED,
    ),
    (
        # moonglade_gallery.collection_health -- the health disk walk. Videos are
        # tracked (path only) and legacy branding/ is excluded: both are this
        # caller's own choices, not the shared default.
        "gallery.collection_health",
        dict(kinds=("image", "video"),
             exclude=QUARANTINE_EXCLUDE + (BRANDING_DIRNAME,)),
        (_ALL_IMAGES - _QUARANTINED - {"branding/marks/mark_400.png"}) | _VIDEO,
    ),
    (
        # moonglade_gallery.backfill_batches -- rooted at batches/, no exclusions
        "gallery.backfill_batches",
        dict(kinds=("image",), include=("batches",), exclude=()),
        {"batches/batch_a/01_108.png", "batches/loose_109.png"},
    ),
    (
        # moonglade_backup._scan_media_files -- the audit + verify_quarantine.
        # Identical to duplicate_groups', which is the point: two callers that
        # agree now say so in one place.
        "backup._scan_media_files",
        dict(kinds=("image",), exclude=QUARANTINE_EXCLUDE),
        _ALL_IMAGES - _QUARANTINED,
    ),
    (
        # moonglade_backup.cmd_organize -- also skips videos/ and imported/,
        # because it MOVES files and those are not PixAI images to normalize.
        "backup.cmd_organize",
        dict(kinds=("image",), exclude=QUARANTINE_EXCLUDE + ("videos", "imported")),
        _ALL_IMAGES - _QUARANTINED - {"imported/ref_201.png"},
    ),
    (
        # moonglade_backup.run_import_local, INTERNAL scan (--import-local with no
        # path): the quarantine set plus legacy branding/, images and videos.
        "backup.run_import_local (internal)",
        dict(kinds=("image", "video"), exclude=IMPORT_EXCLUDE),
        (_ALL_IMAGES - _QUARANTINED - {"branding/marks/mark_400.png"}) | _VIDEO,
    ),
    (
        # moonglade_backup.run_import_local, EXTERNAL source dir: the exclusion
        # names mean nothing outside the backup root, so nothing is excluded.
        "backup.run_import_local (external)",
        dict(kinds=("image", "video"), exclude=()),
        _ALL_IMAGES | _VIDEO,
    ),
    (
        # moonglade_backup._count_backup_images -- the one walker that WANTS the
        # quarantine trees: it counts them into separate columns.
        "backup._count_backup_images",
        dict(kinds=("image",), exclude=()),
        _ALL_IMAGES,
    ),
    (
        # moonglade_backup.run_download -- the pre-network resume index. Prunes by
        # dir NAME at any depth, so the NESTED gallery/ goes too. Zero-byte is the
        # caller's own rule and is asserted separately below.
        "backup.run_download",
        dict(kinds=("image",), exclude=QUARANTINE_EXCLUDE_ANYWHERE),
        _ALL_IMAGES - _QUARANTINED - _NESTED_GALLERY,
    ),
    (
        # moonglade_similar.scan_dir -- any-depth prune AND a narrower ext set:
        # .gif and .avif are real library images that CLIP is not fed.
        "similar.scan_dir",
        dict(kinds=("embeddable",), exclude=QUARANTINE_EXCLUDE_ANYWHERE),
        _ALL_IMAGES - _QUARANTINED - _NESTED_GALLERY - _NOT_EMBEDDABLE,
    ),
]


@pytest.mark.parametrize("walker,kwargs,expected",
                         WALKER_TABLE, ids=[r[0] for r in WALKER_TABLE])
def test_walker_effective_file_set(library, walker, kwargs, expected):
    """Per former walker, by name: the EXACT set scan_library yields for it."""
    got = _rels(scan_library(library, **kwargs))
    assert got == expected, "{}: +{} -{}".format(
        walker, sorted(got - expected), sorted(expected - got))


def test_the_table_covers_every_walker_that_moved():
    """A roll-call, so a walker cannot be added to the scan without a row here."""
    named = {row[0] for row in WALKER_TABLE}
    assert named == {
        "gallery.duplicate_groups", "gallery.collection_health",
        "gallery.backfill_batches", "backup._scan_media_files",
        "backup.cmd_organize", "backup.run_import_local (internal)",
        "backup.run_import_local (external)", "backup._count_backup_images",
        "backup.run_download", "similar.scan_dir",
    }
    # The tenth walker, find_files_for_media_id, is the one-id view and gets its
    # own section below -- it does not walk the whole tree.


# ---------------------------------------------------------------------------
# files_for / find_files_for_media_id -- the indexed one-id view (walker 10)
# ---------------------------------------------------------------------------

def test_files_for_finds_both_naming_layouts(library):
    """Prefixed `*_<mid>.ext` AND bare `<mid>.ext` in one answer -- the alignment
    that stopped resume re-downloading organized month files."""
    got = {str(p.relative_to(library)).replace("\\", "/")
           for p in files_for(library, "100")}
    assert got == {"images/prompt_t1_100.png", "2024-01/100.png"}


def test_files_for_excludes_thumbnails_and_both_quarantines(library):
    """gallery/thumbs/100.jpg, _duplicates/dupe_100.png and anything under
    _deleted/ all carry a matching media_id and none of them may answer."""
    got = {str(p.relative_to(library)) for p in files_for(library, "100")}
    assert not any("gallery" in p or "_duplicates" in p or "_deleted" in p
                   for p in got)
    assert files_for(library, "300") == []          # purged: invisible


def test_files_for_is_exact_not_substring(library):
    """misc/1100.png must not answer for media_id 100 (and vice versa)."""
    assert {p.name for p in files_for(library, "100")} == {"prompt_t1_100.png",
                                                          "100.png"}
    assert [p.name for p in files_for(library, "1100")] == ["1100.png"]


def test_files_for_skips_zero_byte(library):
    """INVARIANT 3 lives HERE for the matcher: an empty file is an interrupted
    download, so resume must treat it as not-downloaded."""
    assert files_for(library, "104") == []


def test_files_for_video_kind(library):
    """already_downloaded_video's contract: same matcher, video extensions."""
    assert [p.name for p in files_for(library, "200", kinds=("video",))] == \
        ["clip_200.mp4"]
    assert files_for(library, "200") == []          # image-only by default


def test_find_files_for_media_id_is_the_named_entry_point(library):
    """The compat name every caller uses, including the `exts=` spelling."""
    assert (sorted(find_files_for_media_id(library, "100")) ==
            sorted(files_for(library, "100")))
    assert [p.name for p in find_files_for_media_id(library, "200",
                                                    exts=g._VIDEO_EXTS)] == \
        ["clip_200.mp4"]
    # include_gallery re-admits the thumbnail tree, and only that tree
    got = {str(p.relative_to(library)).replace("\\", "/")
           for p in find_files_for_media_id(library, "100", include_gallery=True)}
    assert got == {"images/prompt_t1_100.png", "2024-01/100.png",
                   "gallery/thumbs/100.jpg"}


# ---------------------------------------------------------------------------
# MediaEntry: what each caller reads off the scan instead of recomputing
# ---------------------------------------------------------------------------

def test_entry_fields(library):
    by_rel = {str(e.rel).replace("\\", "/"): e
              for e in scan_library(library, kinds=("image", "video"), exclude=())}

    e = by_rel["images/prompt_t1_100.png"]
    assert isinstance(e, MediaEntry)
    assert e.path == library / "images" / "prompt_t1_100.png"
    assert e.rel == Path("images/prompt_t1_100.png")
    assert (e.bucket, e.media_id, e.size, e.kind) == ("images", "100", 4, "image")

    assert by_rel["2024-01/106.webp"].bucket == "month"
    assert by_rel["unknown-date/107.jpeg"].bucket == "month"
    assert by_rel["batches/batch_a/01_108.png"].bucket == "batches"
    assert by_rel["batches/batch_a/01_108.png"].media_id == "108"
    assert by_rel["misc/other_501.png"].bucket == "other"
    assert by_rel["videos/clip_200.mp4"].kind == "video"
    assert by_rel["images/empty_104.png"].size == 0      # reported, not dropped


def test_bucket_of_is_the_one_classifier():
    """The classifier moonglade_backup._bucket_of now aliases, and that this
    module used to re-type inline in collection_health and duplicate_groups."""
    import moonglade_backup as core
    assert core._bucket_of is bucket_of
    assert bucket_of("images/x.webp") == "images"
    assert bucket_of("batches/some_batch/01_x.webp") == "batches"
    assert bucket_of("2023-10/x.webp") == "month"
    assert bucket_of("unknown-date/x.webp") == "month"
    assert bucket_of("randomfolder/x.webp") == "other"
    assert bucket_of(Path("2023-10") / "x.webp") == "month"   # accepts a Path too


def test_media_id_of_is_the_one_extractor():
    """INVARIANT 1. backfill_batches and moonglade_similar.scan_dir used to
    re-implement this inline; both now arrive here through the scan."""
    assert media_id_of("prompt_text_task123_999888.webp") == "999888"
    assert media_id_of("01_999888.webp") == "999888"
    assert media_id_of("999888.webp") == "999888"


# ---------------------------------------------------------------------------
# The rules that deliberately did NOT move into the scan (INVARIANT 3)
# ---------------------------------------------------------------------------

def test_part_files_are_never_yielded(library):
    """The one file rule the scan does own: `.part` is an in-flight download."""
    assert not any(".part" in r for r in
                   _rels(scan_library(library, kinds=("image",), exclude=())))


def test_zero_byte_is_reported_not_decided(library):
    """The audit MUST see the zero-byte file (so it can never pick it as a
    keeper); resume must NOT (so it re-downloads it). One walk, two answers --
    which is why `size` is reported and the rule stays at the caller."""
    audit = _rels(scan_library(library, kinds=("image",),
                               exclude=QUARANTINE_EXCLUDE))
    assert "images/empty_104.png" in audit

    resume = {str(e.rel).replace("\\", "/")
              for e in scan_library(library, kinds=("image",),
                                    exclude=QUARANTINE_EXCLUDE_ANYWHERE)
              if e.size != 0}
    assert "images/empty_104.png" not in resume


def test_leading_underscore_is_organizes_own_rule(library):
    """cmd_organize skips `_*.png`; nobody else does. It is a rule about FILES,
    so it stayed one line at the caller instead of becoming an exclusion."""
    got = _rels(scan_library(library, kinds=("image",),
                             exclude=QUARANTINE_EXCLUDE + ("videos", "imported")))
    assert "images/_hidden_101.png" in got                    # the scan yields it
    assert [r for r in got if Path(r).name.startswith("_")] == \
        ["images/_hidden_101.png"]                            # organize drops it


def test_include_restricts_to_a_subtree_and_tolerates_a_missing_one(library, tmp_path):
    """backfill_batches' shape: walk only batches/, and yield nothing (rather than
    raising) when the subtree does not exist."""
    assert _rels(scan_library(library, kinds=("image",), include=("batches",),
                              exclude=())) == {"batches/batch_a/01_108.png",
                                               "batches/loose_109.png"}
    empty = tmp_path / "no-such-library"
    empty.mkdir()
    assert list(scan_library(empty, kinds=("image",), include=("batches",))) == []
    assert list(scan_library(empty / "gone", kinds=("image",))) == []


def test_exclusion_depth_is_a_caller_choice(library):
    """Named disagreement 2, pinned from both sides: a plain name excludes the
    top-level subtree only; `**/name` prunes that name at any depth."""
    top_only = _rels(scan_library(library, kinds=("image",),
                                  exclude=QUARANTINE_EXCLUDE))
    anywhere = _rels(scan_library(library, kinds=("image",),
                                  exclude=QUARANTINE_EXCLUDE_ANYWHERE))
    assert "misc/nested/gallery/deep_500.png" in top_only
    assert "misc/nested/gallery/deep_500.png" not in anywhere
    assert top_only - anywhere == _NESTED_GALLERY


def test_embeddable_is_a_strict_subset_of_image(library):
    """Named disagreement 1: the CLIP index reads fewer extensions than the
    library holds, on purpose."""
    imgs = _rels(scan_library(library, kinds=("image",), exclude=()))
    embed = _rels(scan_library(library, kinds=("embeddable",), exclude=()))
    assert embed < imgs
    assert imgs - embed == _NOT_EMBEDDABLE


# ---------------------------------------------------------------------------
# The callers, end to end on the same tree -- the scan is what they actually use
# ---------------------------------------------------------------------------

def test_callers_ride_the_scan(library):
    """Spot-check three real callers against the table's expectations rather than
    against their own reimplementations."""
    import moonglade_backup as core

    # the audit's generator yields exactly its table row
    assert {str(rel).replace("\\", "/")
            for _p, rel, _b, _m in core._scan_media_files(library)} == \
        _ALL_IMAGES - _QUARANTINED

    # the disk counter splits the quarantine trees out instead of dropping them
    originals, _bytes, thumbs = core._count_backup_images(library)
    assert thumbs == 1                                  # gallery/thumbs/100.jpg
    assert core._count_backup_images(library).trashed == 1   # _deleted/purged_300.png
    # originals = every image except the three quarantined ones
    assert originals == len(_ALL_IMAGES - _QUARANTINED)

    # backfill drops the loose file that has no batch directory
    (library / "catalog.db").unlink(missing_ok=True)
    g.init_db(library / "catalog.db")
    g.save_catalog(library / "catalog.db",
                   [{f: "" for f in g.CATALOG_FIELDS} | {"media_id": "108"},
                    {f: "" for f in g.CATALOG_FIELDS} | {"media_id": "109"}])
    assert g.backfill_batches(library, library / "catalog.db") == 1
    rows = {r["media_id"]: r["batch"] for r in g.load_catalog(library / "catalog.db")}
    assert rows["108"] == "batch_a"
    assert rows["109"] == ""            # loose in batches/: no batch name to take
