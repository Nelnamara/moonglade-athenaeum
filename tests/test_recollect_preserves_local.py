"""Re-collecting a generation must not erase what you did to it locally.

The live bug (owner, 2026-09-03): a published piece lost its artwork_id when a relaunch
re-polled an already-finished task. Both download paths rebuilt their catalog rows from a
blank CATALOG_FIELDS template and upserted them raw, so every locally-owned field --
artwork_id, is_published, title, rating, collections, art_tags, aes_score, blurhash --
was blanked by the write. carry_local_fields is the guard that exists for exactly this
class of bug and neither path applied it.

These tests drive the real functions with the download stubbed to "skip", which is the
exact live shape: the file is already on disk, so nothing is fetched -- and the row is
rebuilt and written anyway.
"""
import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, load_catalog, save_catalog

from tests.conftest import login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# The locally-owned fields a re-collect used to blank. Named once, asserted everywhere.
LOCAL = {
    "artwork_id": "aw-77", "is_published": "1", "title": "The Nightfallen",
    "rating": "5", "collections": "Favourites, Prints", "art_tags": "elf, moon",
    "aes_score": "7.25", "blurhash": "LEHV6nWB2yk8",
}


class _Args:
    name_length = 60
    name_sep = "_"
    out = "."


def _seed(tmp_path, media_id="m1", **extra):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id=media_id, task_id="t1", filename="images/old.png",
                           created_at="2026-01-01T00:00:00", **dict(LOCAL, **extra))])
    return db


def _stub_download(monkeypatch, out, name="old.png", sub="images"):
    """The live shape: the file is already there, so download answers 'skip' -- and the
    row is rebuilt and upserted regardless."""
    path = out / sub / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really an image")
    monkeypatch.setattr(core, "download", lambda s, url, stem: ("skip", path))
    return path


def test_recollecting_an_image_keeps_every_local_field(tmp_path, monkeypatch):
    db = _seed(tmp_path)
    _stub_download(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "resolve_media", lambda s, mid: ("https://x/i.png", {}))
    monkeypatch.setattr(core, "_task_image_media", lambda outputs: [("m1", "12345")])
    monkeypatch.setattr(core, "extract_full_meta", lambda r: {})
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, r: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)

    core._download_image_task(object(), {"outputs": {"x": 1}}, "t1", tmp_path, _Args(),
                              prompt="a moon")

    row = {r["media_id"]: r for r in load_catalog(db)}["m1"]
    for field, value in LOCAL.items():
        assert row[field] == value, "%s was erased by the re-collect" % field
    # ...and the download pass still wrote what it legitimately owns
    assert row["task_id"] == "t1" and row["seed"] == "12345"
    assert row["source"] == "api" and row["filename"].endswith("old.png")


def test_recollecting_a_video_keeps_every_local_field(tmp_path, monkeypatch):
    db = _seed(tmp_path, media_id="v1", is_video="1")
    _stub_download(monkeypatch, tmp_path, name="old.mp4", sub="videos")
    monkeypatch.setattr(core, "video_outputs",
                        lambda result: ([{"video_media_id": "v1"}], {"prompt": "a moon"}))
    monkeypatch.setattr(core, "media_file_gql",
                        lambda s, mid: {"fileUrl": "https://x/v.mp4", "duration": 5})
    monkeypatch.setattr(core, "extract_full_meta", lambda r: {})
    monkeypatch.setattr(core, "video_faststart", lambda p: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(core, "make_video_thumbnail", lambda *a, **k: None, raising=False)

    core._download_video_task(object(), {"outputs": {}}, "t1", tmp_path, _Args(), {})

    row = {r["media_id"]: r for r in load_catalog(db)}["v1"]
    for field, value in LOCAL.items():
        assert row[field] == value, "%s was erased by the re-collect" % field
    assert row["is_video"] == "1" and row["filename"].endswith("old.mp4")


def test_a_fresh_media_id_still_catalogs_normally(tmp_path, monkeypatch):
    """The carry must not turn a first collect into a no-op: a media_id absent from the
    snapshot passes straight through."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    _stub_download(monkeypatch, tmp_path, name="new.png")
    monkeypatch.setattr(core, "resolve_media", lambda s, mid: ("https://x/i.png", {}))
    monkeypatch.setattr(core, "_task_image_media", lambda outputs: [("mNEW", "999")])
    monkeypatch.setattr(core, "extract_full_meta", lambda r: {})
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, r: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)

    core._download_image_task(object(), {"outputs": {"x": 1}}, "t9", tmp_path, _Args(),
                              prompt="new one")

    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert "mNEW" in rows and rows["mNEW"]["task_id"] == "t9"
    assert rows["mNEW"]["artwork_id"] == "" and rows["mNEW"]["rating"] == ""


def test_the_very_first_collect_has_no_catalog_to_snapshot(tmp_path, monkeypatch):
    """The snapshot reads the catalog BEFORE save_catalog creates it, so on a fresh output
    folder there is no table yet. Nothing local to carry is an empty map, not a crash."""
    _stub_download(monkeypatch, tmp_path, name="first.png")
    monkeypatch.setattr(core, "resolve_media", lambda s, mid: ("https://x/i.png", {}))
    monkeypatch.setattr(core, "_task_image_media", lambda outputs: [("m0", "1")])
    monkeypatch.setattr(core, "extract_full_meta", lambda r: {})
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, r: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    assert not (tmp_path / "catalog.db").exists()

    core._download_image_task(object(), {"outputs": {"x": 1}}, "t0", tmp_path, _Args(),
                              prompt="the first one")

    assert [r["media_id"] for r in load_catalog(tmp_path / "catalog.db")] == ["m0"]


# ---- the route-level guard --------------------------------------------------

def _client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_test_client(create_app(tmp_path))


def test_a_second_poll_of_a_done_task_does_not_collect_again(tmp_path, monkeypatch):
    """The reachable path: api_task_status's done branch had no already-cataloged check,
    and the single-flight entry is dropped once its waiters leave -- so a later poll of the
    same finished task re-ran the collect and re-upserted over the local fields."""
    calls = {"n": 0}

    def _collect(session, tid, out):
        calls["n"] += 1
        return {"media_ids": ["m1"], "saved": 1, "is_video": False}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "collect_generation", _collect)
    monkeypatch.setattr(core, "generation_status",
                        lambda s, t: {"phase": "done", "paid_credit": 0})
    # the task's media is ALREADY catalogued, with local curation on it
    cli = _client(tmp_path, [_row(media_id="m1", task_id="t1", filename="images/a.png",
                                  created_at="2026-01-01T00:00:00", **LOCAL)])

    d = cli.get("/api/task-status", query_string={"task_id": "t1"}).get_json()
    assert d["phase"] == "done"
    assert d.get("media_ids") == ["m1"], "it still answers with the media"
    assert calls["n"] == 0, "an already-collected task must not be collected again"

    # ...and the local fields are untouched, which is the whole point
    row = {r["media_id"]: r for r in load_catalog(tmp_path / "catalog.db")}["m1"]
    assert row["artwork_id"] == LOCAL["artwork_id"] and row["rating"] == LOCAL["rating"]


def test_an_uncollected_done_task_still_collects(tmp_path, monkeypatch):
    """The other half, so the guard cannot be 'achieved' by never collecting."""
    calls = {"n": 0}

    def _collect(session, tid, out):
        calls["n"] += 1
        return {"media_ids": ["mX"], "saved": 1, "is_video": False}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "collect_generation", _collect)
    monkeypatch.setattr(core, "generation_status",
                        lambda s, t: {"phase": "done", "paid_credit": 0})
    cli = _client(tmp_path, [])
    d = cli.get("/api/task-status", query_string={"task_id": "t-new"}).get_json()
    assert d["phase"] == "done" and calls["n"] == 1
