"""Issue #30 -- the card placard's per-card data: task_id/title on the library payload,
the page-batched POST /api/siblings read, the 32px `?s=32` strip-thumb tier, and the
batch filter matching task_id (so "View Batch" works on an --organize'd library,
which blanks the batch column).
"""
import time
from pathlib import Path

import moonglade_gallery as G


def _seed(tmp_path, rows):
    from moonglade_gallery import CATALOG_FIELDS, save_catalog
    (tmp_path / "2026-08").mkdir(parents=True, exist_ok=True)
    full = []
    for r in rows:
        name = "2026-08/pic_%s.png" % r["media_id"]
        (tmp_path / name).write_bytes(b"\x00" * 16)
        full.append({f: "" for f in CATALOG_FIELDS} | {
            "filename": name, "created_at": "2026-08-22T01:02:03Z"} | r)
    save_catalog(tmp_path / "catalog.db", full)


def _client(tmp_path):
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    return login_test_client(create_app(tmp_path))


# ---- /api/siblings ------------------------------------------------------------------

def test_siblings_returns_multi_member_tasks_with_self_ordered_by_media_id(tmp_path):
    _seed(tmp_path, [
        {"media_id": "903", "task_id": "T1"},
        {"media_id": "901", "task_id": "T1"},
        {"media_id": "902", "task_id": "T1", "is_video": "1"},
        {"media_id": "950", "task_id": "T2"},          # single output: no strip
        {"media_id": "960", "task_id": "T3"},
        {"media_id": "961", "task_id": "T3"},
    ])
    cli = _client(tmp_path)
    r = cli.post("/api/siblings", json={"task_ids": ["T1", "T2", "T3", "", 42, None, "  "]})
    assert r.status_code == 200, r.get_data(as_text=True)
    by = r.get_json()["by_task"]
    assert set(by) == {"T1", "T3"}
    # self included, ordered by media_id, thumbs carry ?s=32
    assert [m["media_id"] for m in by["T1"]] == ["901", "902", "903"]
    assert [m["is_video"] for m in by["T1"]] == [False, True, False]
    assert all(m["thumb"] == "/thumbs/%s.jpg?s=32" % m["media_id"] for m in by["T1"])
    assert [m["media_id"] for m in by["T3"]] == ["960", "961"]


def test_siblings_never_returns_the_empty_task_id(tmp_path):
    """Every import shares task_id '' -- querying it would make one giant pseudo-batch."""
    _seed(tmp_path, [
        {"media_id": "101", "task_id": ""},
        {"media_id": "102", "task_id": ""},
        {"media_id": "103", "task_id": ""},
    ])
    cli = _client(tmp_path)
    r = cli.post("/api/siblings", json={"task_ids": ["", " ", "T9"]})
    assert r.status_code == 200
    assert r.get_json() == {"by_task": {}}


def test_siblings_caps_at_200_ids(tmp_path, monkeypatch):
    _seed(tmp_path, [
        {"media_id": "201", "task_id": "T0"}, {"media_id": "202", "task_id": "T0"},
        {"media_id": "301", "task_id": "T250"}, {"media_id": "302", "task_id": "T250"},
    ])
    cli = _client(tmp_path)
    # T250 sits past the cap; T0 is first. Only T0 can come back.
    ids = ["T%d" % i for i in range(300)]
    r = cli.post("/api/siblings", json={"task_ids": ids})
    assert r.status_code == 200
    assert set(r.get_json()["by_task"]) == {"T0"}


def test_siblings_rejects_a_non_list_body_and_tolerates_an_empty_one(tmp_path):
    _seed(tmp_path, [{"media_id": "1", "task_id": "T1"}])
    cli = _client(tmp_path)
    assert cli.post("/api/siblings", json={"task_ids": "T1"}).status_code == 400
    assert cli.post("/api/siblings", json={}).get_json() == {"by_task": {}}


# ---- library payload -----------------------------------------------------------------

def test_library_items_carry_task_id_and_title(tmp_path):
    _seed(tmp_path, [{"media_id": "777", "task_id": "T77", "title": "  Moonrise  "}])
    cli = _client(tmp_path)
    r = cli.get("/api/next/library")
    assert r.status_code == 200
    item = r.get_json()["items"][0]
    assert item["media_id"] == "777"
    assert item["task_id"] == "T77"
    assert item["title"] == "Moonrise"
    # the stamp's full timestamp is still the existing created_at key (commit 3cdc6b9)
    assert item["created_at"] == "2026-08-22T01:02:03Z"
    for k in ("thumb", "model", "date", "w", "h", "is_video", "rating"):
        assert k in item


# ---- /thumbs/<id>.jpg?s=32 ---------------------------------------------------------------

def _seed_768(tmp_path, mid, color=(200, 30, 30)):
    from PIL import Image
    d = tmp_path / "gallery" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (768, 512), color).save(d / (mid + ".jpg"), "JPEG")
    return d / (mid + ".jpg")


def _size(data):
    import io
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def test_strip_thumb_is_32px_cached_under_gallery_cache_strip(tmp_path):
    _seed(tmp_path, [{"media_id": "555", "task_id": "T1"}])
    _seed_768(tmp_path, "555")
    cli = _client(tmp_path)
    r = cli.get("/thumbs/555.jpg?s=32")
    assert r.status_code == 200
    w, h = _size(r.data)
    assert max(w, h) <= 32 and w == 32, (w, h)   # aspect kept, longest side 32
    assert r.headers["Cache-Control"] == "public, max-age=86400"
    cached = tmp_path / "gallery" / "cache" / "_strip" / "555.jpg"
    assert cached.is_file()
    assert _size(cached.read_bytes())[0] == 32
    # nothing written into the goods tree
    assert not list((tmp_path / "2026-08").glob("*.jpg"))


def test_strip_thumb_regenerates_when_the_768_thumb_is_newer(tmp_path):
    _seed(tmp_path, [{"media_id": "556", "task_id": "T1"}])
    src = _seed_768(tmp_path, "556", (10, 10, 200))
    cli = _client(tmp_path)
    assert cli.get("/thumbs/556.jpg?s=32").status_code == 200
    cached = tmp_path / "gallery" / "cache" / "_strip" / "556.jpg"
    first = cached.read_bytes()
    # re-cut the 768 (a rebuilt poster), stamped newer than the cache
    _seed_768(tmp_path, "556", (10, 200, 10))
    newer = cached.stat().st_mtime + 5
    import os
    os.utime(src, (newer, newer))
    r = cli.get("/thumbs/556.jpg?s=32")
    assert r.status_code == 200
    assert cached.read_bytes() != first


def test_strip_thumb_unlisted_size_and_missing_768_fall_through(tmp_path):
    _seed(tmp_path, [{"media_id": "557", "task_id": "T1"}, {"media_id": "558", "task_id": "T1"}])
    _seed_768(tmp_path, "557")
    cli = _client(tmp_path)
    # ?s=999 is not on the allowlist: the normal 768 thumb, normal cache policy
    r = cli.get("/thumbs/557.jpg?s=999")
    assert r.status_code == 200
    assert _size(r.data) == (768, 512)
    assert r.headers["Cache-Control"] == "public, max-age=300"
    assert not (tmp_path / "gallery" / "cache" / "_strip" / "557.jpg").exists()
    # no 768 thumb at all: same answer the plain route gives (a 404), no cache file
    assert cli.get("/thumbs/558.jpg?s=32").status_code == 404
    assert not (tmp_path / "gallery" / "cache" / "_strip").exists()


# ---- batch filter matches task_id ---------------------------------------------------

def test_build_where_batch_matches_task_id_column_too():
    where, params = G._build_where("", "", "", "", batch="T1")
    assert "(batch = ? OR task_id = ?)" in where
    assert params == ["T1", "T1"]


def test_query_catalog_batch_finds_an_organized_row_by_task_id(tmp_path):
    """--organize blanks `batch`; the Details "View Batch" button passes task_id."""
    _seed(tmp_path, [
        {"media_id": "601", "task_id": "T1", "batch": ""},
        {"media_id": "602", "task_id": "T1", "batch": ""},
        {"media_id": "603", "task_id": "T2", "batch": "legacy-folder"},
        {"media_id": "604", "task_id": "T3", "batch": ""},
    ])
    rows, total = G.query_catalog(tmp_path / "catalog.db", batch="T1")
    assert total == 2 and {r["media_id"] for r in rows} == {"601", "602"}
    # the legacy folder-name batch still resolves through the same param
    rows, total = G.query_catalog(tmp_path / "catalog.db", batch="legacy-folder")
    assert total == 1 and rows[0]["media_id"] == "603"
    # and through the route the button actually hits
    cli = _client(tmp_path)
    d = cli.get("/api/next/library?batch=T1").get_json()
    assert d["total"] == 2 and {i["media_id"] for i in d["items"]} == {"601", "602"}
