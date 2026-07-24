"""The trash/quarantine restore panel (docs/AUDIT_2026-07-21.md's restore-panel row,
shipped 2026-07-24): _deleted/ had ~12k files with no restore UI even though the
delete confirm promises files are "recoverable". Covers the pure directory-scan/
restore/delete helpers (list_quarantined, restore_quarantined_media,
delete_quarantined_forever, empty_trash, the purge-time sidecar snapshot) and the
four /api/trash/* routes, including the tier gate itself (restore=LOGIN,
delete-forever/empty=LOCALHOST+confirm=true) -- see tests/test_purge.py and
tests/test_web_pick.py for the conventions this file follows."""
import json
import os
import time

import pixai_gallery as g
from pixai_gallery import (CATALOG_FIELDS, create_app, load_catalog, save_catalog,
                           purge_media_local)

from tests.conftest import login_client

LAN = "203.0.113.5"      # TEST-NET-3, matching tests/test_route_tiers.py's stand-in


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _png_bytes():
    # A real (tiny) PNG, not arbitrary bytes -- make_thumbnail() shells out to
    # Pillow's Image.open(), which raises on non-image bytes and would make every
    # thumbnail-generation assertion below fail-soft into a false pass.
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (80, 40, 120)).save(buf, "PNG")
    return buf.getvalue()


def _seed_quarantined(out_dir, media_id, filename="{}.png", mtime=None, content=None):
    """Drop a file DIRECTLY into _deleted/ -- bypassing purge_media_local -- to
    simulate a pre-2026-07-24 quarantined file with no sidecar."""
    qdir = out_dir / g.DELETED_DIRNAME
    qdir.mkdir(parents=True, exist_ok=True)
    name = filename.format(media_id)
    p = qdir / name
    p.write_bytes(content if content is not None else _png_bytes())
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


# ---------------------------------------------------------------------------
# purge_media_local's new sidecar snapshot
# ---------------------------------------------------------------------------

def test_purge_writes_a_trash_sidecar_snapshot(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="55", filename="55.png", rating="4", collections="favorites",
            prompt_full="a lonely lighthouse", task_id="T55"),
    ])
    img = tmp_path / "images"; img.mkdir()
    (img / "55.png").write_bytes(_png_bytes())
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)

    purge_media_local(tmp_path, thumb, tmp_path / "catalog.db", "55", "55.png")

    meta_path = tmp_path / g.DELETED_DIRNAME / "55.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["rating"] == "4"
    assert meta["collections"] == "favorites"
    assert meta["prompt_full"] == "a lonely lighthouse"
    assert meta["task_id"] == "T55"
    assert isinstance(meta["_deleted_at"], (int, float)) and meta["_deleted_at"] > 0


def test_purge_hard_delete_skips_the_sidecar(tmp_path):
    """quarantine=False leaves nothing to restore -- nothing worth snapshotting."""
    save_catalog(tmp_path / "catalog.db", [_row(media_id="9", filename="9.png")])
    img = tmp_path / "images"; img.mkdir()
    (img / "9.png").write_bytes(_png_bytes())

    purge_media_local(tmp_path, tmp_path / "t", tmp_path / "catalog.db", "9", "9.png",
                      quarantine=False)

    assert not (tmp_path / g.DELETED_DIRNAME).exists()


def test_purge_missing_row_writes_no_sidecar(tmp_path):
    """_snapshot_before_purge must not fabricate a row for a media_id that was
    never in the catalog to begin with (e.g. a stray on-disk file)."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [])                    # a real (empty) catalog -- just no "404" row
    img = tmp_path / "images"; img.mkdir()
    (img / "404.png").write_bytes(_png_bytes())
    purge_media_local(tmp_path, tmp_path / "t", db, "404", "404.png")
    assert not (tmp_path / g.DELETED_DIRNAME / "404.json").exists()
    assert (tmp_path / g.DELETED_DIRNAME / "404.png").exists()   # file still quarantined


# ---------------------------------------------------------------------------
# list_quarantined()
# ---------------------------------------------------------------------------

def test_list_quarantined_empty_when_no_deleted_dir(tmp_path):
    items, total, total_bytes = g.list_quarantined(tmp_path)
    assert items == [] and total == 0 and total_bytes == 0


def test_list_quarantined_paginates_newest_first(tmp_path):
    base = time.time()
    # mtime = base - (5-i): media_id "0" gets the OLDEST mtime (base-5), "4" the
    # NEWEST (base-1) -- so newest-first order is 4, 3, 2, 1, 0.
    for i in range(5):
        _seed_quarantined(tmp_path, str(i), mtime=base - (5 - i))
    items, total, total_bytes = g.list_quarantined(tmp_path, page=1, page_size=2)
    assert total == 5
    assert total_bytes == sum((tmp_path / g.DELETED_DIRNAME / "{}.png".format(i)).stat().st_size
                              for i in range(5))
    assert len(items) == 2
    # newest mtime (i=4, base-1) must lead
    assert items[0]["media_id"] == "4"
    assert items[1]["media_id"] == "3"
    page2, _, _ = g.list_quarantined(tmp_path, page=2, page_size=2)
    assert [it["media_id"] for it in page2] == ["2", "1"]
    page3, _, _ = g.list_quarantined(tmp_path, page=3, page_size=2)
    assert [it["media_id"] for it in page3] == ["0"]


def test_list_quarantined_prefers_sidecar_deleted_at_and_prompt(tmp_path):
    _seed_quarantined(tmp_path, "77", mtime=time.time() - 99999)   # old mtime
    real_deleted_at = time.time()
    (tmp_path / g.DELETED_DIRNAME / "77.json").write_text(
        json.dumps({"prompt_full": "a stormy harbor", "_deleted_at": real_deleted_at}),
        encoding="utf-8")

    items, _, _ = g.list_quarantined(tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it["has_meta"] is True
    assert it["prompt"] == "a stormy harbor"
    assert it["deleted_at"] == real_deleted_at   # NOT the stale file mtime


def test_list_quarantined_sorts_by_sidecar_deleted_at_not_stale_mtime(tmp_path):
    """purge_media_local moves a file into _deleted/ with img.replace(dest) -- a
    same-volume rename -- which does NOT update mtime on Windows/NTFS (mtime tracks
    content writes, not moves/renames). So a quarantined file's mtime really means
    "when it was originally downloaded", not "when it was deleted". Two items both
    with an accurate sidecar, but whose mtimes are in the OPPOSITE order from their
    real delete times, must sort by the sidecar's delete time -- caught live-testing
    this feature, where an old download deleted moments ago sorted BELOW a newer
    download deleted earlier the same session."""
    # media_id_of() takes the LAST underscore-delimited chunk of the stem (real
    # PixAI media_ids are purely numeric) -- these use plain numeric ids so the
    # test doesn't trip over that unrelated parsing rule.
    now = time.time()
    _seed_quarantined(tmp_path, "9001", mtime=now - 500000)     # ancient mtime...
    (tmp_path / g.DELETED_DIRNAME / "9001.json").write_text(
        json.dumps({"_deleted_at": now}), encoding="utf-8")     # ...deleted just now
    _seed_quarantined(tmp_path, "9002", mtime=now - 10)         # recent mtime...
    (tmp_path / g.DELETED_DIRNAME / "9002.json").write_text(
        json.dumps({"_deleted_at": now - 100}), encoding="utf-8")   # ...deleted earlier

    items, total, _ = g.list_quarantined(tmp_path)
    assert total == 2
    assert [it["media_id"] for it in items] == ["9001", "9002"]


def test_list_quarantined_falls_back_to_mtime_without_a_sidecar(tmp_path):
    """Pre-2026-07-24 quarantined files: no sidecar exists at all."""
    mt = time.time() - 500
    _seed_quarantined(tmp_path, "1", mtime=mt)
    items, _, _ = g.list_quarantined(tmp_path)
    assert items[0]["has_meta"] is False
    assert items[0]["deleted_at"] == mt
    assert items[0]["prompt"] == ""


def test_list_quarantined_detects_video_extension(tmp_path):
    _seed_quarantined(tmp_path, "9", filename="{}.mp4", content=b"not really a video")
    items, total, _ = g.list_quarantined(tmp_path)
    assert total == 1
    assert items[0]["is_video"] == "1"
    assert items[0]["filename"] == "9.mp4"


def test_list_quarantined_skips_sidecar_json_as_an_item(tmp_path):
    """A '<media_id>.json' sidecar must never itself be listed as a trash item --
    only the real media file it describes."""
    _seed_quarantined(tmp_path, "3")
    (tmp_path / g.DELETED_DIRNAME / "3.json").write_text("{}", encoding="utf-8")
    items, total, _ = g.list_quarantined(tmp_path)
    assert total == 1
    assert items[0]["media_id"] == "3"


# ---------------------------------------------------------------------------
# _find_quarantined_file() -- the sidecar-vs-media disambiguation
# ---------------------------------------------------------------------------

def test_find_quarantined_file_ignores_the_json_sidecar(tmp_path):
    p = _seed_quarantined(tmp_path, "12")
    (tmp_path / g.DELETED_DIRNAME / "12.json").write_text("{}", encoding="utf-8")
    found = g._find_quarantined_file(tmp_path, "12")
    assert found == p


def test_find_quarantined_file_returns_none_when_absent(tmp_path):
    assert g._find_quarantined_file(tmp_path, "nope") is None


# ---------------------------------------------------------------------------
# restore_quarantined_media()
# ---------------------------------------------------------------------------

def test_restore_recovers_the_full_row_from_its_sidecar(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="55", filename="55.png", rating="5",
                           collections="favorites", prompt_full="a lonely lighthouse")])
    img = tmp_path / "images"; img.mkdir()
    (img / "55.png").write_bytes(_png_bytes())
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    purge_media_local(tmp_path, thumb, db, "55", "55.png")
    assert load_catalog(db) == []                     # sanity: really purged first

    res = g.restore_quarantined_media(tmp_path, thumb, db, "55")

    assert res == {"ok": True, "media_id": "55", "filename": "55.png"}
    assert (tmp_path / "images" / "55.png").exists()
    assert not (tmp_path / g.DELETED_DIRNAME / "55.png").exists()
    assert not (tmp_path / g.DELETED_DIRNAME / "55.json").exists()   # sidecar consumed
    rows = load_catalog(db)
    assert len(rows) == 1
    assert rows[0]["rating"] == "5"
    assert rows[0]["collections"] == "favorites"
    assert rows[0]["prompt_full"] == "a lonely lighthouse"


def test_restore_without_a_sidecar_gets_a_minimal_row(tmp_path):
    """A file quarantined before this feature shipped (or whose sidecar write
    failed) must still come back and be visible in the gallery, even with no
    history to restore beyond its filename."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    _seed_quarantined(tmp_path, "old1", filename="old1.png")
    thumb = tmp_path / "gallery" / "thumbs"

    res = g.restore_quarantined_media(tmp_path, thumb, db, "old1")

    assert res["ok"] is True
    assert (tmp_path / "images" / "old1.png").exists()
    rows = load_catalog(db)
    assert len(rows) == 1 and rows[0]["media_id"] == "old1"
    assert rows[0]["filename"] == "old1.png"
    assert rows[0]["rating"] == ""                    # nothing to recover, and that's OK


def test_restore_unknown_media_id_fails_cleanly(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    res = g.restore_quarantined_media(tmp_path, tmp_path / "t", db, "ghost")
    assert res == {"ok": False, "error": "not found in trash"}
    assert load_catalog(db) == []


def test_restore_avoids_clobbering_a_same_named_live_file(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    images = tmp_path / "images"; images.mkdir()
    (images / "77.png").write_bytes(b"LIVE FILE, DO NOT OVERWRITE")
    _seed_quarantined(tmp_path, "77")             # writes _deleted/77.png

    res = g.restore_quarantined_media(tmp_path, tmp_path / "t", db, "77")

    assert res["ok"] is True
    assert res["filename"] != "77.png"                # renamed to avoid the collision
    assert (images / "77.png").read_bytes() == b"LIVE FILE, DO NOT OVERWRITE"
    assert (images / res["filename"]).exists()


# ---------------------------------------------------------------------------
# delete_quarantined_forever() / empty_trash()
# ---------------------------------------------------------------------------

def test_delete_quarantined_forever_removes_file_sidecar_and_thumb(tmp_path):
    p = _seed_quarantined(tmp_path, "1")
    (tmp_path / g.DELETED_DIRNAME / "1.json").write_text("{}", encoding="utf-8")
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    (thumb / "1.jpg").write_bytes(_png_bytes())

    removed = g.delete_quarantined_forever(tmp_path, thumb, "1")

    assert removed is True
    assert not p.exists()
    assert not (tmp_path / g.DELETED_DIRNAME / "1.json").exists()
    assert not (thumb / "1.jpg").exists()


def test_delete_quarantined_forever_missing_media_id_is_safe(tmp_path):
    assert g.delete_quarantined_forever(tmp_path, tmp_path / "t", "ghost") is False


def test_empty_trash_wipes_everything_and_counts_media_only(tmp_path):
    for i in range(4):
        _seed_quarantined(tmp_path, str(i))
    (tmp_path / g.DELETED_DIRNAME / "0.json").write_text("{}", encoding="utf-8")
    thumb = tmp_path / "gallery" / "thumbs"; thumb.mkdir(parents=True)
    (thumb / "0.jpg").write_bytes(_png_bytes())

    n = g.empty_trash(tmp_path, thumb)

    assert n == 4                                       # sidecar doesn't count
    assert list((tmp_path / g.DELETED_DIRNAME).glob("*")) == []
    assert not (thumb / "0.jpg").exists()


def test_empty_trash_on_missing_dir_is_a_safe_noop(tmp_path):
    assert g.empty_trash(tmp_path, tmp_path / "t") == 0


# ---------------------------------------------------------------------------
# Routes: /api/trash/list, /api/trash/restore
# ---------------------------------------------------------------------------

def test_api_trash_list_returns_items_for_a_signed_in_session(tmp_path):
    _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    d = cli.get("/api/trash/list").get_json()
    assert d["total"] == 1
    assert d["items"][0]["media_id"] == "1"
    assert d["items"][0]["thumb"] == "/thumbs/1.jpg"
    # the on-demand thumbnail for THIS page was actually generated, reusing
    # make_thumbnail() -- not just a URL string with nothing behind it
    thumb_resp = cli.get(d["items"][0]["thumb"])
    assert thumb_resp.status_code == 200


def test_api_trash_list_paginates(tmp_path):
    base = time.time()
    for i in range(3):
        _seed_quarantined(tmp_path, str(i), mtime=base - (3 - i))
    cli = login_client(tmp_path)
    d = cli.get("/api/trash/list?page=1&limit=2").get_json()
    assert d["total"] == 3 and len(d["items"]) == 2 and d["page"] == 1 and d["limit"] == 2


def test_api_trash_list_requires_login(tmp_path):
    """Covered structurally by tests/test_route_tiers.py too; pinned here as a
    concrete example alongside this file's other route tests."""
    _seed_quarantined(tmp_path, "1")
    cli = create_app(tmp_path).test_client()
    r = cli.get("/api/trash/list", environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401


def test_api_trash_restore_route_restores_and_updates_catalog(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)

    r = cli.post("/api/trash/restore", json={"media_ids": ["1"]})

    d = r.get_json()
    assert d["restored"] == ["1"] and d["errors"] == []
    assert (tmp_path / "images" / "1.png").exists()
    assert {row["media_id"] for row in load_catalog(db)} == {"1"}


def test_api_trash_restore_reports_per_item_errors(tmp_path):
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/restore", json={"media_ids": ["ghost"]})
    d = r.get_json()
    assert d["restored"] == []
    assert d["errors"] == [{"media_id": "ghost", "error": "not found in trash"}]


def test_api_trash_restore_works_over_lan_when_logged_in(tmp_path):
    """Restore is LOGIN-tier, not LOCALHOST -- any signed-in session may recover
    something, matching the decided design (docs/AUDIT_2026-07-21.md)."""
    save_catalog(tmp_path / "catalog.db", [])
    _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/restore", json={"media_ids": ["1"]},
                environ_overrides={"REMOTE_ADDR": LAN})
    assert r.get_json()["restored"] == ["1"]


def test_api_trash_restore_requires_login(tmp_path):
    _seed_quarantined(tmp_path, "1")
    cli = create_app(tmp_path).test_client()
    r = cli.post("/api/trash/restore", json={"media_ids": ["1"]},
                environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 401
    assert (tmp_path / g.DELETED_DIRNAME / "1.png").exists()   # nothing moved


# ---------------------------------------------------------------------------
# Routes: /api/trash/delete-forever, /api/trash/empty -- LOCALHOST + confirm=true
# ---------------------------------------------------------------------------

def test_api_trash_delete_forever_refuses_an_authenticated_lan_session(tmp_path):
    """The security-relevant case: being logged in over the LAN is NOT enough --
    same shape as tests/test_purge.py's delete_tasks_bulk LAN test."""
    p = _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/delete-forever", json={"media_ids": ["1"], "confirm": True},
                environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403
    assert p.exists()                                    # nothing destroyed


def test_api_trash_delete_forever_requires_confirm_true(tmp_path):
    p = _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/delete-forever", json={"media_ids": ["1"]})   # no confirm
    assert r.status_code == 400
    assert p.exists()


def test_api_trash_delete_forever_works_from_localhost_with_confirm(tmp_path):
    p = _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/delete-forever", json={"media_ids": ["1"], "confirm": True})
    assert r.get_json() == {"deleted": 1}
    assert not p.exists()


def test_api_trash_empty_refuses_an_authenticated_lan_session(tmp_path):
    p = _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/empty", json={"confirm": True},
                environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403
    assert p.exists()


def test_api_trash_empty_requires_confirm_true(tmp_path):
    p = _seed_quarantined(tmp_path, "1")
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/empty", json={})
    assert r.status_code == 400
    assert p.exists()


def test_api_trash_empty_works_from_localhost_with_confirm(tmp_path):
    for i in range(3):
        _seed_quarantined(tmp_path, str(i))
    cli = login_client(tmp_path)
    r = cli.post("/api/trash/empty", json={"confirm": True})
    assert r.get_json() == {"deleted": 3}
    assert list((tmp_path / g.DELETED_DIRNAME).glob("*")) == []


# ---------------------------------------------------------------------------
# The Panel page itself: floating panel (not an embedded page) + visibility
# gating of the LOCALHOST-only buttons for a LAN session
# ---------------------------------------------------------------------------

def test_panel_page_carries_the_floating_trash_modal_not_an_embedded_page(tmp_path):
    """The trash UI must be a hidden-by-default overlay OUTSIDE the .panel layout
    div (opened via Trash.open()/JS), not a page section rendered inline inside
    the Control Panel's own scrolling content -- the exact distinction the owner
    corrected once already for the Achievements panel ("I meant can the trash page
    be a NEW panel not in the control panel")."""
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)
    assert 'id="trash-modal"' in html
    assert 'class="ach-modal"' in html.split('id="trash-modal"')[1][:40]
    # the modal must close .panel's own div BEFORE #trash-modal opens -- i.e. it is
    # a sibling overlay, not nested inside the Control Panel's own content column
    panel_div_close = html.index('</div>\n<!-- Trash panel')
    trash_modal_open = html.index('id="trash-modal"')
    assert panel_div_close < trash_modal_open
    assert "Trash.open()" in html and "Trash.close()" in html


def test_panel_shows_destructive_trash_buttons_to_localhost(tmp_path):
    cli = login_client(tmp_path)
    html = cli.get("/panel").get_data(as_text=True)      # loopback by default
    assert "Trash.deleteSelected()" in html
    assert "Trash.emptyAll()" in html


def test_panel_hides_destructive_trash_buttons_from_a_lan_session(tmp_path):
    """The visibility-gating principle: a LAN session must not even SEE
    Delete-forever/Empty-trash controls, matching the Users tab's existing
    panel_is_local-gated Remove/Add-user controls -- not just a 403 if clicked."""
    cli = login_client(tmp_path)
    html = cli.get("/panel", environ_overrides={"REMOTE_ADDR": LAN}).get_data(as_text=True)
    assert "Trash.deleteSelected()" not in html
    assert "Trash.emptyAll()" not in html
    assert "Trash.restoreSelected()" in html               # restore stays available
    assert "Trash.open()" in html                           # the panel itself still opens
