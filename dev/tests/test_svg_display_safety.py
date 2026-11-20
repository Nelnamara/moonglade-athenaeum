"""An Edit Pro SVG is shown only through <img>, and never becomes a page (DESIGN_3.22 5.4, S5).

For <img src> to draw an SVG the response needs its real type, so 3.22 sends image/svg+xml --
and keeps every other guard 3.21.1 put on it: Content-Disposition: attachment (a direct visit
is a download), nosniff, and a CSP sandbox that fetches nothing and allows only its own inline
styles, the belt if a browser ignores the disposition. Mutation target 19's display half: an
SVG served inline, or without attachment or the sandbox CSP, turns a test here red. Nothing
here touches the network.
"""
from flask import Flask

from moonglade import gallery as g
from tests.conftest import login_test_client

HOSTILE_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg">'
               b'<script>fetch("/api/whoami")</script><rect width="4" height="4"/></svg>')
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _library(tmp_path):
    (tmp_path / "images").mkdir(parents=True, exist_ok=True)
    (tmp_path / "images" / "123456789.svg").write_bytes(HOSTILE_SVG)
    (tmp_path / "images" / "987654321.png").write_bytes(PNG)
    return login_test_client(g.create_app(tmp_path))


def test_the_svg_policy_is_the_designs_exactly():
    assert g.SVG_FILE_CSP == "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    assert g.media_type_for("logo.SVG") == "image/svg+xml"
    assert "image/svg+xml" not in g._INLINE_FILE_TYPES


def test_an_svg_goes_out_as_an_image_type_download_under_the_sandbox(tmp_path):
    cli = _library(tmp_path)
    for url in ("/full/123456789", "/full/123456789?dl=1"):
        r = cli.get(url)
        assert r.status_code == 200, url
        assert r.mimetype == "image/svg+xml", url
        assert r.headers["Content-Disposition"].startswith("attachment"), url
        assert r.headers["X-Content-Type-Options"] == "nosniff", url
        assert r.headers["Content-Security-Policy"] == g.SVG_FILE_CSP, url
        assert r.data == HOSTILE_SVG, url            # the file itself, never rewritten
        r.close()


def test_a_png_is_unchanged(tmp_path):
    r = _library(tmp_path).get("/full/987654321")
    assert r.mimetype == "image/png"
    assert "attachment" not in (r.headers.get("Content-Disposition") or "")
    assert r.headers["Content-Security-Policy"] == g.FILE_RESPONSE_CSP
    r.close()


def test_an_svg_named_file_gets_the_svg_policy_whatever_type_a_route_guessed():
    app = Flask("t")
    for mime in ("text/xml", "application/octet-stream", "image/svg+xml", "text/plain"):
        resp = g.harden_file_response(app.response_class(b"<svg/>", mimetype=mime), "x/a.svg")
        assert resp.headers["Content-Security-Policy"] == g.SVG_FILE_CSP, mime
        assert resp.headers["Content-Disposition"].startswith("attachment"), mime
        assert resp.headers["X-Content-Type-Options"] == "nosniff", mime
