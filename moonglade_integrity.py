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

Phase B (a broken-file list with per-row actions, a targeted re-download) is a design session
of its own and is not here.
"""
import csv
import io
import json
import os
import struct
import sys
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
