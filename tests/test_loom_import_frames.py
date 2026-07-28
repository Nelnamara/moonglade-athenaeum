"""An imported clip gets its open/close frames from the clip itself.

A shot generated on the board takes its opening frame from whatever was fed in; an imported
clip arrives already rendered, so nothing ever produced those stills and Deep Focus showed two
empty slots. These cover the endpoint that fills them -- and specifically its PARTIAL paths,
because two independent extracts and two independent uploads mean "one end worked" is a normal
outcome rather than an edge case, and the board is written to accept exactly that.

Note the patch target: `_gen_session` and `_find_local_video_file` are closures inside
create_app, so patching them on the gallery module does nothing -- it silently no-ops and the
real API-key path runs instead, which is how the first draft of this file "failed". The seam
that actually works is moonglade_backup itself (the very object `_gen_session` hands back),
plus a real catalog row so the file resolver resolves a real file.
"""
import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog
from tests.conftest import login_client

MID = "42"


def _row(**kw):
    r = {f: "" for f in CATALOG_FIELDS}
    r.update(kw)
    return r


class _Frames:
    """Records what the endpoint asked ffmpeg for, and which ends it lets through."""

    def __init__(self, extract_ok=("first", "last"), upload_ok=("first", "last")):
        self.extract_ok = set(extract_ok)
        self.upload_ok = set(upload_ok)
        self.extracts = []          # [(at_seconds, path)]

    @staticmethod
    def _which(path):
        return "first" if str(path).endswith("_first.png") else "last"

    def extract(self, video_path, out_png, at_seconds=None):
        self.extracts.append((at_seconds, str(out_png)))
        if self._which(out_png) not in self.extract_ok:
            return None
        from PIL import Image                      # a real image: make_thumbnail must open it
        Image.new("RGB", (64, 36), (20, 20, 30)).save(out_png)
        return str(out_png)

    def upload(self, session, path):
        which = self._which(path)
        if which not in self.upload_ok:
            raise RuntimeError("upload refused")
        return "mid_" + which


def _wire(tmp_path, monkeypatch, frames, with_file=True):
    """Seed a catalog video row + the file on disk, and stub the two network seams."""
    rows = []
    if with_file:
        (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        rows = [_row(media_id=MID, filename="clip.mp4", is_video="1")]
    save_catalog(tmp_path / "catalog.db", rows)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "extract_last_frame", frames.extract)
    monkeypatch.setattr(core, "upload_media", frames.upload)
    return login_client(tmp_path)


def _post(cli, mid=MID):
    return cli.post("/api/loom/import-frames", json={"video_media_id": mid})


def test_requires_a_video_media_id(tmp_path):
    r = login_client(tmp_path).post("/api/loom/import-frames", json={})
    assert r.status_code == 400
    assert "video_media_id" in r.get_json()["error"]


def test_clip_not_downloaded_is_a_message_not_a_crash(tmp_path, monkeypatch):
    cli = _wire(tmp_path, monkeypatch, _Frames(), with_file=False)
    r = _post(cli)
    # 200 + an error string: the board surfaces it and the import itself is not rolled back
    assert r.status_code == 200
    assert "collect it first" in r.get_json()["error"]


def test_both_frames_extract_upload_and_thumbnail(tmp_path, monkeypatch):
    frames = _Frames()
    cli = _wire(tmp_path, monkeypatch, frames)
    assert _post(cli).get_json() == {"first_media_id": "mid_first",
                                     "last_media_id": "mid_last"}
    # The one behavioural fact the whole feature rests on: extract_last_frame is general, and
    # at_seconds=0.0 is what makes it yield an OPENING frame (None keeps the EOF-relative path).
    assert [at for at, _ in frames.extracts] == [0.0, None]
    # /thumbs/<id>.jpg serves from disk with no fetch-on-miss, so an un-thumbnailed frame
    # renders as a blank box with a perfectly good media id behind it
    thumbs = tmp_path / "gallery" / "thumbs"
    assert (thumbs / "mid_first.jpg").exists()
    assert (thumbs / "mid_last.jpg").exists()


def test_one_end_failing_to_extract_still_lands_the_other(tmp_path, monkeypatch):
    cli = _wire(tmp_path, monkeypatch, _Frames(extract_ok=("first",)))
    assert _post(cli).get_json() == {"first_media_id": "mid_first"}


def test_one_end_failing_to_upload_still_lands_the_other(tmp_path, monkeypatch):
    cli = _wire(tmp_path, monkeypatch, _Frames(upload_ok=("last",)))
    # a refused upload is swallowed per-end, not escalated into a whole-request failure
    assert _post(cli).get_json() == {"last_media_id": "mid_last"}


def test_both_ends_failing_is_an_error_not_an_empty_success(tmp_path, monkeypatch):
    cli = _wire(tmp_path, monkeypatch, _Frames(extract_ok=()))
    body = _post(cli).get_json()
    assert "error" in body and "ffmpeg" in body["error"]
    # an empty 200 would read to the board as "worked, no frames" and silently do nothing
    assert "first_media_id" not in body and "last_media_id" not in body
