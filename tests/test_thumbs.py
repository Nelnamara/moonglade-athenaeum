"""Thumbnail rebuild + the ffmpeg video-poster fallback: poster-less videos get a
locally-extracted frame instead of staying blank forever; --rebuild-thumbs re-renders
every image thumb at today's settings and sweeps orphans. All fail-soft."""
from types import SimpleNamespace

import pixai_gallery as g
import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _png(path):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (100, 50, 150)).save(path)


def test_build_thumbnails_video_fallback(tmp_path, monkeypatch):
    thumbs = tmp_path / "gallery" / "thumbs"
    thumbs.mkdir(parents=True)
    _png(tmp_path / "a_1.png")                          # image, thumb missing
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "v_2.mp4").write_bytes(b"x")  # video, thumb missing
    (tmp_path / "videos" / "v_3.mp4").write_bytes(b"x")  # video, thumb EXISTS
    _png(thumbs / "3.jpg")                               # ...the existing poster
    rows = [
        _row(media_id="1", filename="a_1.png"),
        _row(media_id="2", filename="videos/v_2.mp4", is_video="1"),
        _row(media_id="3", filename="videos/v_3.mp4", is_video="1"),
    ]
    called = []

    def fake_vthumb(video_path, thumb_path):
        called.append(str(video_path))
        _png(thumb_path)
        return True
    monkeypatch.setattr(g, "make_video_thumbnail", fake_vthumb)
    g.build_thumbnails(rows, tmp_path, thumbs, force=True, workers=1)
    # the poster-less video got the ffmpeg fallback...
    assert len(called) == 1 and called[0].endswith("v_2.mp4")
    assert (thumbs / "2.jpg").exists()
    # ...the image thumb regenerated, and the existing video poster was NOT
    # overwritten even under force (it came from the network; can't regen)
    assert (thumbs / "1.jpg").exists() and (thumbs / "3.jpg").exists()


def test_make_video_thumbnail_fail_soft(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _x: None)   # no ffmpeg anywhere
    assert g.make_video_thumbnail(tmp_path / "nope.mp4",
                                  tmp_path / "t.jpg") is False
    assert not (tmp_path / "t.jpg").exists()


def test_rebuild_thumbs_sweeps_orphans_and_regens(tmp_path, monkeypatch):
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.png")])
    _png(tmp_path / "a_1.png")
    thumbs = tmp_path / "gallery" / "thumbs"
    _png(thumbs / "1.jpg")            # stale-quality thumb -> regenerated
    _png(thumbs / "999.jpg")          # orphan (media gone) -> swept
    before = (thumbs / "1.jpg").stat().st_mtime_ns
    out = core.run_rebuild_thumbs(SimpleNamespace(out=str(tmp_path), workers=1,
                                                  progress=None))
    assert out["swept"] == 1
    assert not (thumbs / "999.jpg").exists()
    assert (thumbs / "1.jpg").exists()
    assert (thumbs / "1.jpg").stat().st_mtime_ns >= before   # rewritten in place
