"""A running Sync must not undo what the owner does in the gallery while it runs.

`run_download` reads the whole catalog when it starts (`known`) and used to merge every page
it saved over that read, through an upsert that rewrites every column. A rating, a
collection, a prompt correction or PixAI's per-image `cloud_deleted_at` set while the Sync
was walking was put back to its start-of-run value by the next page save, and a row deleted
in the gallery came back (red team, 2026-11-19). The same held for Sync's later steps, which
load whole rows, spend minutes on the network, and save those rows back.

Each test makes its edit from inside a network stub, i.e. after the writer took its read and
before it saved, which is exactly the window an owner clicking in the gallery lands in.
"""
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import models as models_mod
from moonglade.gallery import (CATALOG_FIELDS, catalog, delete_from_catalog, load_catalog,
                               merge_over_current, save_catalog, save_catalog_over_snapshot,
                               update_prompt_full, update_rating)
from moonglade import task_reads as task_reads_mod


def _row(**kw):
    r = {f: "" for f in CATALOG_FIELDS}
    r.update(kw)
    return r


def _set(db, mid, **cols):
    with catalog(db) as con:
        for k, v in cols.items():
            con.execute("UPDATE catalog SET {}=? WHERE media_id=?".format(k), (v, mid))
        con.commit()


def _by_id(db):
    return {r["media_id"]: r for r in load_catalog(db)}


def _seed(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="m1", task_id="t1", prompt_full="old prompt", created_at="2024-01-01"),
        _row(media_id="m2", task_id="t1", created_at="2024-01-01"),
        _row(media_id="m3", task_id="t1", created_at="2024-01-01"),
    ])
    return db


def _edit_in_gallery(db):
    """What the owner does in the gallery while the Sync walks."""
    update_rating(db, "m1", 5)
    _set(db, "m1", collections="Keepers")
    update_prompt_full(db, "m1", "corrected prompt")
    delete_from_catalog(db, "m2")
    _set(db, "m3", cloud_deleted_at="2026-11-19T00:00:00Z")


def _page(mids):
    node = {"id": "t1", "mediaId": mids[0], "batchMediaIds": list(mids),
            "createdAt": "2024-01-01T00:00:00", "promptsPreview": "p", "status": "ok"}
    return {"user": {"taskSummaries": {
        "edges": [{"node": node}],
        "pageInfo": {"hasPreviousPage": False, "startCursor": ""}}}}


def _dl_args(out, workers):
    return SimpleNamespace(
        out=str(out), token="t", page_size=20, max=0, delay=0, workers=workers,
        name_length=40, name_sep="_", convert=None, jpeg_quality=92, jpeg_bg="white",
        keep_webp=False, collect_only=False, full_meta=False, update=False, update_grace=2)


@pytest.mark.parametrize("workers", [1, 4], ids=["serial", "parallel"])
def test_a_page_save_keeps_edits_made_during_the_sync(tmp_path, monkeypatch, workers):
    db = _seed(tmp_path)
    edited = []

    def fake_gql(session, variables, *a, **k):
        _edit_in_gallery(db)                 # after run_download's start-of-run read
        edited.append(1)
        return _page(["m1", "m2", "m3", "m4"])

    def fake_download(session, url, stem, **kw):
        dest = stem.with_suffix(".webp")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return "ok", dest

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(core, "_quick_count", lambda *a, **k: 0)
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {})
    monkeypatch.setattr(core._pixai_client, "_client_of",
                        lambda s: SimpleNamespace(user_id="u1"))
    monkeypatch.setattr(core, "gql", fake_gql)
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, mid: ("http://x/" + mid, {"width": "8", "height": "8"}))
    monkeypatch.setattr(core, "download", fake_download)

    core.run_download(_dl_args(tmp_path, workers))

    assert edited, "the edit never ran -- this test would pass vacuously"
    rows = _by_id(db)
    m1 = rows["m1"]
    assert m1["rating"] == "5", "the page save undid a rating set during the Sync"
    assert m1["collections"] == "Keepers", "the page save undid a collection set during the Sync"
    assert m1["prompt_full"] == "corrected prompt", "the page save undid a prompt correction"
    assert "m2" not in rows, "a row deleted during the Sync came back"
    assert rows["m3"]["cloud_deleted_at"] == "2026-11-19T00:00:00Z", \
        "the page save cleared PixAI's per-image delete stamp"
    # ...and the Sync still did its own job: what it fetched landed, new media included.
    assert m1["url"] == "http://x/m1" and m1["width"] == "8" and m1["filename"]
    assert rows["m4"]["url"] == "http://x/m4", "a new media id must still be cataloged"


def test_the_backfill_step_keeps_edits_made_while_it_ran(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", task_id="t1", filename="a.png"),
                      _row(media_id="m2", task_id="t2", filename="b.png")])

    def detail(session, tid, **kw):
        if tid == "t1":
            update_rating(db, "m1", 4)
            _set(db, "m1", collections="Mid-run")
            delete_from_catalog(db, "m2")
        return {"parameters": {"modelId": "V1", "prompts": "a cat"}, "outputs": {}}

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(task_reads_mod, "task_detail_gql", detail)
    monkeypatch.setattr(models_mod, "model_name_gql", lambda *a, **k: "Model")
    monkeypatch.setattr(core, "resolve_loras", lambda s, t: "")
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, t: fm)
    monkeypatch.setattr(core, "_BACKFILL_CHECKPOINT_TASKS", 1)

    core.run_backfill_full_meta(SimpleNamespace(
        out=str(tmp_path), token=None, workers=1, delay=0.0, progress=None,
        with_loras=False, with_credit=False, with_surface=False))

    rows = _by_id(db)
    assert rows["m1"]["prompt_full"] == "a cat", "the backfill must still fill the row"
    assert rows["m1"]["rating"] == "4" and rows["m1"]["collections"] == "Mid-run", \
        "the backfill's checkpoint undid an edit made while it ran"
    assert "m2" not in rows, "the backfill brought back a row deleted while it ran"


def test_the_fix_models_step_keeps_edits_made_while_it_ran(tmp_path, monkeypatch):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="m1", task_id="t1", model_id="123", model_name="")])

    def name_lookup(session, vid, strict=False):
        update_rating(db, "m1", 3)
        return "Tsubaki"

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(models_mod, "model_name_gql", name_lookup)

    core.run_fix_models(SimpleNamespace(out=str(tmp_path), token=None, workers=1, delay=0,
                                        progress=None, relabel_removed=False))

    m1 = _by_id(db)["m1"]
    assert m1["model_name"] == "Tsubaki"
    assert m1["rating"] == "3", "--fix-models undid a rating set while it looked names up"


def test_the_merge_rules():
    snap = {"media_id": "m", "rating": "", "url": "", "deleted_remote": "1"}
    cur = {"media_id": "m", "rating": "5", "url": "", "deleted_remote": "1"}
    # An echo of the snapshot loses to the catalog; news wins; a blank keeps.
    out = merge_over_current({"media_id": "m", "rating": "", "url": "u"}, snap, cur)
    assert out["rating"] == "5" and out["url"] == "u"
    # A writer that cleared a value on purpose (blank_keeps=False) is written as cleared.
    out = merge_over_current({"media_id": "m", "deleted_remote": ""}, snap, cur,
                             blank_keeps=False)
    assert out["deleted_remote"] == ""


def test_a_row_new_since_the_snapshot_is_written_and_a_deleted_one_is_not(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="gone"), _row(media_id="kept", rating="2")])
    snapshot = _by_id(db)
    delete_from_catalog(db, "gone")
    written = save_catalog_over_snapshot(db, [
        _row(media_id="gone", url="u"), _row(media_id="kept", url="u"),
        _row(media_id="new", url="u")], snapshot)
    assert {r["media_id"] for r in written} == {"kept", "new"}
    rows = _by_id(db)
    assert set(rows) == {"kept", "new"} and rows["kept"]["rating"] == "2"
