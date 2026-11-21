"""
moonglade/history.py
====================
The generation history: the feed document and its reader (`gql`, with the refused-page and
big-page retry handling), extraction (`find_connection`, the stem and local file names, the Fix
markers, the already-downloaded checks), content hashing (`_file_sha`, `_same_bytes`,
`_same_pixels`) and the cataloged-ids readers. Moved verbatim out of moonglade/backup.py in the
3.22 split (phase 4).

The names it reads from the engine (gql_adhoc, the error classes, vlog, video_outputs and the
catalog's load_catalog/save_catalog, which tests patch there) are imported from moonglade.backup
inside each function that uses them, at call time, so a test's patch of backup's binding still
reaches them and importing this module never imports the engine.
"""
import re
import time
from pathlib import Path

from moonglade import gen_cli as _gen_cli
from moonglade.scan import _VIDEO_EXTS, find_files_for_media_id

# ---------------------------------------------------------------------------
# The history feed: one road, the full document over the ad-hoc POST
# ---------------------------------------------------------------------------
# The history feed as a full document, selecting the task summary fields every reader uses.
# It needs no saved copy on PixAI's side. The saved request it replaced (a hash of the site's
# old document) was answered from a cache part of the time and refused the rest -- about one
# read in five on the owner's install on 2026-10-25 -- and the site itself no longer sends it
# (#89). Same ids, same order, same result shape, so `find_connection` reads it.
_HISTORY_PAGE_DOC = (
    "query($userId: ID!, $last: Int, $before: String) { user(id: $userId) { id "
    "taskSummaries(last: $last, before: $before) { "
    "pageInfo { hasNextPage hasPreviousPage endCursor startCursor } "
    "edges { node { id userId status priority runnerId startedAt endAt createdAt paidCredit "
    "mediaId batchMediaIds i2vProModel characteristics artworkCount promptsPreview "
    "enrolledExperiment } } } } }")

# What a user is told when PixAI refuses a page of the feed, in plain words: the read
# changed nothing, and asking again later is all there is to do.
HISTORY_REFUSED = ("PixAI refused the history feed; nothing was changed -- try again in a "
                   "minute.")
# PixAI's passing failure on a big page: a GraphQL "Internal server error" (its database
# layer) after about 5 s, seen only at 5000 rows, 2 reads of 4, the same read answering 5 s
# later (PROBE_2026-10-25). `gql` waits this long and asks once more, then once more at
# HISTORY_FALLBACK_LAST rows, a size that answered every time it was measured.
HISTORY_RETRY_WAIT_S = 5.0
HISTORY_FALLBACK_LAST = 2000
# --count's page size (--count-page-size). 2000, not the 5000 it was: the count asks 2.5x as
# many pages, and never the size PixAI fails now and then.
COUNT_PAGE_SIZE = 2000


def _history_wait(seconds):
    """The wait before `gql` asks again after an internal-server failure. Its own name, so a
    test records the wait instead of taking it."""
    time.sleep(seconds)


def _feed_refusal(exc):
    """`(refused, internal)` for an error the feed's document read raised. `refused` is True
    when PixAI answered with GraphQL errors (`_graphql_post` hangs the list on the error; a
    bare "GraphQL error: ..." message counts too); `internal` is True when one of them is the
    passing "Internal server error". A network error, a 401, a 5xx or a non-JSON body is
    neither."""
    errors = getattr(exc, "graphql_errors", None)
    if isinstance(errors, list):
        return True, any(isinstance(err, dict) and "internal server error"
                         in str(err.get("message") or "").lower() for err in errors)
    text = str(exc)
    if text.startswith("GraphQL error"):
        return True, "internal server error" in text.lower()
    return False, False


def gql(session, variables, retries=4):
    """One page of the history feed: `_HISTORY_PAGE_DOC` POSTed through `gql_adhoc` with the
    page variables (`page_variables`), a query. Returns the `data` dict; `find_connection`
    reads the page out of it. `retries` is `gql_adhoc`'s, covering network errors and 5xx as
    it always has.

    PixAI answering with a GraphQL error is `HistoryPageRefused` (message HISTORY_REFUSED,
    chained from PixAI's own error), at once -- with one exception. Its "Internal server error"
    on a big page passes: wait HISTORY_RETRY_WAIT_S (`_history_wait`) and ask once more, and if
    that fails the same way and the page asked for more than HISTORY_FALLBACK_LAST rows, ask
    once more for HISTORY_FALLBACK_LAST rows with the same `before`. A page that comes back
    smaller than asked is still a page: every caller walks on from the returned page's own
    `pageInfo.startCursor`, never from the size it asked for. Network errors, a 401 and a 5xx
    raise as they do from `gql_adhoc`. Read-only, so asking again costs nothing but a request.

    An answer with no page in it is `HistoryPageRefused` too (`_history_answer`), never an
    empty history: a body that is not GraphQL at all -- `{"message": "Forbidden"}` at a 200,
    400 or 403, an edge's or a stale credential's own JSON -- comes back from the ad-hoc POST
    as {}, and every caller would read the missing connection as the end of the feed."""
    from moonglade.backup import gql_adhoc, HistoryPageRefused, PixAIError
    try:
        data = gql_adhoc(session, _HISTORY_PAGE_DOC, variables, retries=retries)
    except PixAIError as e:
        refused, internal = _feed_refusal(e)
        if not refused:
            raise
        if not internal:
            raise HistoryPageRefused(HISTORY_REFUSED) from e
    else:
        return _history_answer(data)
    _history_wait(HISTORY_RETRY_WAIT_S)
    try:
        data = gql_adhoc(session, _HISTORY_PAGE_DOC, variables, retries=retries)
    except PixAIError as e:
        refused, internal = _feed_refusal(e)
        if not refused:
            raise
        last = (variables or {}).get("last")
        if not internal or not isinstance(last, int) or last <= HISTORY_FALLBACK_LAST:
            raise HistoryPageRefused(HISTORY_REFUSED) from e
    else:
        return _history_answer(data)
    try:
        data = gql_adhoc(session, _HISTORY_PAGE_DOC,
                         dict(variables, last=HISTORY_FALLBACK_LAST), retries=retries)
    except PixAIError as e:
        if _feed_refusal(e)[0]:
            raise HistoryPageRefused(HISTORY_REFUSED) from e
        raise
    return _history_answer(data)


def _history_answer(data):
    """`data` when it holds a page of the feed (a connection: `edges` and `pageInfo`); else
    `HistoryPageRefused`, chained from a PixAIError that says what came back. A user with no
    generations still gets a connection, with no edges, so no real answer is refused. The
    same check the artworks list makes (`artwork_list_gql`, #88)."""
    from moonglade.backup import HistoryPageRefused, PixAIError
    if find_connection(data or {}) is None:
        raise HistoryPageRefused(HISTORY_REFUSED) from PixAIError(
            "PixAI answered, but with no history page in it")
    return data


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def find_connection(data):
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if "edges" in cur and "pageInfo" in cur:
                return cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def slug_from_prompt(prompt, max_len, sep="_"):
    """Make a filesystem-safe slug from a prompt preview.

    Removes characters Windows forbids (\\ / : * ? " < > |), collapses runs of
    punctuation/whitespace (commas etc.) into the separator, trims to max_len, and
    strips trailing dots/spaces/separators (which Windows dislikes).
    """
    if not prompt:
        return ""
    s = prompt.strip()
    # Drop anything that's not a word char, space, or hyphen; this removes the
    # forbidden set plus commas, quotes, parentheses, colons, etc.
    s = re.sub(r"[^\w\s-]", " ", s, flags=re.UNICODE)
    # Collapse whitespace/hyphen runs into the chosen separator.
    s = re.sub(r"[\s-]+", sep, s).strip(sep + ". ")
    if len(s) > max_len:
        s = s[:max_len].rstrip(sep + ". ")
    return s


def build_stem_name(prompt_preview, task_id, media_id, max_len, sep="_"):
    """<clean_prompt>_<task_id>_<media_id>, falling back gracefully if no prompt.

    The media_id is always last so resume can match on `_<media_id>` no matter
    what readable text precedes it. The task_id is the stable per-task anchor.
    """
    slug = slug_from_prompt(prompt_preview, max_len, sep)
    tid = str(task_id or "task")
    mid = str(media_id)
    parts = [p for p in (slug, tid, mid) if p]
    return sep.join(parts)


# The two region kinds POST /v2/task/fixer accepts, in the order a filename spells them out
# (so "hand then face" and "face then hand" produce the same marker).
_FIX_TAGS = ("face", "hand")


def local_media_id(path):
    """Content-addressed id for an imported (non-PixAI) file: local_<12 hex>.

    Derived from the file's BYTES. The id used to be a hash of the file's PATH, which
    let the name decide the identity -- two different pictures both landing on
    `imported/image.png` collided on the catalog row as well as on disk, and one of
    them was silently never stored. Hashing content makes that collision impossible,
    and makes the same picture imported twice from two folders recognisable as one
    picture instead of two. Returns None when the file can't be read."""
    h = _file_sha(path)
    return ("local_" + h[:12]) if h else None


_LOCAL_SUFFIX_RE = re.compile(r"(?:_local_[0-9a-f]{12})+$")


def build_local_name(path, mid):
    """<readable-stem>_<media_id><ext> -- build_stem_name()'s counterpart for a file
    with no PixAI task behind it, keeping that convention's load-bearing half: the id
    goes LAST, so anything that matches on a trailing _<media_id> treats an imported
    file exactly like a backed-up one.

    Any id already on the stem is stripped first, which is what makes this safe to run
    over its own output: without it a second pass slugs `image_local_ab12` and produces
    `image_local_ab12_local_ab12`, growing the name on every run."""
    slug = slug_from_prompt(_LOCAL_SUFFIX_RE.sub("", path.stem), 60)
    ext = path.suffix.lower()
    return "{}_{}{}".format(slug, mid, ext) if slug else "{}{}".format(mid, ext)


def migrate_local_filenames(out, db_path, thumb_dir):
    """Bring already-imported files onto the content-addressed scheme, so the library
    carries ONE naming convention rather than two. Returns (renamed, skipped).

    Curation rides along: the entire row is carried over and only media_id/filename
    change, so ratings, collections, titles and tags survive. The thumbnail is named
    after the media id, so it is renamed in step -- otherwise every migrated file
    would quietly lose its thumbnail and regenerate as a placeholder.

    Deliberately never deletes: a destination that already exists holds the same
    content (the name contains the content hash), so the row is left exactly as it
    is for a human to look at rather than resolved by removing one of them."""
    from moonglade.backup import load_catalog, save_catalog, vlog
    from moonglade.catalog import delete_from_catalog
    out = Path(out)
    thumb_dir = Path(thumb_dir)
    renamed = skipped = 0
    for r in load_catalog(db_path):
        if (r.get("source") or "") != "local":
            continue
        rel = (r.get("filename") or "").replace("\\", "/")
        # imported/ ONLY -- that folder holds files the importer itself copied in, so
        # their names are ours to choose. A file the owner dropped into videos/ or
        # anywhere else under the backup was named by him and is merely CATALOGUED in
        # place (run_import_local's in-place mode never moves anything); renaming those
        # would be this tool reaching into files it did not put there.
        if not rel.startswith("imported/"):
            continue
        src = out / rel
        if not src.exists():
            continue
        new_mid = local_media_id(src)
        if not new_mid:
            skipped += 1
            continue
        new_name = build_local_name(src, new_mid)
        old_mid = r.get("media_id") or ""
        if src.name == new_name and old_mid == new_mid:
            continue                                  # already on the new scheme
        dest = src.with_name(new_name)
        if dest != src:
            if dest.exists():
                skipped += 1                          # same content already there
                continue
            try:
                src.replace(dest)
            except OSError:
                skipped += 1                          # locked right now; next run gets it
                continue
        # Row first, old row second: a crash between them leaves a stale extra row
        # (visible, fixable) rather than no row at all for a file that just moved.
        row = dict(r)
        row["media_id"] = new_mid
        row["filename"] = str(dest.relative_to(out)).replace("\\", "/")
        save_catalog(db_path, [row])
        if old_mid and old_mid != new_mid:
            delete_from_catalog(db_path, old_mid)
            old_thumb = thumb_dir / "{}.jpg".format(old_mid)
            if old_thumb.exists():
                try:
                    old_thumb.replace(thumb_dir / "{}.jpg".format(new_mid))
                except OSError:
                    pass                              # regenerable; not worth failing over
        renamed += 1
        vlog("renamed import {} -> {}".format(rel, row["filename"]))
    return renamed, skipped


def fixer_block(task):
    """`parameters.chat.fixer` when this getTaskById task is a hand/face Fix, else None.

    PixAI turns a POST /v2/task/fixer submit into an ordinary taskKind=chat generation, so a
    Fix comes back looking exactly like an instruct Edit apart from this one sub-block -- it
    is the only thing that identifies the task family after the fact."""
    chat = ((task or {}).get("parameters") or {}).get("chat")
    fx = chat.get("fixer") if isinstance(chat, dict) else None
    return fx if isinstance(fx, dict) else None


def fix_marker(boxes):
    """'fix-face' / 'fix-hand' / 'fix-face-hand' for a Fix output's filename, read off the
    tags its boxes carried. An untagged box degrades to a plain 'fix' rather than guessing
    which region kind it was. Hyphens stay literal so the marker reads as ONE token beside
    the separator-joined parts around it."""
    tags = {str((b or {}).get("tag") or "").lower()
            for b in (boxes or []) if isinstance(b, dict)}
    return "-".join(["fix"] + [t for t in _FIX_TAGS if t in tags])


def build_fix_stem_name(source_label, boxes, task_id, media_id, max_len, sep="_"):
    """`<source-slug>_fix-face_<task_id>_<media_id>` -- the filename stem for a Fix output.

    build_stem_name cannot serve this family: a fixer task's `prompts` is a FIXED template
    PixAI writes itself ("Image 2 shows the areas in Image 1 that need fixing..."), so every
    Fix output it ever named got the same meaningless 60-character slug and a folder of them
    was unbrowsable. The readable half comes from the SOURCE image instead, and the marker
    says which kind of region was repaired.

    Two ordering rules, both load-bearing: the source slug leads, so a Fix sorts directly
    beside the image it repaired (same slug, and the source's own name continues with a
    digit while this one continues with 'f'); and media_id stays LAST, so invariant 7's
    shared `_<media_id>` matcher -- resume, already_downloaded, organize -- still finds it.
    The length cap applies to the slug only, so the marker can never be truncated away."""
    slug = slug_from_prompt(source_label, max_len, sep)
    parts = [p for p in (slug, fix_marker(boxes), str(task_id or "task"), str(media_id)) if p]
    return sep.join(parts)


def already_downloaded(root, media_id):
    """Return an existing image file for this media_id anywhere under root,
    regardless of its prompt prefix, task id, or which subfolder it's in.

    Uses the shared `find_files_for_media_id` matcher so resume recognizes BOTH
    naming layouts — prefixed `*_<mid>.*` AND bare `<mid>.*` (the single-image
    --organize month layout). Before this was aligned, bare month files were
    invisible to resume, so every re-download re-fetched them as flat files and
    organize left the flat copy orphaned -> the images/+month duplication."""
    matches = find_files_for_media_id(root, media_id)
    return matches[0] if matches else None


def already_downloaded_video(root, media_id):
    """Video-aware sibling of already_downloaded() (B16, audit 2026-07-21).

    already_downloaded() alone is a guaranteed-False no-op for videos: its default
    matcher (find_files_for_media_id's _IMAGE_EXTS) never matches .mp4/.webm/etc,
    so --sync-artworks --with-videos' resume check fired a full resolve_media
    network round trip on every single run, even for a video already on disk. Same
    shared matcher, same exact-match + quarantine-exclusion contract -- just
    _VIDEO_EXTS instead of the image-only default."""
    matches = find_files_for_media_id(root, media_id, exts=_VIDEO_EXTS)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Content hashing (shared by --audit content dedup and organize's same-bytes check)
# ---------------------------------------------------------------------------
def _file_sha(path, _chunk=1 << 20):
    """Streamed blake2b digest of a file. Returns hex str, or None on read error."""
    import hashlib
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(_chunk), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _same_bytes(a, b):
    """True if two files are byte-identical. Cheap size check first, then hash."""
    try:
        sa, sb = a.stat().st_size, b.stat().st_size
    except OSError:
        return False
    if sa != sb:
        return False
    ha = _file_sha(a)
    return ha is not None and ha == _file_sha(b)


def _same_pixels(a, b):
    """True if two images have identical pixel content, ignoring container/metadata
    differences (e.g. a PNG with embedded prompt text vs the same image without).
    Returns None if Pillow is unavailable or either file can't be decoded."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    try:
        with Image.open(a) as ia, Image.open(b) as ib:
            if ia.size != ib.size:
                return False
            ra, rb = ia.convert("RGBA"), ib.convert("RGBA")
            # Every band's extremes, not getbbox(): on an RGBA image getbbox() looks at
            # the alpha band only (Pillow 10+), so any two opaque pictures "matched" and a
            # different picture under the same id passed as a metadata-only copy.
            return all(hi == 0 for _lo, hi in ImageChops.difference(ra, rb).getextrema())
    except Exception:
        return None


def media_ids_for(node):
    """Every media id a task summary NAMES: `mediaId` plus `batchMediaIds`, deduped.

    NOT the ids the catalog is keyed by -- on a batch task `mediaId` is the composite
    preview grid and on a video task it is the poster still, and no row is keyed by
    either. Anything asking "is this already collected?" wants `cataloged_media_ids`
    below; asking it here answers "no" forever for both shapes (2026-09-07)."""
    ids = []
    if node.get("mediaId"):
        ids.append(str(node["mediaId"]))
    for b in (node.get("batchMediaIds") or []):
        if b:
            ids.append(str(b))
    return list(dict.fromkeys(ids))


def cataloged_media_ids(node):
    """The media ids this task's catalog rows are actually keyed by.

    `media_ids_for` answers a DIFFERENT question -- every media id a task names -- and the
    two sets are not the same. On a batch task `mediaId` is the composite preview grid,
    which is never one of the batch members and is never cataloged (probe 2026-09-06); on a
    video task `mediaId` is the poster STILL, while the catalog's row is keyed by the mp4's
    own media id. Anything asking "has this task already been collected?" off
    media_ids_for therefore answered "no" forever for both shapes -- which is what made the
    live mirror's catch-up relist the same tasks every five minutes and claim in the log
    they had never been mirrored (fixed 2026-09-07; the ruling that catch-up skips a task
    only when the catalog is actually missing its media is unchanged, this is the id set
    that ruling always meant).

    Reads whichever shape it is handed:

    * A full `getTaskById` result (it has `outputs`): videos via `video_outputs`, images via
      `_task_image_media` -- the same two helpers `collect_generation` catalogs from, so the
      answer is by construction the ids the rows carry.
    * A `listUserTaskSummaries` node (a `TaskSummary`: no `outputs` at all, only
      `mediaId` / `batchMediaIds` / `i2vProModel`): `batchMediaIds` when the task HAS a
      batch, else `mediaId`. That is PixAI's own frontend rule for a summary, and it lands
      on the same ids `_task_image_media` reaches from the detail. A member PixAI has
      deleted comes through as a hole in `batchMediaIds` and is dropped here, matching
      `_task_image_media` skipping a `deletedAt` member -- so a batch whose members are ALL
      deleted yields nothing and deliberately does NOT fall back to `mediaId`, exactly as
      that helper refuses to.

    A VIDEO summary returns [] -- honestly nothing, because a summary names none of the ids
    the catalog holds (only getTaskById carries the video's own media id). [] therefore
    means "this node cannot tell you", not "there is nothing to collect", and a caller that
    must decide about a video task from a summary has to ask by task id instead:
    `_watch_catchup` checks `_is_video_task_node` first and uses `get_row_by_task`."""
    from moonglade.full_meta import video_outputs
    node = node or {}
    outputs = node.get("outputs")
    if outputs is not None:                          # full task detail
        vouts, _shared = video_outputs(node)
        if vouts:
            return list(dict.fromkeys(
                str(o["video_media_id"]) for o in vouts if o.get("video_media_id")))
        return [mid for mid, _seed in _gen_cli._task_image_media(outputs)]
    if _is_video_task_node(node):                    # summary: only the poster still
        return []
    batch = node.get("batchMediaIds")
    if isinstance(batch, (list, tuple)) and len(batch) > 0:
        return list(dict.fromkeys(str(b) for b in batch if b))
    return [str(node["mediaId"])] if node.get("mediaId") else []


def _is_video_task_node(node):
    """A listing node is a VIDEO task iff it carries `i2vProModel` (set for BOTH i2v and
    reference-video -- verified across the whole feed: 100% of video tasks have it, no image
    task does). Such a node's `mediaId` is the video's poster STILL, so the image download
    path must SKIP it -- otherwise that still gets catalogued as a standalone image, a
    duplicate of the video's own poster (the "video shown as a phantom image" bug). The real
    video is backed up by run_sync_videos, which keys off this same field."""
    return bool(node.get("i2vProModel"))


def extract_meta(node):
    return {
        "task_id": node.get("id", ""),
        "created_at": node.get("createdAt", ""),
        "prompt_preview": node.get("promptsPreview", "") or "",
        "status": node.get("status", ""),
    }
