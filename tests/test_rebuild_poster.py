"""POST /api/rebuild-poster/<media_id>: regenerate ONE video's poster thumb from its file.
Built for the fade-in case (a clip thumbnailed inside its fade) so a single poster can be
redone without a whole --rebuild-thumbs pass (owner, 2026-08-22). Videos only.
"""
from pathlib import Path

import moonglade_gallery as G


def _seed(tmp_path, mid, is_video):
    from moonglade_gallery import CATALOG_FIELDS, save_catalog
    (tmp_path / "videos").mkdir(parents=True, exist_ok=True)
    name = ("videos/clip_%s.mp4" if is_video else "videos/pic_%s.png") % mid
    (tmp_path / name).write_bytes(b"\x00" * 64)
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": mid, "filename": name, "is_video": "1" if is_video else "",
        "created_at": "2026-08-22T00:00:00Z"}])


def test_rebuild_poster_regenerates_a_video_thumb(tmp_path, monkeypatch):
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    _seed(tmp_path, "555", is_video=True)
    calls = []

    def fake_make(video_path, thumb_path):
        calls.append((Path(video_path).name, Path(thumb_path).name))
        Path(thumb_path).parent.mkdir(parents=True, exist_ok=True)
        Path(thumb_path).write_bytes(b"jpg")
        return True
    monkeypatch.setattr(G, "make_video_thumbnail", fake_make)

    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/rebuild-poster/555")
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["ok"] is True
    assert calls == [("clip_555.mp4", "555.jpg")], calls
    # cache-busted so the browser shows the new frame immediately
    assert d["thumb"].startswith("/thumbs/555.jpg?v=")


def test_rebuild_poster_refuses_an_image(tmp_path, monkeypatch):
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    _seed(tmp_path, "777", is_video=False)
    monkeypatch.setattr(G, "make_video_thumbnail", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/rebuild-poster/777")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_rebuild_poster_unknown_id_is_404(tmp_path):
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    _seed(tmp_path, "555", is_video=True)
    cli = login_test_client(create_app(tmp_path))
    assert cli.post("/api/rebuild-poster/000").status_code == 404


def test_rebuild_poster_reports_ffmpeg_failure_softly(tmp_path, monkeypatch):
    """ffmpeg missing / extract failing is a soft {ok:false,error}, never a 500."""
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    _seed(tmp_path, "555", is_video=True)
    monkeypatch.setattr(G, "make_video_thumbnail", lambda *a, **k: False)
    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/rebuild-poster/555")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is False and "ffmpeg" in d["error"]


def test_rebuild_poster_finds_a_moved_video_via_the_matcher(tmp_path, monkeypatch):
    """The catalog row's filename is stale (the clip was moved by --organize); the route must
    fall back to find_files_for_media_id told to look for VIDEO extensions. Pins the fallback
    branch -- a NameError hid there once because the happy path never reached it."""
    from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog
    from tests.conftest import login_test_client
    (tmp_path / "2026-08").mkdir(parents=True, exist_ok=True)
    # the real file sits where organize put it; the row still names the old path
    (tmp_path / "2026-08" / "moved_clip_555.mp4").write_bytes(bytes(64))
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "555", "filename": "videos/gone_555.mp4", "is_video": "1",
        "created_at": "2026-08-22T00:00:00Z"}])
    calls = []
    def fake_make(video_path, thumb_path):
        calls.append(Path(video_path).name); return True
    monkeypatch.setattr(G, "make_video_thumbnail", fake_make)
    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/rebuild-poster/555")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ok"] is True
    assert calls == ["moved_clip_555.mp4"], calls
