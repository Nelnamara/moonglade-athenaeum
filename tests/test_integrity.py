"""The library integrity pass, Phase A (moonglade_integrity.py; scope items 2+3).

Health's counters are aggregates, so it read green over a library whose files were empty or
torn. This pass names the broken rows, one report line each, and stamps when it last ran:

  quick tier   missing file, zero-byte file, no thumbnail / no poster, zero-byte thumbnail,
               uncataloged file, orphan thumbnail (one walk of the library, one scandir of
               the thumbnails -- sizes come free)
  deep tier    + structural end-of-file checks that never decode a picture: PNG IEND, JPEG
               EOI, WebP RIFF length, GIF trailer, MP4 `moov`. A failure is "suspect", never
               "corrupt".

A broken row PixAI no longer has (archive-only, #66) is LOST: recoverable "no", because there
is nothing left to re-fetch it from. Read-only: the only thing it writes is its own two
report files.
"""
import csv
import hashlib
import json
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path

import moonglade_backup as core
import moonglade_gallery as g
import moonglade_integrity as integ
from moonglade_gallery import CATALOG_FIELDS, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _png(w=2, h=2):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _jpeg():
    return b"\xff\xd8\xff\xe0" + b"\x00" * 40 + b"\xff\xd9"


def _webp(claimed_extra=0):
    body = b"VP8L" + struct.pack("<I", 6) + b"\x2f\x00\x00\x00\x00\x00"
    return b"RIFF" + struct.pack("<I", 4 + len(body) + claimed_extra) + b"WEBP" + body


def _box(kind, payload=b""):
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _mp4(with_moov=True):
    return (_box(b"ftyp", b"isom\x00\x00\x02\x00")
            + (_box(b"moov", b"\x00" * 16) if with_moov else b"")
            + _box(b"mdat", b"\x00" * 32))


def _library(tmp_path):
    """A small library with one of every problem the pass names, beside sound rows."""
    out = tmp_path
    img = out / "images"
    vid = out / "videos"
    thumbs = out / "gallery" / "thumbs"
    for d in (img, vid, thumbs):
        d.mkdir(parents=True, exist_ok=True)
    png = _png()
    files = {
        img / "p_t1_101.png": png,                       # sound
        img / "p_t1_102.png": b"",                       # zero-byte
        img / "p_t1_103.png": png[:-12],                 # IEND cut off
        img / "p_t1_104.webp": _webp(claimed_extra=40),  # RIFF claims more than the file holds
        img / "p_t1_106.png": png,                       # sound, but no thumbnail
        img / "p_t1_107.png": png,                       # sound, zero-byte thumbnail
        img / "p_t1_110.jpg": _jpeg(),                   # sound JPEG
        img / "p_t1_999.png": png,                       # on disk, no catalog row
        vid / "p_t1_108.mp4": _mp4(),                    # sound video, no poster
        vid / "p_t1_111.mp4": _mp4(with_moov=False),     # video with no moov atom
    }
    for p, data in files.items():
        p.write_bytes(data)
    for mid in ("101", "102", "103", "104", "110", "111"):
        (thumbs / (mid + ".jpg")).write_bytes(_jpeg())
    (thumbs / "107.jpg").write_bytes(b"")
    (thumbs / "555.jpg").write_bytes(_jpeg())            # a thumbnail with no row
    save_catalog(out / "catalog.db", [
        _row(media_id="101", filename="p_t1_101.png"),
        _row(media_id="102", filename="p_t1_102.png"),
        _row(media_id="103", filename="p_t1_103.png"),
        _row(media_id="104", filename="p_t1_104.webp"),
        _row(media_id="105", filename="p_t1_105.png"),                       # no file at all
        _row(media_id="106", filename="p_t1_106.png"),
        _row(media_id="107", filename="p_t1_107.png"),
        _row(media_id="108", filename="videos/p_t1_108.mp4", is_video="1"),
        _row(media_id="109", filename="p_t1_109.png", deleted_remote="1"),   # LOST
        _row(media_id="110", filename="p_t1_110.jpg"),
        _row(media_id="111", filename="videos/p_t1_111.mp4", is_video="1"),
    ])
    return out


def _tree_hash(root, skip=("integrity_report.csv", "integrity_report.json")):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel in skip:
            continue
        h.update(rel.encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def _lines(out):
    with open(out / "integrity_report.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["media_id", "problem", "path", "size", "recoverable"]
    return {r[0]: r for r in rows[1:]}


def test_the_quick_tier_names_each_broken_row(tmp_path):
    out = _library(tmp_path)
    rep = integ.verify_library(out, out / "catalog.db")
    lines = _lines(out)
    problems = {mid: r[1] for mid, r in lines.items()}
    assert problems == {
        "102": "zero-byte",
        "105": "missing",
        "106": "no thumbnail",
        "107": "zero-byte thumbnail",
        "108": "no poster",
        "109": "missing",
        "999": "uncataloged",
        "555": "orphan thumbnail",
    }
    assert lines["102"][2] == "images/p_t1_102.png" and lines["102"][3] == "0"
    assert lines["105"][2] == "p_t1_105.png" and lines["105"][3] == ""
    assert lines["105"][4] == "yes"                       # PixAI still has it
    assert lines["109"][4] == "no"                        # archive-only: nothing to re-fetch
    assert rep["counts"]["missing"] == 2
    assert rep["counts"]["zero_byte"] == 1
    assert rep["counts"]["missing_thumb"] == 2            # one thumbnail, one video poster
    assert rep["counts"]["zero_byte_thumb"] == 1
    assert rep["counts"]["uncataloged"] == 1
    assert rep["counts"]["orphan_thumb"] == 1
    assert rep["counts"]["suspect"] == 0                  # the quick tier reads no file
    assert rep["lost"] == 1
    assert rep["deep"] is False


def test_the_deep_tier_marks_torn_files_suspect(tmp_path):
    out = _library(tmp_path)
    rep = integ.verify_library(out, out / "catalog.db", deep=True)
    lines = _lines(out)
    assert lines["103"][1] == "suspect: truncated"        # PNG with no IEND
    assert lines["104"][1] == "suspect: truncated"        # WebP shorter than its RIFF length
    assert lines["111"][1] == "suspect: truncated"        # MP4 with no moov atom
    for sound in ("101", "110"):
        assert sound not in lines, sound
    assert rep["counts"]["suspect"] == 3
    assert rep["deep"] is True
    assert "corrupt" not in (out / "integrity_report.csv").read_text(encoding="utf-8")


def test_the_structural_checks_on_their_own(tmp_path):
    def check(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return integ.structural_problem(p)
    assert check("a.png", _png()) is None
    assert check("b.png", _png()[:-12]) == "truncated"
    assert check("c.jpg", _jpeg()) is None
    assert check("d.jpg", _jpeg()[:-2]) == "truncated"
    assert check("e.webp", _webp()) is None
    assert check("f.webp", _webp(claimed_extra=10)) == "truncated"
    assert check("g.gif", b"GIF89a" + b"\x00" * 20 + b"\x3b") is None
    assert check("h.gif", b"GIF89a" + b"\x00" * 20) == "truncated"
    assert check("i.mp4", _mp4()) is None
    assert check("j.mp4", _mp4(with_moov=False)) == "truncated"
    assert check("k.mp4", _mp4()[:-10]) == "truncated"    # last box runs past the end
    # a format it does not know is never called suspect
    assert check("l.png", b"not a png at all, just bytes") is None


def test_the_report_files_and_the_stamp(tmp_path):
    out = _library(tmp_path)
    integ.verify_library(out, out / "catalog.db")
    doc = json.loads((out / "integrity_report.json").read_text(encoding="utf-8"))
    assert doc["verified_at"].endswith("Z")
    datetime.strptime(doc["verified_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert doc["rows"] == 11
    assert doc["deep"] is False
    assert doc["counts"]["missing"] == 2
    assert doc["lost"] == 1
    assert integ.read_summary(out)["verified_at"] == doc["verified_at"]
    assert integ.read_summary(tmp_path / "nowhere") is None


def test_it_is_read_only(tmp_path):
    out = _library(tmp_path)
    before = _tree_hash(out)
    integ.verify_library(out, out / "catalog.db", deep=True)
    assert _tree_hash(out) == before, "the pass changed the library"


def test_it_is_idempotent(tmp_path):
    out = _library(tmp_path)
    first = integ.verify_library(out, out / "catalog.db", deep=True)
    csv1 = (out / "integrity_report.csv").read_bytes()
    second = integ.verify_library(out, out / "catalog.db", deep=True)
    assert (out / "integrity_report.csv").read_bytes() == csv1
    assert first["counts"] == second["counts"] and first["rows"] == second["rows"]


def test_progress_is_reported(tmp_path):
    out = _library(tmp_path)
    seen = []
    integ.verify_library(out, out / "catalog.db", progress=lambda d, t, n=0: seen.append((d, t)))
    assert seen and seen[-1][0] == seen[-1][1] == 11


def test_hostile_file_names_cannot_forge_a_report_line(tmp_path):
    """A file name can start a spreadsheet formula, and on some systems hold a line break
    that would forge a Control Panel progress line. Both are neutralised."""
    assert integ.csv_safe("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert integ.csv_safe("+1") == "'+1" and integ.csv_safe("@a") == "'@a"
    assert integ.csv_safe("images/a.png") == "images/a.png"
    line = integ.printable("a\n~=MGPROG=~1|1|0\rb\x1b[2J")
    assert "\n" not in line and "\r" not in line and "\x1b" not in line
    out = tmp_path
    (out / "=cmd_777.png").write_bytes(_png())          # at the library root: the path IS the name
    save_catalog(out / "catalog.db", [])
    integ.verify_library(out, out / "catalog.db")
    lines = _lines(out)
    assert lines["777"][1] == "uncataloged"
    assert lines["777"][2] == "'=cmd_777.png"


# ---------------------------------------------------------------------------
# Health: the tiles read the report, and today's numbers do not move
# ---------------------------------------------------------------------------

def test_health_counts_zero_byte_files_and_reads_the_last_run(tmp_path):
    out = _library(tmp_path)
    before = g.collection_health(out, out / "catalog.db")
    assert before["zero_byte"] == 1
    assert before["integrity"] is None                   # never verified
    integ.verify_library(out, out / "catalog.db")
    after = g.collection_health(out, out / "catalog.db")
    assert after["integrity"]["verified_at"].endswith("Z")
    assert after["integrity"]["counts"]["missing_thumb"] == 2
    # Owner question 1, option (a): the numbers he already knows keep their meaning.
    for key in ("missing", "uncataloged", "total_files"):
        assert after[key] == before[key], key


# ---------------------------------------------------------------------------
# The CLI flag and the Panel row
# ---------------------------------------------------------------------------

def test_the_cli_flag_runs_the_pass_and_logs_a_job(tmp_path, monkeypatch, capsys):
    out = _library(tmp_path)
    monkeypatch.setattr(sys, "argv", ["prog", "--verify-library", "--verify-deep",
                                      "--out", str(out)])
    core.main()
    printed = capsys.readouterr().out
    assert "suspect" in printed and "missing" in printed
    doc = json.loads((out / "integrity_report.json").read_text(encoding="utf-8"))
    assert doc["deep"] is True and doc["counts"]["suspect"] == 3
    jobs = [j for j in core.read_jobs(out) if j.get("type") == "cli"]
    assert [j["label"] for j in jobs] == ["Verify library integrity"]
    assert jobs[0]["status"] == "done"
