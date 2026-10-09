"""moonglade.integrity -- the library integrity pass (Phase A).

Health's tiles are aggregates: a library whose files are EMPTY or TORN still reads green,
because Health counts a file that exists, whatever is in it. This pass looks at every
catalogued file and names the broken ones, one report line per broken row, and stamps when it
last ran.

    python -m moonglade --verify-library                        # quick tier
    python -m moonglade --verify-library --verify-deep          # + structural checks

  quick tier   ONE scan_library() walk of the library (sizes come free off the directory read)
               and ONE scandir of gallery/thumbs/:
                 missing          the catalog row names a file and none is on disk
                 zero-byte        the file is there and empty (an interrupted download)
                 no thumbnail /   the file is sound but gallery/thumbs/<media_id>.jpg is not
                 no poster        there (a video's poster lives at the same path)
                 zero-byte thumbnail
                 uncataloged      an image on disk with no catalog row (Health's own rule)
                 orphan thumbnail a thumbnail with no catalog row (report only; thumbnails
                                  of pictures in the Trash are not counted)
  deep tier    + a STRUCTURAL check of each sound file that never decodes a picture: it reads
               the first 16 and the last 64 bytes (an MP4 walks its top-level boxes). PNG must
               end with IEND, JPEG with EOI, a WebP must be as long as its RIFF header says, a
               GIF must end with its trailer, an MP4 must hold a `moov` box and no box may run
               past the end of the file. A file that fails is "suspect: truncated" -- never
               "corrupt": odd-but-valid files exist, and this pass does not decode to prove
               anything. A format it does not recognise is never called suspect.

A broken row that PixAI no longer has (archive-only, moonglade.gallery.is_archive_only) is
LOST: its report line says recoverable "no", because there is nothing left to re-fetch it
from. Every other broken row says "yes".

READ-ONLY. It never deletes, moves, re-downloads or rebuilds anything. The only files it
writes are its own two reports among the library's records (_moonglade/records/, beside
audit_report.csv), each replaced atomically:

  integrity_report.csv    media_id, problem, path, size, recoverable -- one line per problem
  integrity_report.json   verified_at (UTC), deep, rows checked, files walked, the counts,
                          the lost count. collection_health() reads it for Health's tiles.

Hostile file names: a cell that a spreadsheet would read as a formula is prefixed with a
quote (csv_safe), and every printed line has its control characters replaced (printable), so
a file name cannot forge a Control Panel progress line or a terminal escape.

PHASE B (Session W, the Archive Integrity Handoff) is the Broken files list in Health, built on
the report above and kept in its own section at the foot of this file: broken_list() reads the
report back for the list, and the owner's local marks (Mark lost, Keep as is) live in
integrity_marks.json among the library's decisions (_moonglade/decisions/). The list itself is read-only. The fixes it offers (a
targeted re-download, a thumbnail rebuild) are the two writes at the very foot, one function
each, with the rules they keep: an archive-only row is refused by the re-download itself, and
nothing is ever deleted or quarantined.
"""
import csv
import io
import json
import os
import struct
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from moonglade import paths as _paths

REPORT_CSV = "integrity_report.csv"
REPORT_JSON = "integrity_report.json"
REPORT_FORMAT = "moonglade-integrity"
REPORT_VERSION = 1
PRINT_LINES = 20

# The problem words, as the report line says them.
P_MISSING = "missing"
P_ZERO = "zero-byte"
P_SUSPECT = "suspect: truncated"
P_NO_THUMB = "no thumbnail"
P_NO_POSTER = "no poster"
P_ZERO_THUMB = "zero-byte thumbnail"
P_UNCATALOGED = "uncataloged"
P_ORPHAN_THUMB = "orphan thumbnail"

# Report order: the worst first, so the first lines printed are the ones that matter.
_SEVERITY = {P_MISSING: 0, P_ZERO: 1, P_SUSPECT: 2, P_NO_POSTER: 3, P_NO_THUMB: 3,
             P_ZERO_THUMB: 4, P_UNCATALOGED: 5, P_ORPHAN_THUMB: 6}
_COUNT_KEY = {P_MISSING: "missing", P_ZERO: "zero_byte", P_SUSPECT: "suspect",
              P_NO_THUMB: "missing_thumb", P_NO_POSTER: "missing_thumb",
              P_ZERO_THUMB: "zero_byte_thumb", P_UNCATALOGED: "uncataloged",
              P_ORPHAN_THUMB: "orphan_thumb"}
COUNT_KEYS = ("missing", "zero_byte", "suspect", "missing_thumb", "zero_byte_thumb",
              "uncataloged", "orphan_thumb")
_FILE_PROBLEMS = (P_MISSING, P_ZERO, P_SUSPECT)

_TAIL = 64
_MP4_MAX_BOXES = 4096


# ---------------------------------------------------------------------------
# Structural checks (the deep tier) -- read two small ranges, never decode
# ---------------------------------------------------------------------------

def _mp4_problem(path, size):
    """Walk an MP4's top-level boxes. "truncated" when a box runs past the end of the file
    or no `moov` box is found (the index a player needs; an interrupted write loses it)."""
    seen_moov = False
    pos = 0
    with open(path, "rb") as f:
        for _ in range(_MP4_MAX_BOXES):
            if pos >= size:
                break
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                break                                   # a few stray bytes at the end
            box = struct.unpack(">I", hdr[:4])[0]
            kind = hdr[4:8]
            if box == 1:                                # 64-bit size follows
                ext = f.read(8)
                if len(ext) < 8:
                    return "truncated"
                box = struct.unpack(">Q", ext)[0]
                if box < 16:
                    return None                         # malformed, not provably torn
            elif box == 0:                              # runs to the end of the file
                box = size - pos
            elif box < 8:
                return None
            if kind == b"moov":
                seen_moov = True
            if pos + box > size:
                return "truncated"
            pos += box
    return None if seen_moov else "truncated"


def structural_problem(path):
    """None when the file looks whole, "truncated" when its end is missing. Decides the
    format from the file's own first bytes, not its extension; a format it does not know,
    or a file it cannot read, is None -- this check only ever accuses on evidence."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(16)
            n = min(size, _TAIL)
            f.seek(size - n)
            tail = f.read(n)
    except OSError:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return None if b"IEND\xaeB`\x82" in tail else "truncated"
    if head.startswith(b"\xff\xd8"):
        return None if b"\xff\xd9" in tail else "truncated"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        riff = struct.unpack("<I", head[4:8])[0]
        return "truncated" if size < riff + 8 else None
    if head[:4] == b"GIF8":
        return None if tail.rstrip(b"\x00").endswith(b"\x3b") else "truncated"
    if head[4:8] == b"ftyp":
        try:
            return _mp4_problem(path, size)
        except (OSError, struct.error):
            return None
    return None


# ---------------------------------------------------------------------------
# Hostile text
# ---------------------------------------------------------------------------

def csv_safe(text):
    """A cell a spreadsheet would run as a formula gets a leading quote."""
    s = str(text)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def printable(text):
    """One printable line: control characters (line breaks, escapes) become '?', and
    anything the console cannot encode is replaced rather than raising."""
    s = "".join("?" if (ord(ch) < 32 or 127 <= ord(ch) < 160) else ch for ch in str(text))
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return s.encode(enc, "replace").decode(enc, "replace")
    except LookupError:
        return s


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_atomic(path, data):
    """Write `data` to `path` through a temp file of this writer's own (pid + a random tag), so
    two writers of one report never write into each other's temp file."""
    import uuid
    tmp = path.with_name("{}.tmp-{}-{}".format(path.name, os.getpid(), uuid.uuid4().hex[:8]))
    try:
        tmp.write_bytes(data)
        try:
            from moonglade import backup as core          # lazy: the Windows sharing-violation retry
            core._atomic_replace(tmp, path)
        except ImportError:
            os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()                         # only ever this writer's own temp file
            except OSError:
                pass


# The reports' lock: a file beside the reports, created exclusively, held while one writer
# reads and rewrites the reports (the re-check of a fix run) or writes them (a full check), so
# neither can lose the other's lines. A lock older than REPORT_LOCK_STALE_S was left by a
# process that died and is broken; a writer waits up to REPORT_LOCK_WAIT_S for a live one.
REPORT_LOCK = "integrity_report.lock"
REPORT_LOCK_STALE_S = 120
REPORT_LOCK_WAIT_S = 60


class _ReportLock:
    def __init__(self, out):
        self.path = _paths.records_path(out, REPORT_LOCK)
        self.held = False

    def __enter__(self):
        deadline = time.time() + REPORT_LOCK_WAIT_S
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except PermissionError:
                # Windows answers EACCES, not EEXIST, while another writer's lock is being
                # deleted (delete pending). That is "busy", so wait and try again, bounded by
                # the same deadline as a held lock.
                if time.time() > deadline:
                    raise TimeoutError("the integrity reports are busy")
                time.sleep(0.05)
                continue
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > REPORT_LOCK_STALE_S:
                        self.path.unlink()           # a dead writer's lock, never a live one's
                        continue
                except OSError:
                    continue                         # it went while we looked: try again
                if time.time() > deadline:
                    raise TimeoutError("the integrity reports are busy")
                time.sleep(0.05)
                continue
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            self.held = True
            return self

    def __exit__(self, *exc):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
        return False


def _trash_ids(out, g):
    """Media ids with a file in the Trash: the Trash panel builds their thumbnails in the
    same folder, so those are not orphans."""
    ids = set()
    try:
        with os.scandir(out / g.DELETED_DIRNAME) as it:
            for e in it:
                ids.add(g.media_id_of(e.name))
    except OSError:
        pass
    return ids


def _index(out, g):
    """The walk the pass decides from: ONE scan_library() of the library and ONE scandir of
    gallery/thumbs/. (by_rel, by_mid, thumbs): every media file by its relative path and by
    (kind, media_id), and every thumbnail's size by media id."""
    by_rel = {}
    by_mid = defaultdict(list)                         # (kind, media_id) -> [MediaEntry]
    for e in g.scan_library(out, kinds=("image", "video"), exclude=g.HEALTH_EXCLUDE):
        by_rel[str(e.rel).replace("\\", "/")] = e
        by_mid[(e.kind, e.media_id)].append(e)

    thumbs = {}                                        # media_id -> bytes
    try:
        with os.scandir(out / g.GALLERY_DIRNAME / "thumbs") as it:
            for e in it:
                if e.name.lower().endswith(".jpg"):
                    try:
                        if e.is_file():
                            thumbs[e.name[:-4]] = e.stat().st_size
                    except OSError:
                        continue
    except OSError:
        pass
    return by_rel, by_mid, thumbs


def _row_check(r, index, deep, gallery_dirname):
    """One catalog row against the index: (problem, path, size, best). `problem` is None
    for a sound row; `best` is the file the row was judged on (its largest copy), or None
    when there is none. The one decision both the full pass and a re-check of a few rows
    make, so the two can never disagree about what "broken" means."""
    by_rel, by_mid, thumbs = index
    mid = str(r.get("media_id") or "")
    fn = str(r.get("filename") or "").replace("\\", "/")
    is_video = str(r.get("is_video") or "") == "1"
    kind = "video" if is_video else "image"
    cands = [by_rel[fn]] if fn in by_rel else []
    for c in by_mid.get((kind, mid), ()):
        if c not in cands:
            cands.append(c)
    sized = [c for c in cands if c.size is not None]
    problem, path, size, best = None, fn, "", None
    if not cands:
        problem = P_MISSING
    elif sized:
        best = max(sized, key=lambda c: c.size)
        path, size = str(best.rel).replace("\\", "/"), best.size
        if best.size == 0:
            problem = P_ZERO
        elif deep and structural_problem(best.path):
            problem = P_SUSPECT
        elif mid not in thumbs:
            problem = P_NO_POSTER if is_video else P_NO_THUMB
            path, size = "{}/thumbs/{}.jpg".format(gallery_dirname, mid), ""
        elif thumbs[mid] == 0:
            problem = P_ZERO_THUMB
            path, size = "{}/thumbs/{}.jpg".format(gallery_dirname, mid), 0
    return problem, path, size, best


def _line_for(r, check, g):
    """A report line for a row whose check found a problem, or None for a sound row."""
    problem, path, size, _best = check
    if not problem:
        return None
    gone = problem in _FILE_PROBLEMS and g.is_archive_only(r)
    return (str(r.get("media_id") or ""), problem, path, size, "no" if gone else "yes")


def verify_library(out_dir, db_path, deep=False, progress=None):
    """Run the pass, write both reports, return the summary (the JSON document) with the
    report lines under "lines" as (media_id, problem, path, size, recoverable) tuples."""
    from moonglade import gallery as g                     # lazy: the catalog verbs and the walk
    out = Path(out_dir)
    rows = g.integrity_rows(db_path) if Path(db_path).exists() else []
    index = _index(out, g)
    by_rel, by_mid, thumbs = index

    lines = []
    catalog_ids = set()
    lost = 0
    with_file = [r for r in rows if str(r.get("filename") or "").strip()]
    total = len(with_file)
    step = max(1, total // 200)
    for r in rows:
        if r.get("media_id"):
            catalog_ids.add(str(r["media_id"]))
    for done, r in enumerate(with_file, 1):
        line = _line_for(r, _row_check(r, index, deep, g.GALLERY_DIRNAME), g)
        if line:
            lost += 1 if line[4] == "no" else 0
            lines.append(line)
        if progress and (done % step == 0 or done == total):
            progress(done, total)

    # Uncataloged: Health's own rule -- an image media id on disk that no row names.
    disk_images = defaultdict(list)
    for (k, m), entries in by_mid.items():
        if k == "image":
            disk_images[m].extend(e for e in entries if e.size is not None)
    for m in sorted(set(disk_images) - catalog_ids):
        if not disk_images[m]:
            continue
        e = sorted(disk_images[m], key=lambda x: str(x.rel))[0]
        lines.append((m, P_UNCATALOGED, str(e.rel).replace("\\", "/"), e.size, "yes"))

    trash = _trash_ids(out, g)
    for m in sorted(set(thumbs) - catalog_ids - trash):
        lines.append((m, P_ORPHAN_THUMB, "{}/thumbs/{}.jpg".format(g.GALLERY_DIRNAME, m),
                      thumbs[m], "yes"))

    lines.sort(key=lambda ln: (_SEVERITY[ln[1]], ln[0], ln[2]))
    summary = {
        "format": REPORT_FORMAT, "version": REPORT_VERSION,
        "verified_at": _utc_now(), "deep": bool(deep),
        "rows": total, "files": len(by_rel),
        "counts": _counts(lines), "lost": lost, "report": REPORT_CSV,
    }
    with _ReportLock(out):
        _write_reports(out, lines, summary)
    return dict(summary, lines=lines)


def _counts(lines):
    counts = {k: 0 for k in COUNT_KEYS}
    for ln in lines:
        counts[_COUNT_KEY[ln[1]]] += 1
    return counts


def _write_reports(out, lines, summary):
    """Both reports, each replaced atomically: the CSV of `lines`, then the JSON summary."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["media_id", "problem", "path", "size", "recoverable"])
    for mid, problem, path, size, rec in lines:
        w.writerow([csv_safe(mid), problem, csv_safe(path), size, rec])
    _write_atomic(_paths.records_path(out, REPORT_CSV), buf.getvalue().encode("utf-8"))
    _write_atomic(_paths.records_path(out, REPORT_JSON),
                  json.dumps(summary, indent=2, sort_keys=True).encode("utf-8"))


def read_summary(out_dir):
    """The last run's integrity_report.json, or None when there is none (or it is not one).
    A file read, never a walk: Health calls this on every recompute."""
    try:
        doc = json.loads(_paths.records_path(out_dir, REPORT_JSON, make=False)
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(doc, dict) or doc.get("format") != REPORT_FORMAT:
        return None
    if not isinstance(doc.get("counts"), dict) or not doc.get("verified_at"):
        return None
    return doc


def _fmt_size(n):
    if n == "" or n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "{:.0f} {}".format(n, unit) if unit == "B" else "{:.1f} {}".format(n, unit)
        n /= 1024


def run_cli(out_dir, db_path, deep=False, progress=None):
    """--verify-library: run the pass and print the summary and the first report lines,
    which is what the Control Panel's log shows."""
    out = Path(out_dir)
    print("Verifying library integrity ({})...".format(
        "quick + structural checks" if deep else "quick checks"), flush=True)
    rep = verify_library(out, db_path, deep=deep, progress=progress)
    c = rep["counts"]
    print("\n{} catalogued files checked, {} files on disk, verified {}".format(
        rep["rows"], rep["files"], rep["verified_at"]))
    print("  missing files           {:,}{}".format(
        c["missing"], "  ({} lost: PixAI no longer has them)".format(rep["lost"]) if rep["lost"] else ""))
    print("  zero-byte files         {:,}".format(c["zero_byte"]))
    if deep:
        print("  suspect (truncated)     {:,}".format(c["suspect"]))
    else:
        print("  suspect (truncated)     not checked (add --verify-deep)")
    print("  missing thumbnails      {:,}".format(c["missing_thumb"]))
    print("  zero-byte thumbnails    {:,}".format(c["zero_byte_thumb"]))
    print("  uncataloged files       {:,}".format(c["uncataloged"]))
    print("  orphan thumbnails       {:,}".format(c["orphan_thumb"]))
    lines = rep["lines"]
    print("\nReport -> {} ({} line{})".format(REPORT_CSV, len(lines), "" if len(lines) == 1 else "s"))
    for mid, problem, path, size, rec in lines[:PRINT_LINES]:
        print(printable("  {}  {}  {}  {}  recoverable: {}".format(
            mid, problem, path, _fmt_size(size), rec)))
    if len(lines) > PRINT_LINES:
        print("  ... {} more in {}".format(len(lines) - PRINT_LINES, REPORT_CSV))
    print("Nothing was changed: this pass only reads.")
    return rep


# ---------------------------------------------------------------------------
# Phase B: the Broken files list (Session W, Archive Integrity Handoff)
# ---------------------------------------------------------------------------
#
# The list is the report above, read back, with what a row needs to draw and act:
#   kind    the chip it sits under -- "zero" (Zero-byte), "thumb" (Thumbnail: no thumbnail,
#           no poster, an empty thumbnail) or "suspect" (Suspect). Lost cuts across them.
#           "missing" (the file is nowhere on disk) has no chip of its own: it shows under All,
#           and under Lost when PixAI no longer has it (owner's ruling on the 2026-10-04 fix
#           round -- the drawn chips stay as they are).
#   state   the pill: "recoverable", "suspect" (still recoverable, drawn peach) or "lost".
#   action  the one fix that applies: "redownload" (a missing, empty or cut-short file PixAI
#           still has), "rebuild" (a thumbnail, local work), or None (a LOST row has none).
#
# LOST is decided from the catalog NOW, not from the report's recoverable column: the
# archive-only flag is rewritten at every reconcile, so a file PixAI lists again becomes
# RECOVERABLE without a new check. A row the owner marked lost is LOST whatever PixAI says.
#
# A missing file's size is the catalog's expected size where it is known; the catalog keeps no
# byte size today, so its row says "size unknown" and Fix all's estimate counts the library's
# average for it.

MARKS_FILE = "integrity_marks.json"
MARKS_FORMAT = "moonglade-integrity-marks"
# Mark lost: "this one is gone, stop counting it" (any broken row).
# Keep as is: "I've seen it" on a LOST row; it lapses if PixAI lists the file again.
MARKS = ("lost", "kept")

KIND_ZERO, KIND_THUMB, KIND_SUSPECT, KIND_MISSING = "zero", "thumb", "suspect", "missing"
LIST_KIND = {P_ZERO: KIND_ZERO, P_SUSPECT: KIND_SUSPECT, P_NO_THUMB: KIND_THUMB,
             P_NO_POSTER: KIND_THUMB, P_ZERO_THUMB: KIND_THUMB, P_MISSING: KIND_MISSING}
REFETCH_PROBLEMS = _FILE_PROBLEMS                   # missing, zero-byte, suspect
REBUILD_PROBLEMS = (P_NO_THUMB, P_NO_POSTER, P_ZERO_THUMB)
_STATE_RANK = {"recoverable": 0, "suspect": 1, "lost": 2}
_REPORT_HEAD = ["media_id", "problem", "path", "size", "recoverable"]

_marks_lock = threading.Lock()


def _csv_unsafe(text):
    """csv_safe() undone: the quote it put in front of a formula-looking cell comes off."""
    s = str(text)
    return s[1:] if s[:1] == "'" and s[1:2] in ("=", "+", "-", "@", "\t", "\r") else s


def read_lines(out_dir):
    """The last check's report lines, as (media_id, problem, path, size, recoverable) with
    size an int ("" when the report has none). [] when there is no report."""
    try:
        text = _paths.records_path(out_dir, REPORT_CSV, make=False).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != _REPORT_HEAD:
        return []
    lines = []
    for r in rows[1:]:
        if len(r) != 5:
            continue
        mid, problem, path, size, rec = r
        # isascii() too: "²".isdigit() is True and int("²") raises
        lines.append((_csv_unsafe(mid), problem, _csv_unsafe(path),
                      int(size) if size.isascii() and size.isdigit() else "", rec))
    return lines


def read_marks(out_dir):
    """{media_id: {"mark": "lost" | "kept", "at": utc}} -- the owner's local flags."""
    try:
        doc = json.loads(_paths.decisions_path(out_dir, MARKS_FILE, make=False)
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    marks = doc.get("marks") if isinstance(doc, dict) else None
    if not isinstance(marks, dict):
        return {}
    return {str(k): v for k, v in marks.items()
            if isinstance(v, dict) and v.get("mark") in MARKS}


def set_mark(out_dir, media_id, mark):
    """Set (or with "" clear) one row's local mark and return the mark it had before ("" for
    none), which is what Undo sends back. Writes integrity_marks.json atomically and touches
    nothing else: no file, no catalog row, no report."""
    mid = str(media_id or "").strip()
    if not mid:
        raise ValueError("no media id")
    if mark not in ("",) + MARKS:
        raise ValueError("unknown mark {!r}".format(mark))
    with _marks_lock:
        marks = read_marks(out_dir)
        prev = (marks.get(mid) or {}).get("mark", "")
        if mark:
            marks[mid] = {"mark": mark, "at": _utc_now()}
        else:
            marks.pop(mid, None)
        doc = {"format": MARKS_FORMAT, "marks": marks}
        _write_atomic(_paths.decisions_path(out_dir, MARKS_FILE),
                      json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
    return prev


def reconciled_at(out_dir):
    """When the last reconcile (moonglade.backup.run_reconcile_deleted) rewrote the
    archive-only flags, or None before the first stamped one."""
    from moonglade import backup as core                  # lazy, like _write_atomic's
    try:
        doc = json.loads(_paths.records_path(out_dir, core.RECONCILE_STAMP, make=False)
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    at = doc.get("reconciled_at") if isinstance(doc, dict) else None
    return at if isinstance(at, str) and at else None


def listed_ids(out_dir):
    """The media ids the Broken files list can show (the report's list-kind lines)."""
    return {ln[0] for ln in read_lines(out_dir) if ln[1] in LIST_KIND}


def _gone_as_of(row, rec_at):
    """The date a LOST row's line names: PixAI's own date when it dropped this one image,
    else the last reconcile that found its task gone. None when neither is known."""
    cd = str(row.get("cloud_deleted_at") or "").strip()
    if cd:
        return cd[:10]
    if str(row.get("deleted_remote") or "").strip() == "1" and rec_at:
        return rec_at[:10]
    return None


def _safe_id(mid):
    """A media id that can be a file name (a thumbnail's): no separators, no dot names."""
    return bool(mid) and mid not in (".", "..") and not any(c in mid for c in "/\\:")


def _thumb_present(thumbs_dir, mid):
    if not _safe_id(mid):
        return False
    try:
        return (thumbs_dir / (mid + ".jpg")).stat().st_size > 0
    except OSError:
        return False


def broken_list(out_dir, db_path, avg_bytes=None):
    """Health's Broken files list, from the last check's report. Read-only.

    Returns {verified_at, deep, rows, counts, broken, lost, fix}:
      rows    one dict per row, in the handoff's order (recoverable, then suspect, then
              lost; newest first within each): media_id, problem, kind, path, size, state,
              action, archive_only, mark, thumb, is_video, created_at, gone_as_of.
      counts  per chip: all, zero, thumb, suspect, lost.
      broken  rows that are not LOST; lost: rows that are.
      fix     what "Fix all recoverable" would do: the redownload and rebuild ids (never a
              LOST row, never an archive-only one), the lost count it leaves alone, and
              redownload_bytes, an estimate (the cut-short file's own size or the library's
              average file size, `avg_bytes`, whichever is larger), None without an average.
    """
    from moonglade import gallery as g                     # lazy: the catalog verbs
    out = Path(out_dir)
    summary = read_summary(out)
    lines = [ln for ln in read_lines(out) if ln[1] in LIST_KIND]
    ids = list(dict.fromkeys(ln[0] for ln in lines))
    catalog = ({str(r["media_id"]): r for r in g.rows_for_media_ids(db_path, ids)}
               if ids and Path(db_path).exists() else {})
    marks = read_marks(out)
    rec_at = reconciled_at(out)
    thumbs_dir = out / g.GALLERY_DIRNAME / "thumbs"

    rows = []
    for mid, problem, path, size, _rec in lines:
        r = catalog.get(mid)
        if r is None:
            continue                                  # gone from the catalog since the check
        archive = g.is_archive_only(r)
        mark = (marks.get(mid) or {}).get("mark", "")
        refetch = problem in REFETCH_PROBLEMS
        lost = (refetch and archive) or mark == "lost"
        state = "lost" if lost else ("suspect" if problem == P_SUSPECT else "recoverable")
        rows.append({
            "media_id": mid, "problem": problem, "kind": LIST_KIND[problem],
            "path": path, "size": size, "state": state,
            "action": None if lost else ("redownload" if refetch else "rebuild"),
            "archive_only": archive,
            # "kept" only means something while the row is LOST; it lapses with the flag
            "mark": mark if (mark == "lost" or (mark == "kept" and lost)) else "",
            "thumb": _thumb_present(thumbs_dir, mid),
            "is_video": str(r.get("is_video") or "") == "1",
            "created_at": str(r.get("created_at") or ""),
            "gone_as_of": _gone_as_of(r, rec_at) if (archive and refetch) else None,
        })
    rows.sort(key=lambda x: (x["created_at"], x["media_id"]), reverse=True)
    rows.sort(key=lambda x: _STATE_RANK[x["state"]])  # stable: newest first inside each

    counts = {"all": len(rows), KIND_ZERO: 0, KIND_THUMB: 0, KIND_SUSPECT: 0, KIND_MISSING: 0,
              "lost": 0}
    for x in rows:
        counts[x["kind"]] += 1
        counts["lost"] += 1 if x["state"] == "lost" else 0
    fixable = [x for x in rows if x["action"] and not x["archive_only"]]
    redl = [x for x in fixable if x["action"] == "redownload"]
    est = (sum(max(int(x["size"] or 0), int(avg_bytes)) for x in redl)
           if avg_bytes else None)
    return {
        "verified_at": (summary or {}).get("verified_at"),
        "deep": bool((summary or {}).get("deep")),
        "rows": rows, "counts": counts,
        "broken": counts["all"] - counts["lost"], "lost": counts["lost"],
        "fix": {"redownload": [x["media_id"] for x in redl],
                "rebuild": [x["media_id"] for x in fixable if x["action"] == "rebuild"],
                "lost": counts["lost"], "redownload_bytes": est},
    }


# ---------------------------------------------------------------------------
# Phase B: the fixes (the targeted runner)
# ---------------------------------------------------------------------------
#
# Two writes, one function each, so a reader can audit them on their own:
#
#   redownload_one  a missing, empty or cut-short file PixAI still has. THE RULE comes first: a row
#                   PixAI no longer has (archive-only) is refused here, from the catalog,
#                   whatever the caller asked -- it is the only copy anywhere, and this
#                   function never touches it. READ_ONLY comes next, before any network.
#                   Then the app's own single-media path (moonglade.backup.resolve_media +
#                   download; for a video, media_file_gql's fileUrl + download, the way the
#                   backup's own sync fetches clips), ONE attempt, of the FULL-SIZE file only (never resolve_media's
#                   thumbnail fallback), into a staging file under gallery/. Only when the new
#                   bytes are a whole file of the same kind as the broken one (a format this
#                   module recognises from its first bytes, and the structural check passes),
#                   the size the catalog records for the picture, and -- for a cut-short file --
#                   at least as big as what is there, does an atomic replace put them over it,
#                   keeping its name -- and
#                   only when that file's own name carries this row's media id, so an odd
#                   catalog row can never put one picture over another's file. A
#                   MISSING file has no broken file to replace: its destination is the
#                   catalog's own path, decided in ONE place, missing_target(), and refused
#                   before anything is fetched unless it resolves strictly inside the library.
#   rebuild_one     a missing or empty thumbnail: the gallery's own make_thumbnail (a video's
#                   poster: make_video_thumbnail), local only, no network, READ_ONLY or not.
#
# NOTHING IS DELETED OR QUARANTINED. The broken file is only ever replaced by a verified
# whole one; a re-download that fails or does not check out leaves it exactly as it was. The
# one thing removed is this module's own staging file, which nothing else ever saw.

STAGING_DIRNAME = "refetch-staging"        # under gallery/, which every library walk prunes

_FORMAT_OF_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp",
                  ".gif": "gif", ".mp4": "mp4", ".m4v": "mp4", ".mov": "mp4"}

# The plain words a refused or failed row shows (peach, never ruby).
WORDS = {
    "archive_only": "PixAI no longer has this picture, so there's no copy left to re-download.",
    "read_only": "Read-only mode is on, so files won't be re-downloaded.",
    "not_in_catalog": "This picture isn't in the catalog any more.",
    "bad_path": "Couldn't re-download. The catalog's path for this file isn't a safe place inside the library, so nothing was written.",
    "occupied": "Couldn't re-download. Something else is already at this file's path, so nothing was written.",
    "marked_lost": "You marked this file lost.",
    "not_listed": "This file isn't on the Broken files list.",
    "no_file": "Couldn't re-download. PixAI didn't return the file.",
    "unverified": "Couldn't re-download. The new copy didn't check out, so the old file was left as it is.",
    "type_differs": "Couldn't re-download. PixAI sent a different kind of file, so the old one was left as it is.",
    "unknown_type": "This kind of file can't be re-downloaded here.",
    "file_broken": "The file itself is broken, so its thumbnail can't be rebuilt from it.",
    "not_this_picture": "The file the catalog names for this picture belongs to another picture, so nothing was changed.",
    "changed": "This file has changed since the check. Run the check again.",
    "small_copy": "PixAI only has a small copy; nothing changed.",
    "size_differs": "Couldn't re-download. PixAI's copy isn't this picture's size, so the old file was left as it is.",
    "smaller": "Couldn't re-download. PixAI's copy is smaller than the cut-short file here, so the old file was left as it is.",
    "rebuild_failed": "Couldn't rebuild the thumbnail.",
}


def _result(mid, action, ok=True, refused="", error="", note="", nbytes=0):
    return {"media_id": mid, "action": action, "ok": ok, "refused": refused,
            "error": error or (WORDS.get(refused, "") if refused else ""),
            "note": note, "bytes": nbytes}


def _format_of(path):
    """The media format a file's own first bytes say it is, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] == b"GIF8":
        return "gif"
    if head[4:8] == b"ftyp":
        return "mp4"
    return None


def verified_whole(path):
    """True only for a file that is not empty, is a format recognised from its own first
    bytes, and passes the structural check. Stricter than structural_problem(), which lets an
    unknown format through: new bytes have to prove they are a picture before they replace
    anything (a 200 that is an error page is not "unknown, so fine")."""
    try:
        if os.path.getsize(path) <= 0:
            return False
    except OSError:
        return False
    return _format_of(path) is not None and structural_problem(path) is None


def missing_target(out_dir, row):
    """WHERE A RE-DOWNLOADED MISSING FILE GOES -- the one place that decides it. Returns
    (path, "") or (None, reason), reason "bad_path" or "occupied". Pure path work: it reads the
    disk only to resolve links and to see whether something is already there, and writes nothing.

    The destination is the catalog row's own `filename`. The backup records most pictures by
    bare file name and keeps them in images/ (a video in videos/), so a bare name goes back
    there; a name with folders keeps its folders. It is refused unless every rule holds:
      1. a relative path: no drive or ':' anywhere, no leading '/', no '..' part, no NUL,
         and no part that ends in a dot or a space (Windows strips those, so "branding./x" would
         be checked as one folder and written into another);
      2. resolved (links followed), strictly inside the library root;
      3. not inside a tree every library walk prunes (gallery/, _duplicates/, _deleted/,
         branding/) -- a file put there would never be found again;
      4. an extension the re-download knows how to check;
      5. a file name that carries this row's media id, so the file is found as this picture
         again and never lands under another picture's name.
    "occupied": something is already at that path. It is never overwritten."""
    from moonglade import gallery as g
    mid = str(row.get("media_id") or "").strip()
    raw = str(row.get("filename") or "").strip().replace("\\", "/")
    if not mid or not raw or "\x00" in raw or ":" in raw or raw.startswith("/"):
        return None, "bad_path"                                        # rule 1
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or ".." in parts or any(p.endswith((".", " ")) for p in parts):
        return None, "bad_path"                                        # rule 1
    if len(parts) == 1:
        parts = ["videos" if str(row.get("is_video") or "") == "1" else "images"] + parts
    root = Path(out_dir).resolve()
    target = root.joinpath(*parts).resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        return None, "bad_path"                                        # rule 2
    if not rel.parts:
        return None, "bad_path"                                        # rule 2: the root itself
    pruned = {os.path.normcase(n) for n in g.HEALTH_EXCLUDE}
    if os.path.normcase(rel.parts[0]) in pruned:
        return None, "bad_path"                                        # rule 3
    if target.suffix.lower() not in _FORMAT_OF_EXT:
        return None, "bad_path"                                        # rule 4
    if g.media_id_of(target) != mid:
        return None, "bad_path"                                        # rule 5
    if target.exists() or target.is_symlink():
        return None, "occupied"
    return target, ""


# The variants resolve_media can pick that ARE the picture at full size. Its THUMBNAIL and
# STILL_THUMBNAIL fallbacks are small copies and never replace an original (review finding 4).
FULL_SIZE_VARIANTS = ("PUBLIC", "ORIGINAL", "ORIG", "FULL")


def _full_size_url(core, session, row, mid):
    """(url, "") for the picture's full-size file, or (None, reason): "no_file" when PixAI
    returns nothing, "small_copy" when all it lists is a thumbnail.

    A VIDEO is read the way the backup's own sync reads one (review finding 5): /v1/media lists
    no URL for a video, so resolve_media can never find it; the GraphQL media object carries the
    mp4 itself in `fileUrl` (moonglade.backup.media_file_gql). That file has no thumbnail
    variants -- it is the clip."""
    if str(row.get("is_video") or "") == "1":
        url = (core.media_file_gql(session, mid) or {}).get("fileUrl")
        return (url, "") if url else (None, "no_file")
    url, info = core.resolve_media(session, mid)
    if not url:
        return None, "no_file"
    if (info or {}).get("variant") not in FULL_SIZE_VARIANTS:
        return None, "small_copy"
    return url, ""


def _pixel_size_ok(path, row):
    """False when the catalog knows this picture's width and height and the new file is a
    different size. Pictures only (a video's frame size would need ffprobe); with no size in
    the catalog, or no Pillow, there is nothing to compare and the other checks stand."""
    if str(row.get("is_video") or "") == "1":
        return True
    try:
        w, h = int(str(row.get("width") or "0")), int(str(row.get("height") or "0"))
    except ValueError:
        return True
    if w <= 0 or h <= 0:
        return True
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        with Image.open(path) as im:
            return tuple(im.size) == (w, h)
    except Exception:                                  # noqa: BLE001 -- unreadable is not a match
        return False


def _download_session():
    """The session a fix run downloads with -- made once per run (FixRunner), and without the
    USER_ID lookup: media reads never use the user id, and that `me` query retries three
    times."""
    from moonglade import backup as core
    return core._make_session(None, resolve_user=False)


def _move_no_clobber(src, dest):
    """Put `src` at `dest` only if nothing is there; never overwrite. A hard link, which the OS
    refuses when `dest` exists, then the staging name goes. Where the disk has no hard links,
    Windows' own rename, which refuses an existing `dest` too. Raises FileExistsError when
    something is already at `dest`."""
    try:
        os.link(src, dest)
    except FileExistsError:
        raise
    except OSError:
        if os.name != "nt":
            raise
        os.rename(src, dest)
        return
    os.unlink(src)


def _still_broken(target, problem):
    """Whether the file about to be replaced is still the broken one: empty, or (for a
    cut-short file) still failing the structural check. A sync that mended it meanwhile wins."""
    try:
        size = os.path.getsize(target)
    except OSError:
        return False
    if size == 0:
        return True
    return problem == P_SUSPECT and structural_problem(target) is not None


def _live_check(out, row, index, g):
    return _row_check(row, index or _index(out, g), True, g.GALLERY_DIRNAME)


def redownload_one(out_dir, db_path, media_id, session_factory=None, index=None, on_bytes=None):
    """Re-download ONE broken file over itself. Returns a result dict (media_id, action, ok,
    refused, error, note, bytes). See the section comment for the order of the checks."""
    from moonglade import backup as core
    from moonglade import gallery as g
    out = Path(out_dir)
    mid = str(media_id or "").strip()
    row = g.get_row(db_path, mid) if mid else None
    if not row:
        return _result(mid, "redownload", ok=False, refused="not_in_catalog")
    # THE RULE. Read from the catalog here, never from the caller.
    if g.is_archive_only(row):
        return _result(mid, "redownload", ok=False, refused="archive_only")
    try:
        core._check_read_only("re-download a broken file")
    except core.PixAIError:
        return _result(mid, "redownload", ok=False, refused="read_only")

    problem, _path, _size, best = _live_check(out, row, index, g)
    if problem not in REFETCH_PROBLEMS:
        return _result(mid, "redownload", note="already sound")   # never overwrite a sound file
    missing = problem == P_MISSING
    if missing:
        target, why = missing_target(out, row)         # the catalog's path, checked, or refused
        if target is None:
            return _result(mid, "redownload", ok=False, refused=why)
    elif best is None:
        return _result(mid, "redownload", note="already sound")
    else:
        target = Path(best.path)                       # the broken file itself...
        if g.media_id_of(target) != mid:               # ...and never another picture's file
            return _result(mid, "redownload", ok=False, refused="not_this_picture")
    want = _FORMAT_OF_EXT.get(target.suffix.lower())
    if not want:
        return _result(mid, "redownload", ok=False, refused="unknown_type")

    stage = out / g.GALLERY_DIRNAME / STAGING_DIRNAME
    got = None
    stem = None
    try:
        stage.mkdir(parents=True, exist_ok=True)
        session = (session_factory or _download_session)()
        url, why = _full_size_url(core, session, row, mid)
        if not url:
            return _result(mid, "redownload", ok=False, refused=why)
        import uuid
        stem = stage / "{}-{}".format(mid if _safe_id(mid) else "media", uuid.uuid4().hex[:10])
        # (the finally below removes everything this stem left in the staging folder)
        status, got = core.download(session, url, stem, retries=0, progress=on_bytes)
        if status != "ok" or not got:
            return _result(mid, "redownload", ok=False, refused="no_file")
        if not verified_whole(got):
            return _result(mid, "redownload", ok=False, refused="unverified")
        if _format_of(got) != want:
            return _result(mid, "redownload", ok=False, refused="type_differs")
        nbytes = os.path.getsize(got)
        if problem == P_SUSPECT and nbytes < int(best.size or 0):
            return _result(mid, "redownload", ok=False, refused="smaller")
        if not _pixel_size_ok(got, row):
            return _result(mid, "redownload", ok=False, refused="size_differs")
        if missing:
            # Re-asked at the last moment: nothing may have appeared there while it downloaded.
            target, why = missing_target(out, row)
            if target is None:
                return _result(mid, "redownload", ok=False, refused=why)
            target.parent.mkdir(parents=True, exist_ok=True)   # inside the library: rule 2
            try:
                _move_no_clobber(got, target)          # never over something that appeared
            except FileExistsError:
                return _result(mid, "redownload", ok=False, refused="occupied")
        else:
            if not _still_broken(target, problem):    # mended while it downloaded: leave it
                return _result(mid, "redownload", note="already sound")
            core._atomic_replace(got, target)          # the verified file, over the broken one
        got = None
    except Exception:                                  # noqa: BLE001 -- one row, said plainly
        return _result(mid, "redownload", ok=False, refused="no_file")
    finally:
        # Our own staging files only: the download (if it never moved) and any .part it left.
        if stem is not None:
            for left in list(stage.iterdir()):
                if left.name.startswith(stem.name):    # a name match, never a glob pattern
                    try:
                        left.unlink()
                    except OSError:
                        pass

    # The fresh file deserves its thumbnail. An image's is remade from it; a video keeps a
    # poster it already has (that one came from PixAI and cannot be remade from the file).
    thumb = out / g.GALLERY_DIRNAME / "thumbs" / (mid + ".jpg")
    if _safe_id(mid):
        if str(row.get("is_video") or "") == "1":
            if not thumb.exists() or thumb.stat().st_size == 0:
                g.make_video_thumbnail(target, thumb)
        else:
            g.make_thumbnail(target, thumb)
    return _result(mid, "redownload", nbytes=nbytes)


def rebuild_one(out_dir, db_path, media_id, index=None):
    """Rebuild ONE missing or empty thumbnail from the file on disk. Local only: no network,
    and READ_ONLY does not stop it. Refuses when the file itself is broken."""
    from moonglade import gallery as g
    out = Path(out_dir)
    mid = str(media_id or "").strip()
    row = g.get_row(db_path, mid) if mid else None
    if not row or not _safe_id(mid):
        return _result(mid, "rebuild", ok=False, refused="not_in_catalog")
    problem, _path, _size, best = _live_check(out, row, index, g)
    if problem in _FILE_PROBLEMS or best is None:
        return _result(mid, "rebuild", ok=False, refused="file_broken")
    if problem not in REBUILD_PROBLEMS:
        return _result(mid, "rebuild", note="already sound")
    if g.media_id_of(best.path) != mid:                # this picture's thumbnail, from its own file
        return _result(mid, "rebuild", ok=False, refused="not_this_picture")
    thumb = out / g.GALLERY_DIRNAME / "thumbs" / (mid + ".jpg")
    made = (g.make_video_thumbnail(best.path, thumb) if str(row.get("is_video") or "") == "1"
            else g.make_thumbnail(best.path, thumb))
    if not made:
        return _result(mid, "rebuild", ok=False, refused="rebuild_failed")
    return _result(mid, "rebuild")


FIX_ACTIONS = ("redownload", "rebuild")


def fix_one(out_dir, db_path, media_id, session_factory=None, index=None, on_bytes=None,
            marks=None, expect=None):
    """The fix one row needs NOW: a re-download for a missing, empty or cut-short file, a
    rebuild for a thumbnail. A row the owner marked lost is left alone.

    `expect` is the action the list SHOWED for this row (the client sends it with the id).
    When the file has changed since the check so that today's fix is a different one, nothing
    runs: a Rebuild the owner pressed never turns into a network re-download, nor the other
    way round (review finding 3)."""
    from moonglade import gallery as g
    mid = str(media_id or "").strip()
    marks = read_marks(out_dir) if marks is None else marks
    row = g.get_row(db_path, mid) if mid else None
    if not row:
        return _result(mid, "", ok=False, refused="not_in_catalog")
    problem = _live_check(Path(out_dir), row, index, g)[0]
    action = "redownload" if problem in _FILE_PROBLEMS else "rebuild"
    if (marks.get(mid) or {}).get("mark") == "lost":
        return _result(mid, action, ok=False, refused="marked_lost")
    if problem is not None and expect is not None and expect != action:
        return _result(mid, expect, ok=False, refused="changed")
    if problem in _FILE_PROBLEMS:
        return redownload_one(out_dir, db_path, mid, session_factory=session_factory,
                              index=index, on_bytes=on_bytes)
    if problem in REBUILD_PROBLEMS:
        return rebuild_one(out_dir, db_path, mid, index=index)
    return _result(mid, action, note="already sound")


def reverify(out_dir, db_path, media_ids):
    """Check THESE catalog rows again (read-only) and rewrite both reports in place: their
    old row lines go, the lines a fresh check finds come in, and the counts follow. Every
    other line stays as the full check wrote it, and so does its `verified_at`; this run is
    stamped `reverified_at`. Returns the new summary, or None when there is no report."""
    from moonglade import gallery as g
    out = Path(out_dir)
    ids = {str(m) for m in media_ids if str(m).strip()}
    index = _index(out, g)                             # the walk, before the lock is taken
    with _ReportLock(out):
        return _reverify_locked(out, db_path, ids, index, g)


def _reverify_locked(out, db_path, ids, index, g):
    """reverify's read-modify-write, run while it holds the reports' lock."""
    summary = read_summary(out)
    if summary is None:
        return None
    row_problems = set(_SEVERITY) - {P_UNCATALOGED, P_ORPHAN_THUMB}
    lines = [ln for ln in read_lines(out) if not (ln[0] in ids and ln[1] in row_problems)]
    deep = bool(summary.get("deep"))
    for r in g.rows_for_media_ids(db_path, sorted(ids)):
        if not str(r.get("filename") or "").strip():
            continue
        line = _line_for(r, _row_check(r, index, deep, g.GALLERY_DIRNAME), g)
        if line:
            lines.append(line)
    lines.sort(key=lambda ln: (_SEVERITY.get(ln[1], 9), ln[0], ln[2]))
    summary = dict(summary, counts=_counts(lines),
                   lost=sum(1 for ln in lines if ln[4] == "no"), reverified_at=_utc_now())
    _write_reports(out, lines, summary)
    return summary


def run_summary(fixed, total, results, stopped=False):
    """The run's last line, for its Activity row: "Fixed 11 of 12 · 1 couldn't be
    re-downloaded". Failures are counted by what was being tried."""
    failed = [r for r in results if not r.get("ok")]
    redl = sum(1 for r in failed if r.get("action") == "redownload")
    reb = sum(1 for r in failed if r.get("action") == "rebuild")
    other = len(failed) - redl - reb
    parts = ["Fixed {} of {}".format(fixed, total)]
    if redl:
        parts.append("{} couldn't be re-downloaded".format(redl))
    if reb:
        parts.append("{} thumbnail{} couldn't be rebuilt".format(reb, "" if reb == 1 else "s"))
    if other:
        parts.append("{} couldn't be fixed".format(other))
    if stopped:
        parts.append("stopped")
    return " · ".join(parts)


class FixRunner:
    """One fix run at a time, on a thread of the server, so closing Health never stops it.

    start(items) takes the chosen rows, each {"media_id", "action"} with the action the list
                showed, keeps the ones on the Broken files list with an action it knows (the
                rest come back as `refused`), and fixes them in order: fix_one per row, with
                its shown action as `expect`, so every row goes through the same checks as a
                single click -- the archive-only refusal included. Answers the run's status,
                or None while a run is going.
    stop()      finishes the current file and stops. Nothing is rolled back.
    status()    a copy of the run: total, done, fixed, failed, the current row with its
                bytes (a true fraction for the byte bar), and every result so far.

    The run mirrors itself to the Activity tray through `log_job` (type "integrity"), and
    when it ends the rows it touched are checked again (reverify) so Health's tiles and the
    list read the result."""

    def __init__(self, out_dir, db_path, log_job=None, session_factory=None):
        self.out = Path(out_dir)
        self.db = Path(db_path)
        self._log = log_job or (lambda *a, **k: None)
        self._session_factory = session_factory
        self._fix = fix_one
        self._lock = threading.Lock()
        self._thread = None
        self._state = {"running": False, "job_id": "", "total": 0, "done": 0, "fixed": 0,
                       "failed": 0, "current": None, "results": [], "stopped": False,
                       "stop": False, "refused": [], "finished_at": None, "summary": ""}

    def status(self):
        with self._lock:
            st = dict(self._state)
            st["results"] = [dict(r) for r in self._state["results"]]
            st["current"] = dict(self._state["current"]) if self._state["current"] else None
            st.pop("stop", None)
        return st

    def stop(self):
        with self._lock:
            if self._state["running"]:
                self._state["stop"] = True

    def wait(self, timeout=None):
        t = self._thread
        if t is not None:
            t.join(timeout)

    def start(self, items):
        import uuid
        shown = {}                                     # media_id -> the action the list showed
        refused = []
        for it in items or []:
            mid = str((it or {}).get("media_id") or "").strip() if isinstance(it, dict) else ""
            act = (it or {}).get("action") if isinstance(it, dict) else None
            if not mid:
                continue
            if act not in FIX_ACTIONS:
                refused.append(mid)
            elif mid not in shown:
                shown[mid] = act
        listed = listed_ids(self.out)
        take = [(m, a) for m, a in shown.items() if m in listed]
        refused += [m for m in shown if m not in listed]
        with self._lock:
            if self._state["running"]:
                return None
            job_id = "integrity-" + uuid.uuid4().hex[:12]
            self._state = {"running": bool(take), "job_id": job_id if take else "",
                           "total": len(take), "done": 0, "fixed": 0, "failed": 0,
                           "current": None, "results": [], "stopped": False, "stop": False,
                           "refused": refused, "finished_at": None, "summary": ""}
        if not take:
            return self.status()
        label = "Fixing {} file{}".format(len(take), "" if len(take) == 1 else "s")
        self._log(job_id, status="running", type="integrity", label=label, done=0,
                  total=len(take))
        self._thread = threading.Thread(target=self._run, args=(job_id, take), daemon=True,
                                        name="moonglade-integrity-fix")
        self._thread.start()
        return self.status()

    def _on_bytes(self, n, total):
        with self._lock:
            cur = self._state["current"]
            if cur is not None:
                cur["bytes"], cur["expect"] = int(n), int(total or 0)

    def _run(self, job_id, items):
        from moonglade import gallery as g
        touched = []
        err = ""
        made = []

        def session_once():                            # ONE download session for the whole run
            if not made:
                made.append((self._session_factory or _download_session)())
            return made[0]
        try:
            index = _index(self.out, g)
            marks = read_marks(self.out)
            for mid, shown in items:
                with self._lock:
                    if self._state["stop"]:
                        self._state["stopped"] = True
                        break
                    self._state["current"] = {"media_id": mid, "bytes": 0, "expect": 0}
                try:
                    res = self._fix(self.out, self.db, mid, session_factory=session_once,
                                    index=index, on_bytes=self._on_bytes, marks=marks,
                                    expect=shown)
                except Exception:                      # noqa: BLE001 -- one row, never the run
                    res = _result(mid, "", ok=False, error="Couldn't fix this file.")
                touched.append(mid)
                with self._lock:
                    st = self._state
                    st["results"].append(res)
                    st["done"] += 1
                    st["fixed" if res.get("ok") else "failed"] += 1
                    st["current"] = None
                    done, total = st["done"], st["total"]
                self._log(job_id, status="running", done=done, total=total)
            else:
                with self._lock:
                    self._state["stopped"] = bool(self._state["stop"]) and \
                        self._state["done"] < self._state["total"]
            if touched:
                reverify(self.out, self.db, touched)
        except Exception as e:                         # noqa: BLE001 -- the run ends, said
            err = "The fix run stopped: {}".format(str(e)[:120])
        finally:
            with self._lock:
                st = self._state
                st["running"] = False
                st["current"] = None
                st["finished_at"] = _utc_now()
                st["summary"] = run_summary(st["fixed"], st["total"], st["results"],
                                            stopped=st["stopped"])
                summary, failed, done, total = st["summary"], st["failed"], st["done"], st["total"]
            self._log(job_id, status="done_with_errors" if (failed or err) else "done",
                      label=summary, done=done, total=total, error=(err or None))
