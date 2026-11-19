"""A file someone else made never runs as a page on Moonglade's origin (red team, 2026-11-18).

Two holes, both proved by a probe that day:

  * /full/<media_id> sent a library file inline under its own type. 3.21.1 catalogs .svg
    (Edit Pro makes them), and an SVG may carry <script>, so opening one at its own address ran
    that script AS Moonglade, with the signed-in session. Every route that serves a library or
    user file now goes through gallery.harden_file_response: nosniff, a CSP sandbox, and a
    download (Content-Disposition: attachment) for any type that is not a raster picture, a
    video or a sound. An <img> ignores Content-Disposition, so the gallery still shows one.
  * /branding/ is PUBLIC tier and handed any loose file to send_from_directory, so a dropped
    .html or .svg was served to anyone. Owner's ruling: "Just images should be accepted. that
    was the design. sounds and video have no place. save for the animated webp." Raster types
    only, plus the art pack's own moment clips and sounds the shipped front end plays (named by
    exact file in branding.branding_serves_type, held for the owner's word); the rest 404."""
from moonglade import branding as branding_mod
from moonglade import gallery as g
from moonglade.gallery import create_app
from tests.conftest import login_test_client

HOSTILE_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg">'
               b'<script>fetch("/api/whoami")</script></svg>')
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _library(tmp_path):
    img = tmp_path / "images"
    img.mkdir(parents=True, exist_ok=True)
    (img / "123456789.svg").write_bytes(HOSTILE_SVG)
    (img / "987654321.png").write_bytes(PNG)
    app = create_app(tmp_path)
    return login_test_client(app)


def _hardened(r):
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Content-Security-Policy") == g.FILE_RESPONSE_CSP
    assert "sandbox" in g.FILE_RESPONSE_CSP


# ---- /full/: an SVG is a download, a PNG still shows ------------------------------------

def test_a_hostile_svg_via_full_is_an_attachment_with_nosniff_and_csp(tmp_path):
    cli = _library(tmp_path)
    for url in ("/full/123456789", "/full/123456789?dl=1"):
        r = cli.get(url)
        assert r.status_code == 200, url
        assert r.headers["Content-Disposition"].startswith("attachment"), url
        assert "123456789.svg" in r.headers["Content-Disposition"], url
        _hardened(r)
        r.close()


def test_a_png_via_full_still_displays_inline(tmp_path):
    cli = _library(tmp_path)
    r = cli.get("/full/987654321")
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    assert "attachment" not in (r.headers.get("Content-Disposition") or "")
    _hardened(r)
    r.close()
    # the detail page's plain Download still saves it under its own name
    r = cli.get("/full/987654321?dl=1")
    assert r.headers["Content-Disposition"].startswith("attachment")
    r.close()


def test_harden_file_response_downloads_every_type_that_is_not_a_picture_video_or_sound():
    from flask import Flask
    app = Flask("t")
    for mime, inline in (("image/png", True), ("image/webp", True), ("image/gif", True),
                         ("video/mp4", True), ("audio/ogg", True),
                         ("image/svg+xml", False), ("text/html", False),
                         ("application/xhtml+xml", False), ("text/xml", False),
                         ("application/octet-stream", False), ("application/pdf", False)):
        resp = g.harden_file_response(app.response_class(b"x", mimetype=mime), "f.bin")
        cd = resp.headers.get("Content-Disposition") or ""
        assert cd.startswith("attachment") is (not inline), mime
        assert resp.headers["X-Content-Type-Options"] == "nosniff", mime
        assert resp.headers["Content-Security-Policy"] == g.FILE_RESPONSE_CSP, mime


def test_the_attachment_name_is_safe_for_any_file_name():
    cd = g._attachment_disposition('a"b\\c\r\nd é.svg')
    assert cd.startswith('attachment; filename="')
    assert "\r" not in cd and "\n" not in cd
    plain = cd.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in plain and "\\" not in plain
    assert "filename*=UTF-8''" in cd


def test_thumbs_carry_the_same_headers(tmp_path):
    cli = _library(tmp_path)
    tdir = tmp_path / "gallery" / "thumbs"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "987654321.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)
    r = cli.get("/thumbs/987654321.jpg")
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"
    assert "attachment" not in (r.headers.get("Content-Disposition") or "")
    _hardened(r)
    r.close()


# ---- /branding/: pictures only ------------------------------------------------------------

def _drop(rel, data):
    p = branding_mod._role_dir("marks") / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_branding_serves_raster_pictures_with_nosniff(tmp_path):
    cli = create_app(tmp_path).test_client()            # anonymous: the route is PUBLIC
    for name in ("free.png", "free.jpg", "free.jpeg", "free.webp", "free.gif", "free.ico",
                 "free.avif"):
        _drop(name, PNG)
        r = cli.get("/branding/marks/" + name)
        assert r.status_code == 200, name
        assert "attachment" not in (r.headers.get("Content-Disposition") or ""), name
        assert r.headers.get("X-Content-Type-Options") == "nosniff", name
        r.close()


def test_branding_refuses_every_other_type_loose_or_not(tmp_path):
    cli = create_app(tmp_path).test_client()            # anonymous
    for name, data in (("evil.html", b"<script>alert(1)</script>"),
                       ("evil.htm", b"<script>alert(1)</script>"),
                       ("evil.svg", HOSTILE_SVG), ("evil.xml", b"<x/>"),
                       ("evil.js", b"alert(1)"), ("evil.css", b"*{}"),
                       ("notes.txt", b"hi"), ("song.mp3", b"ID3"), ("clip.mp4", b"\x00" * 8),
                       ("marks.json", b'{"marks": []}'), ("noext", b"x")):
        _drop(name, data)
        assert cli.get("/branding/marks/" + name).status_code == 404, name
    # a drop-in sound under sfx/ is not a picture either: the app's synth chime plays instead
    sfx = branding_mod.branding_root() / "sfx"
    sfx.mkdir(parents=True, exist_ok=True)
    (sfx / "ach_gold.ogg").write_bytes(b"OggS")
    assert cli.get("/branding/sfx/ach_gold.ogg").status_code == 404


def test_branding_type_rule_names_only_the_shipped_moment_media():
    serves = branding_mod.branding_serves_type
    coded = branding_mod._public_rel_to_coded
    for name in branding_mod._MOMENT_CLIPS.values():
        assert serves(coded(name)), name
    for name in ("ee_starfall_cast.ogg", "ee_starfall_loop.ogg"):
        assert serves(coded(name)), name
        assert serves(coded(name).upper()), name           # the FS is case-insensitive
    for rel in ("ee_other_clip.mp4", "ee_other.ogg", "sfx/ach_gold.ogg", "marks/x.svg",
                "marks/x.html", "marks/marks.json", "x.png.html", "x", "dir.png/x"):
        assert not serves(coded(rel)), rel
    for rel in ("logo.png", "marks/x.webp", "banner.png", "favicon.ico", "X.PNG"):
        assert serves(coded(rel)), rel
