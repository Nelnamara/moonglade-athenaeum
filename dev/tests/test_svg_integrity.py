"""3.21.2, L3 (DESIGN_3.22 "Live in master today"): an SVG with no thumbnail is not broken.

An svg-logo-maker result arrives by sync as `.svg` (3.21.1). make_thumbnail cannot draw one
(Pillow does not open SVG, and this app never rasterises it), so every Library check listed
each SVG as "no thumbnail", its Rebuild failed every time, and a missing SVG could not be
re-downloaded at all. Now:
  - the check never asks an SVG (or any picture type the thumbnailer cannot draw) for a
    thumbnail, and the Broken files list never offers it a Rebuild -- an older report's line
    included;
  - the thumbnail builder skips it without counting a failure;
  - a missing or empty SVG re-downloads like any other picture, accepted by its XML head;
  - it stays a plain file: served as a download, never inline (3.21.1's hardening)."""
from pathlib import Path

import pytest

from moonglade import gallery as g
from moonglade import integrity as integ
from moonglade.gallery import CATALOG_FIELDS, save_catalog
from tests.test_integrity import _png
from tests.test_integrity_fix import FakeMediaSession

SVG = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
       b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
       b'<rect width="64" height="64" fill="#336"/></svg>\n')


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _lib(tmp_path, svg_bytes=SVG, with_svg_file=True):
    out = tmp_path
    (out / "images").mkdir(parents=True, exist_ok=True)
    thumbs = out / "gallery" / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    (out / "images" / "p_t1_201.png").write_bytes(_png())
    (thumbs / "201.jpg").write_bytes(b"\xff\xd8jpeg\xff\xd9")
    if with_svg_file:
        (out / "images" / "logo_t2_202.svg").write_bytes(svg_bytes)
    (out / "images" / "p_t3_203.png").write_bytes(_png())       # a raster with no thumbnail
    save_catalog(out / "catalog.db", [
        _row(media_id="201", filename="p_t1_201.png", task_id="t1", width="2", height="2"),
        _row(media_id="202", filename="logo_t2_202.svg", task_id="t2", width="64", height="64"),
        _row(media_id="203", filename="p_t3_203.png", task_id="t3", width="2", height="2"),
    ])
    return out


def _problems(summary):
    return {(ln[0], ln[1]) for ln in summary["lines"]}


@pytest.mark.parametrize("deep", [False, True])
def test_an_svg_is_never_reported_without_a_thumbnail(tmp_path, deep):
    out = _lib(tmp_path)
    s = integ.verify_library(out, out / "catalog.db", deep=deep)
    probs = _problems(s)
    assert not any(m == "202" for m, _p in probs), probs
    assert ("203", integ.P_NO_THUMB) in probs, "a raster's missing thumbnail is still found"


def test_the_thumbnailer_rule():
    assert g.thumbnail_renders("a_1.png") and g.thumbnail_renders("x/a_1.JPG")
    assert not g.thumbnail_renders("logo_2.svg") and not g.thumbnail_renders("LOGO_2.SVG")
    assert not g.thumbnail_renders("odd_3.notapicture")
    assert g.thumbnail_renders("") and g.thumbnail_renders(None)          # today's default


def test_the_broken_list_never_offers_an_svg_a_rebuild_even_from_an_old_report(tmp_path):
    out = _lib(tmp_path)
    integ.verify_library(out, out / "catalog.db")
    # a report written before 3.21.2 named the SVG "no thumbnail"
    lines = integ.read_lines(out) + [("202", integ.P_NO_THUMB, "gallery/thumbs/202.jpg", "", "yes")]
    integ._write_reports(out, lines, integ.read_summary(out))
    lst = integ.broken_list(out, out / "catalog.db")
    assert [r["media_id"] for r in lst["rows"] if r["action"] == "rebuild"] == ["203"]
    assert "202" not in repr(lst["fix"])


def test_a_rebuild_asked_for_an_svg_is_already_sound_not_a_failure(tmp_path):
    out = _lib(tmp_path)
    res = integ.rebuild_one(out, out / "catalog.db", "202")
    assert res["ok"] is True and not res["refused"]
    assert not (out / "gallery" / "thumbs" / "202.jpg").exists()


def test_build_thumbnails_skips_an_svg_without_counting_a_failure(tmp_path, monkeypatch):
    out = _lib(tmp_path)
    tried = []
    real = g.make_thumbnail
    monkeypatch.setattr(g, "make_thumbnail", lambda src, dst: tried.append(Path(src).name) or real(src, dst))
    seen = []
    g.build_thumbnails(g.load_catalog(out / "catalog.db"), out, out / "gallery" / "thumbs",
                       progress_cb=lambda d, t, p: seen.append((d, t)), workers=1)
    assert "logo_t2_202.svg" not in tried
    assert seen[-1][0] == seen[-1][1], "every row is accounted for: none counted as failed"


def test_a_missing_svg_re_downloads_by_its_xml_head(tmp_path):
    out = _lib(tmp_path, with_svg_file=False)
    s = integ.verify_library(out, out / "catalog.db")
    assert ("202", integ.P_MISSING) in _problems(s)
    session = FakeMediaSession({"202": (SVG, "image/svg+xml")})
    res = integ.redownload_one(out, out / "catalog.db", "202", session_factory=lambda: session)
    assert res["ok"] is True, res
    assert (out / "images" / "logo_t2_202.svg").read_bytes() == SVG
    assert not (out / "gallery" / "thumbs" / "202.jpg").exists()


def test_an_empty_svg_is_replaced_and_an_html_page_never_is(tmp_path):
    out = _lib(tmp_path, svg_bytes=b"")
    page = b"<!DOCTYPE html><html><body>Not found</body></html>"
    res = integ.redownload_one(out, out / "catalog.db", "202",
                               session_factory=lambda: FakeMediaSession({"202": (page, "image/svg+xml")}))
    assert res["ok"] is False and res["refused"] == "unverified"
    assert (out / "images" / "logo_t2_202.svg").read_bytes() == b""
    res = integ.redownload_one(out, out / "catalog.db", "202",
                               session_factory=lambda: FakeMediaSession({"202": (SVG, "image/svg+xml")}))
    assert res["ok"] is True, res
    assert (out / "images" / "logo_t2_202.svg").read_bytes() == SVG


@pytest.mark.parametrize("head,ok", [
    (SVG, True),
    (b'\xef\xbb\xbf  <svg xmlns="http://www.w3.org/2000/svg"></svg>', True),
    (b"<!-- made by a tool -->\n<svg></svg>", True),
    (b'<?xml version="1.0"?><note>not a picture</note>', False),
    (b"<!DOCTYPE html><html></html>", False),
    (b"<html><svg></svg></html>", False),
])
def test_the_svg_head_rule(tmp_path, head, ok):
    f = tmp_path / "x_1.svg"
    f.write_bytes(head)
    assert (integ._format_of(f) == "svg") is ok
    assert integ.verified_whole(f) is ok
