"""moonglade_integrity -- the library integrity pass (Phase A).

Health's tiles are aggregates: a library whose files are EMPTY or TORN still reads green,
because Health counts a file that exists, whatever is in it. This pass looks at every
catalogued file and names the broken ones, one report line per broken row, and stamps when it
last ran.

    python moonglade_backup.py --verify-library                 # quick tier
    python moonglade_backup.py --verify-library --verify-deep   # + structural checks

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

A broken row that PixAI no longer has (archive-only, moonglade_gallery.is_archive_only) is
LOST: its report line says recoverable "no", because there is nothing left to re-fetch it
from. Every other broken row says "yes".

READ-ONLY. It never deletes, moves, re-downloads or rebuilds anything. The only files it
writes are its own two reports at the library root, beside audit_report.csv, each replaced
atomically:

  integrity_report.csv    media_id, problem, path, size, recoverable -- one line per problem
  integrity_report.json   verified_at (UTC), deep, rows checked, files walked, the counts,
                          the lost count. collection_health() reads it for Health's tiles.

Hostile file names: a cell that a spreadsheet would read as a formula is prefixed with a
quote (csv_safe), and every printed line has its control characters replaced (printable), so
a file name cannot forge a Control Panel progress line or a terminal escape.

PHASE B (Session W, the Archive Integrity Handoff) is the Broken files list in Health, built on
the report above and kept in its own section at the foot of this file: broken_list() reads the
report back for the list, and the owner's local marks (Mark lost, Keep as is) live in
integrity_marks.json beside the reports. The list is still read-only; the fixes it offers run
elsewhere and are described where they are written.
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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    try:
        import moonglade_backup as core              # lazy: the Windows sharing-violation retry
        core._atomic_replace(tmp, path)
    except ImportError:
        os.replace(tmp, path)


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


def verify_library(out_dir, db_path, deep=False, progress=None):
    """Run the pass, write both reports, return the summary (the JSON document) with the
    report lines under "lines" as (media_id, problem, path, size, recoverable) tuples."""
    import moonglade_gallery as g                     # lazy: the catalog verbs and the walk
    out = Path(out_dir)
    rows = g.integrity_rows(db_path) if Path(db_path).exists() else []

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
        mid = str(r.get("media_id") or "")
        fn = str(r.get("filename") or "").replace("\\", "/")
        is_video = str(r.get("is_video") or "") == "1"
        kind = "video" if is_video else "image"
        cands = [by_rel[fn]] if fn in by_rel else []
        for c in by_mid.get((kind, mid), ()):
            if c not in cands:
                cands.append(c)
        sized = [c for c in cands if c.size is not None]
        problem, path, size = None, fn, ""
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
                path, size = "{}/thumbs/{}.jpg".format(g.GALLERY_DIRNAME, mid), ""
            elif thumbs[mid] == 0:
                problem = P_ZERO_THUMB
                path, size = "{}/thumbs/{}.jpg".format(g.GALLERY_DIRNAME, mid), 0
        if problem:
            gone = problem in _FILE_PROBLEMS and g.is_archive_only(r)
            lost += 1 if gone else 0
            lines.append((mid, problem, path, size, "no" if gone else "yes"))
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
    counts = {k: 0 for k in COUNT_KEYS}
    for ln in lines:
        counts[_COUNT_KEY[ln[1]]] += 1

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["media_id", "problem", "path", "size", "recoverable"])
    for mid, problem, path, size, rec in lines:
        w.writerow([csv_safe(mid), problem, csv_safe(path), size, rec])
    summary = {
        "format": REPORT_FORMAT, "version": REPORT_VERSION,
        "verified_at": _utc_now(), "deep": bool(deep),
        "rows": total, "files": len(by_rel),
        "counts": counts, "lost": lost, "report": REPORT_CSV,
    }
    _write_atomic(out / REPORT_CSV, buf.getvalue().encode("utf-8"))
    _write_atomic(out / REPORT_JSON, json.dumps(summary, indent=2, sort_keys=True).encode("utf-8"))
    return dict(summary, lines=lines)


def read_summary(out_dir):
    """The last run's integrity_report.json, or None when there is none (or it is not one).
    A file read, never a walk: Health calls this on every recompute."""
    try:
        doc = json.loads((Path(out_dir) / REPORT_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
#   state   the pill: "recoverable", "suspect" (still recoverable, drawn peach) or "lost".
#   action  the one fix that applies: "redownload" (an empty or cut-short file PixAI still
#           has), "rebuild" (a thumbnail, local work), or None (a LOST row has none).
#
# LOST is decided from the catalog NOW, not from the report's recoverable column: the
# archive-only flag is rewritten at every reconcile, so a file PixAI lists again becomes
# RECOVERABLE without a new check. A row the owner marked lost is LOST whatever PixAI says.
#
# A MISSING file (a catalog row whose file is nowhere on disk) is not on the list: the
# handoff's chips (All, Zero-byte, Thumbnail, Suspect, Lost) and its counts have no place
# for one, and Health's own Missing files tile already counts them.

MARKS_FILE = "integrity_marks.json"
MARKS_FORMAT = "moonglade-integrity-marks"
# Mark lost: "this one is gone, stop counting it" (any broken row).
# Keep as is: "I've seen it" on a LOST row; it lapses if PixAI lists the file again.
MARKS = ("lost", "kept")

KIND_ZERO, KIND_THUMB, KIND_SUSPECT = "zero", "thumb", "suspect"
LIST_KIND = {P_ZERO: KIND_ZERO, P_SUSPECT: KIND_SUSPECT, P_NO_THUMB: KIND_THUMB,
             P_NO_POSTER: KIND_THUMB, P_ZERO_THUMB: KIND_THUMB}
REFETCH_PROBLEMS = (P_ZERO, P_SUSPECT)
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
        text = (Path(out_dir) / REPORT_CSV).read_text(encoding="utf-8")
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
        lines.append((_csv_unsafe(mid), problem, _csv_unsafe(path),
                      int(size) if size.isdigit() else "", rec))
    return lines


def read_marks(out_dir):
    """{media_id: {"mark": "lost" | "kept", "at": utc}} -- the owner's local flags."""
    try:
        doc = json.loads((Path(out_dir) / MARKS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
        _write_atomic(Path(out_dir) / MARKS_FILE,
                      json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"))
    return prev


def reconciled_at(out_dir):
    """When the last reconcile (moonglade_backup.run_reconcile_deleted) rewrote the
    archive-only flags, or None before the first stamped one."""
    import moonglade_backup as core                  # lazy, like _write_atomic's
    try:
        doc = json.loads((Path(out_dir) / core.RECONCILE_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
    import moonglade_gallery as g                     # lazy: the catalog verbs
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

    counts = {"all": len(rows), KIND_ZERO: 0, KIND_THUMB: 0, KIND_SUSPECT: 0, "lost": 0}
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
