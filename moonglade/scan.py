"""
moonglade/scan.py
=================
The library scan: the one tree-walk every walker in the app rides. Moved verbatim out of
moonglade/gallery.py in the 3.21.0 split (phase 1), with `_IMAGE_EXTS`, which the kind
taxonomy below needs at import time. The section comment below predates the move.

Imports nothing from moonglade.backup or moonglade.gallery.
"""
import os
from pathlib import Path

from moonglade import paths as _paths

_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg"})


# ---------------------------------------------------------------------------
# LIBRARY SCAN -- the one tree-walk (2026-08-23)
# ---------------------------------------------------------------------------
# Ten places used to walk the library tree, each carrying a private copy of the
# exclusion set, the `.part` skip, the extension set and the bucket classifier.
# They drifted twice: B11 (audit 2026-07-21) had to teach `_deleted/` to five
# walkers one at a time, and `_count_backup_images` only caught up at M06
# (2026-07-27) -- its own docstring says so. This section is the one module they
# all ride now. It lives HERE, in the gallery, beside the SQLite catalog helpers,
# because the import direction runs one way: `moonglade.backup` imports the
# gallery at module top (see its `from moonglade.gallery import ...`), the gallery
# only imports the backup lazily inside functions, and `moonglade.similar` imports
# the gallery lazily inside `scan_dir`. Putting the scan anywhere else would need
# a new top-level module or a cycle.
#
# WHAT IS SHARED: the exclusion vocabulary, the `.part` skip, the extension /
# `kinds` taxonomy, `bucket_of`, `media_id_of`, and the traversal itself.
# WHAT IS NOT: the zero-byte rule and every caller-specific filter stay at the
# caller (INVARIANT 3) -- `scan_library` reports `size` (None on a stat failure)
# and lets each caller decide, exactly as each one decided before.
#
# THE TEN WALKERS (walker -> what it skipped -> what it asks for now):
#
#   moonglade/gallery.py
#     find_files_for_media_id   gallery/ _duplicates/ _deleted/, .part, zero-byte,
#                               _IMAGE_EXTS (or caller `exts`), exact-id
#                            -> files_for(kinds=("image",) or exts,
#                                         exclude=QUARANTINE_EXCLUDE)
#     duplicate_groups          gallery/ _duplicates/ _deleted/, .part, _IMAGE_EXTS
#                            -> scan_library(kinds=("image",),
#                                            exclude=QUARANTINE_EXCLUDE)
#     collection_health._walk   gallery/ _duplicates/ _deleted/ branding/, .part,
#                               _IMAGE_EXTS + its own video set
#                            -> scan_library(kinds=("image","video"),
#                                            exclude=QUARANTINE_EXCLUDE+(BRANDING_DIRNAME,))
#     backfill_batches          nothing (rooted at batches/), _IMAGE_EXTS
#                            -> scan_library(kinds=("image",), include=("batches",),
#                                            exclude=())
#
#   moonglade/backup.py
#     _scan_media_files         gallery/ _duplicates/ _deleted/, .part, _IMAGE_EXTS
#                            -> scan_library(kinds=("image",),
#                                            exclude=QUARANTINE_EXCLUDE)
#     cmd_organize              gallery/ _duplicates/ _deleted/ videos/ imported/,
#                               .part, leading-underscore names, _IMAGE_EXTS
#                            -> scan_library(kinds=("image",),
#                                            exclude=QUARANTINE_EXCLUDE+("videos","imported"))
#                               plus its own name.startswith("_") skip, kept at the caller
#     run_import_local          gallery/ _duplicates/ _deleted/ branding/ (internal
#                               scan only -- an EXTERNAL source dir excludes nothing),
#                               .part, _IMAGE_EXTS | _VIDEO_EXTS
#                            -> scan_library(kinds=("image","video"),
#                                            exclude=IMPORT_EXCLUDE or ())
#     _count_backup_images      counts gallery/ as thumbs and _deleted/ as trashed
#                               rather than dropping them; skips _duplicates/;
#                               .part, _IMAGE_EXTS
#                            -> scan_library(kinds=("image",), exclude=())
#                               plus a split on rel.parts[0] against the shared dirnames
#     run_download._iter_...    gallery/ _duplicates/ _deleted/ by dir NAME at any
#                               depth, .part, zero-byte, _IMAGE_EXTS
#                            -> scan_library(kinds=("image",),
#                                            exclude=QUARANTINE_EXCLUDE_ANYWHERE)
#                               plus its own zero-byte skip, kept at the caller
#
#   moonglade/similar.py
#     scan_dir                  gallery/ _duplicates/ _deleted/ by dir NAME at any
#                               depth, case-insensitively; a NARROWER ext set
#                            -> scan_library(kinds=("embeddable",),
#                                            exclude=QUARANTINE_EXCLUDE_ANYWHERE)
#
# NAMED DISAGREEMENTS -- kept as caller choices, NOT silently unified:
#
#   1. Extension set. `moonglade.similar.scan_dir` indexes only
#      {.png,.jpg,.jpeg,.webp} -- it does NOT embed `.gif` or `.avif`, which the
#      other nine walkers do read. That is the `"embeddable"` kind, deliberately a
#      subset of `"image"`, not a bug to be widened here.
#   2. Exclusion DEPTH. Eight walkers exclude the top-level subtrees
#      `out/gallery`, `out/_duplicates`, `out/_deleted` only; `run_download` and
#      `scan_dir` prune any DIRECTORY OF THAT NAME at any depth. Both survive: a
#      plain name in `exclude` is the top-level subtree, a `"**/name"` entry is the
#      any-depth prune. `QUARANTINE_EXCLUDE` and `QUARANTINE_EXCLUDE_ANYWHERE` are
#      the two spellings. (The any-depth match is case-insensitive, which is what
#      scan_dir already did; run_download's own name compare was case-sensitive,
#      a difference that cannot show up on Windows, where the two names are the
#      same directory.)
#   3. Zero-byte. Only `files_for` (so `find_files_for_media_id`, resume, and
#      `find_image_file`) and `run_download` treat a zero-byte file as not-there
#      (INVARIANT 3). The audit deliberately does not -- it wants to SEE the
#      zero-byte file so it can never pick it as a keeper (dev/tests/test_dedup.py pins
#      both halves). So the rule stays at the caller and `scan_library` reports
#      `size` instead of deciding.
#   4. Video. Only `collection_health` and `run_import_local` look at videos at
#      all; the audit, organize, dedup and resume paths are image-only, and stay so.
#   5. Legacy `branding/`. Only `collection_health` and `run_import_local` exclude
#      it. Branding moved to the app root on 2026-07-26, so on a current install
#      this excludes nothing; it is kept because an older install still has files
#      there. Adding it to the other eight would be a behaviour change, so it is
#      not added.
#   6. `cmd_organize` alone also skips `videos/`, `imported/`, and any file whose
#      name starts with `_`. The two directories are `exclude` entries; the
#      leading-underscore rule is one line at the caller, because it is a rule
#      about FILES, not about the shape of the tree.
#
# ONE MODULE, TWO TRAVERSALS. `scan_library` walks the whole tree with
# `os.scandir` and prunes excluded subtrees before descending (so the gallery's
# thousands of thumbnails are never enumerated). `files_for` answers the one-id
# question with a targeted `rglob("*<mid>.*")` instead, because it is called once
# per media id inside loops -- a full walk per id is what made resume scale
# quadratically before run_download built its index. Same rules, same helpers,
# two access paths: the SET each yields is identical, only the cost differs.
# ---------------------------------------------------------------------------
from collections import namedtuple

# The quarantine / derived-output directory names. One spelling each, shared by
# every walker and by the code that WRITES them, so a rename can never again be
# taught to some walkers and not others.
GALLERY_DIRNAME = "gallery"           # derived thumbnails + regenerable caches
DUPLICATES_DIRNAME = "_duplicates"    # matches cmd_dedup()'s own quarantine_root name
# Accidental bulk deletes should be recoverable: purges MOVE files here instead of
# destroying them (the catalog row is still removed, so the gallery stays clean).
DELETED_DIRNAME = "_deleted"
# App chrome (banner/logo/marks). Branding moved to the APP root on 2026-07-26, so
# under a current out_dir this names nothing -- kept because an install that predates
# the move still has files here, and a scan that swept them in would catalogue
# someone's banner and mascots as gallery images.
BRANDING_DIRNAME = "branding"
# The app's own folder in a library (_moonglade/): its records, the owner's decisions, every
# login's stores and the Loom -- never pictures. Every walker prunes it, so nothing in it is
# ever catalogued, counted, flagged as a stray, organized or quarantined (the Loom's frames
# and cuts included).
RECORDS_DIRNAME = _paths.LIBRARY_APP_DIRNAME

# The two spellings of "skip the derived + quarantined trees, and the app's records"
# (named disagreement 2).
QUARANTINE_EXCLUDE = (GALLERY_DIRNAME, DUPLICATES_DIRNAME, DELETED_DIRNAME, RECORDS_DIRNAME)
QUARANTINE_EXCLUDE_ANYWHERE = tuple("**/" + n for n in QUARANTINE_EXCLUDE)
# --import-local's internal scan: the three above plus legacy branding/.
IMPORT_EXCLUDE = QUARANTINE_EXCLUDE + (BRANDING_DIRNAME,)
# Web Import's per-request ceiling on uploaded parts (/api/import-local). The page sends a big
# folder in batches well under it (gallery/src/lib/importBatches.js); the route keeps it as a
# guard and reports whatever it did not take.
IMPORT_REQUEST_CAP = 1000
# collection_health()'s walk, and therefore _health_dir_key()'s stat set. Same names as
# IMPORT_EXCLUDE today; kept separate because the two would not have to move together and
# the health memo's correctness depends on THIS one matching the health walk exactly.
HEALTH_EXCLUDE = QUARANTINE_EXCLUDE + (BRANDING_DIRNAME,)

_VIDEO_EXTS = frozenset({".mp4", ".webm", ".mov", ".mkv", ".m4v"})
# What moonglade.similar's CLIP index will actually embed -- deliberately narrower
# than _IMAGE_EXTS (named disagreement 1).
_EMBED_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# The kind taxonomy. `_IMAGE_EXTS` is defined at the top of this module beside the
# other catalog constants; the other two live here because nothing outside the scan
# needs them.
SCAN_KINDS = {
    "image": _IMAGE_EXTS,
    "video": _VIDEO_EXTS,
    "embeddable": _EMBED_EXTS,
}
# ext -> the widest kind that owns it ("image" wins over the "embeddable" subset).
_KIND_BY_EXT = {}
for _k in ("image", "video", "embeddable"):
    for _e in SCAN_KINDS[_k]:
        _KIND_BY_EXT.setdefault(_e, _k)
del _k, _e

MediaEntry = namedtuple("MediaEntry", "path rel bucket media_id size kind")
MediaEntry.__doc__ = """One media file the scan found.

    path      absolute Path
    rel       Path relative to the scan root (native separators, like the
              `p.relative_to(out_dir)` every caller used to compute itself)
    bucket    bucket_of(rel) -- "images" | "batches" | "month" | "other"
    media_id  media_id_of(path) -- INVARIANT 1
    size      st_size, or None if the stat() failed. None is NOT zero: resume
              treats an unreadable stat as "probably fine, already done", and a
              genuine zero means an interrupted download (INVARIANT 3).
    kind      which entry of SCAN_KINDS matched ("image" | "video" | ...)
    """


def bucket_of(path_or_rel):
    """THE bucket classifier (was moonglade_backup._bucket_of; moonglade.organize._bucket_of is
    now an alias onto this, and the gallery used to re-type it inline twice more).
    Classifies a path RELATIVE to out_dir into its top-level bucket name:
    "images", "batches", "month" (YYYY-MM/ or unknown-date/), or "other". Feeds
    _BUCKET_PRIORITY, which decides which copy of a duplicated media_id is the
    keeper."""
    top = str(path_or_rel).replace("\\", "/").split("/")[0]
    if top == "images":
        return "images"
    if top == "batches":
        return "batches"
    if top == "unknown-date":
        return "month"
    if len(top) == 7 and top[4] == "-" and top[:4].isdigit():
        return "month"
    return "other"


def media_id_of(path):
    """Canonical media_id extraction (INVARIANT 1): the last underscore-delimited
    chunk of the filename stem. Works for every naming layout the tool produces:
    flat (`prompt_task_<mid>`), batch (`NN_<mid>`), and bare (`<mid>`).

    The two inline re-implementations (backfill_batches here, scan_dir in
    moonglade_similar.py) are gone -- both now arrive here through the scan."""
    return Path(path).stem.split("_")[-1]


def _is_under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _kind_map(kinds):
    """{ext: kind name} for a `kinds` argument.

    `kinds` is a kind name or an iterable of them (keys of SCAN_KINDS). It also
    accepts a raw iterable of ".ext" strings -- that is the compat path for
    find_files_for_media_id(exts=...), whose callers pass an extension set
    directly (e.g. already_downloaded_video's _VIDEO_EXTS)."""
    if isinstance(kinds, str):
        kinds = (kinds,)
    out = {}
    for k in kinds:
        if k.startswith("."):
            ext = k.lower()
            out.setdefault(ext, _KIND_BY_EXT.get(ext, "other"))
        else:
            for ext in SCAN_KINDS[k]:
                out[ext] = k
    return out


def _split_exclusions(exclude):
    """(top-level subtree names, any-depth dir names) -- see named disagreement 2.

    A plain "gallery" prunes out_dir/gallery only. A "**/gallery" prunes any
    directory of that name at any depth, matched case-insensitively (which is what
    moonglade.similar.scan_dir has always done, and what run_download's own
    name-based prune does in practice on Windows)."""
    tops, anywhere = [], set()
    for name in exclude:
        if name.startswith("**/"):
            anywhere.add(name[3:].lower())
        else:
            tops.append(name)
    return tops, anywhere


def scan_library(out_dir, *, kinds=("image",), include=(), exclude=QUARANTINE_EXCLUDE):
    """Walk the library tree once and yield a MediaEntry per media file.

    out_dir   the scan root. Everything (`rel`, `bucket`, `exclude`) is relative
              to it -- so --import-local can point this at an EXTERNAL folder and
              get the same rules with no exclusions.
    kinds     which extension families count. See SCAN_KINDS / _kind_map.
    include   restrict the walk to these top-level subtrees ("only look under
              batches/"). Empty = the whole tree. A named subtree that does not
              exist simply yields nothing.
    exclude   directory names to prune. Plain name = the top-level subtree;
              "**/name" = that name at any depth (named disagreement 2).

    Prunes excluded subtrees BEFORE descending, so their entries are never
    enumerated at all -- that is what made the health panel usable at 35k images
    (owner report 2026-08-06) and what keeps run_download's startup index cheap.
    Reads is_file/size straight off the DirEntry, which on Windows comes from the
    directory read itself: no per-file syscall.

    Skips `.part` temp files (INVARIANT 3). Does NOT apply the zero-byte rule --
    that one is the caller's, and `size` is reported so the caller can apply it.
    """
    root = Path(out_dir)
    kind_of = _kind_map(kinds)
    top_names, any_names = _split_exclusions(exclude)
    pruned = {os.path.normcase(str(root / n)) for n in top_names}
    starts = [str(root / n) for n in include] or [str(root)]

    for start in starts:
        stack = [start]
        while stack:
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if (os.path.normcase(e.path) not in pruned
                                        and e.name.lower() not in any_names):
                                    stack.append(e.path)
                                continue
                            if not e.is_file(follow_symlinks=False):
                                continue
                        except OSError:
                            continue
                        name = e.name
                        if name.endswith(".part"):
                            continue
                        kind = kind_of.get(os.path.splitext(name)[1].lower())
                        if kind is None:
                            continue
                        try:
                            size = e.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = None
                        p = Path(e.path)
                        rel = p.relative_to(root)
                        yield MediaEntry(p, rel, bucket_of(rel), media_id_of(name),
                                         size, kind)
            except OSError:
                continue


def files_for(out_dir, media_id, *, kinds=("image",), exclude=QUARANTINE_EXCLUDE):
    """Every on-disk file whose media_id is exactly `media_id`. The one-id view.

    BOTH naming layouts in one pass:
      * prefixed   `prompt_task_<mid>.ext` / `NN_<mid>.ext`
      * bare       `<mid>.ext`   (single-image --organize month files)
    The exact `media_id_of(p) == mid` check prevents substring collisions (a
    longer id ending in these digits).

    Zero-byte files are excluded HERE, not left to the caller, because this is the
    resume/lookup matcher and "the file exists but is empty" has to read as
    not-downloaded (INVARIANT 3): treating it as present strands the catalog row
    pointing at a dead file that no --update ever re-fetches.

    Uses a targeted glob rather than scan_library's full walk -- it is called once
    per media id inside loops, so a whole-tree walk per id is quadratic (see the
    section header, "one module, two traversals"). The rules are the same ones.
    """
    root = Path(out_dir)
    mid = str(media_id)
    kind_of = _kind_map(kinds)
    top_names, any_names = _split_exclusions(exclude)
    top_dirs = [root / n for n in top_names]
    matches = []
    for p in root.rglob("*{}.*".format(mid)):
        if p.suffix.lower() not in kind_of:
            continue
        if p.name.endswith(".part"):
            continue
        if media_id_of(p) != mid:
            continue
        if any(_is_under(p, d) for d in top_dirs):
            continue
        if any_names and any_names & {q.lower() for q in p.relative_to(root).parts[:-1]}:
            continue
        try:
            if not p.is_file() or p.stat().st_size == 0:
                continue
        except OSError:
            continue
        matches.append(p)
    return matches


def find_files_for_media_id(out_dir, media_id, include_gallery=False, exts=None):
    """All on-disk files whose media_id matches, anywhere under out_dir.

    The named entry point onto `files_for` above -- kept under this name because
    resume (`already_downloaded`), the gallery (`find_image_file`), the loom's
    video fallback and the duplicate audit all call it by it, several of them with
    an explicit `exts` set.

    `exts` defaults to `_IMAGE_EXTS` (this matcher's historical, still image-only
    default -- e.g. dev/tests/test_loom_export_bundle.py pins that video media resolves
    via a separate catalog-row fallback, NOT this matcher). Pass `exts=_VIDEO_EXTS`
    (B16, audit 2026-07-21) for a video-aware sibling -- see already_downloaded_video
    in moonglade/backup.py -- so the SAME exact-match + quarantine-exclusion
    contract applies to videos, not just images.
    """
    exclude = (QUARANTINE_EXCLUDE if not include_gallery
               else (DUPLICATES_DIRNAME, DELETED_DIRNAME, RECORDS_DIRNAME))
    return files_for(out_dir, media_id,
                     kinds=(("image",) if exts is None else exts),
                     exclude=exclude)


def find_local_video_file(out_dir, mid, row=None):
    """Resolve a catalog media_id to its local video file on disk: try the catalog's
    stored filename first, then fall back to the shared media-id matcher (SAME exact
    media_id_of(p) == mid check and _duplicates/_deleted quarantine exclusion as every
    other matcher in this file -- B17, audit 2026-07-21: a bare glob fallback used to
    have neither, so a quarantined file was a valid hit and a shorter media_id could
    match as a substring of a longer, unrelated one's filename). find_files_for_media_id
    defaults to images, hence the explicit exts=_VIDEO_EXTS. Returns a Path or None.

    Lifted out of create_app on 2026-09-26 (moved, not changed) so the CLI's
    --reference-video length lookup reads the one answer the app's _find_local_video_file
    gives its four callers. `row` is the media id's catalog row (or None / {} for "none").

    _VIDEO_EXTS, not a hand-written tuple: the local copy was missing .m4v, which
    run_import_local DOES copy in and catalog as is_video='1' (its media_exts is
    _IMAGE_EXTS | _VIDEO_EXTS). Harmless while the only callers were Loom handoff/
    duration -- a .m4v is never a generated shot -- but the detail page's existence
    check runs over a whole catalog, so the short list would have reported a perfectly
    present imported clip as missing from disk."""
    out_dir = Path(out_dir)
    vid_exts = _VIDEO_EXTS
    row = row or {}
    fn = row.get("filename") or ""
    if fn:
        cand = out_dir / fn
        # The catalog's `filename` is joined onto out_dir, so a row carrying a traversing
        # path resolves outside the library. /video-file already refuses that (relative_to
        # + send_from_directory's own safe_join), which is exactly why this branch has to
        # agree: without the check THIS resolver says "present" for a file the serving
        # route will 404, and the detail page draws a player over it and says nothing --
        # M30's own symptom, reached by a different road. `.resolve()` is the load-bearing
        # part: relative_to alone does not normalise, so `..` walks straight through it.
        if (_is_under(cand.resolve(), out_dir.resolve())
                and cand.is_file() and cand.suffix.lower() in vid_exts):
            return cand
    fallback = find_files_for_media_id(out_dir, mid, exts=vid_exts)
    return fallback[0] if fallback else None
# ---------------------------------------------------------------------------
# END LIBRARY SCAN
# ---------------------------------------------------------------------------
