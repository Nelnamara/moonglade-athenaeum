"""Health's Broken files list (Session W, Phase B of library items 2+3): what the list shows.

The integrity check (moonglade_integrity.verify_library, Phase A) writes one report line per
broken row. The list reads those lines back and, for each one, adds what a row needs to draw
and to act: its state pill (RECOVERABLE, SUSPECT or LOST), the one action that applies
(re-download or rebuild), whether PixAI still has it, and the local mark the owner gave it.

  - the chips are Zero-byte, Thumbnail and Suspect (plus Lost, which cuts across them);
  - a broken file PixAI no longer has is LOST, decided from the catalog's flags NOW, so a
    reconcile that finds it again turns the row back into RECOVERABLE;
  - Mark lost and Keep as is are a local flag in integrity_marks.json at the library root,
    beside the reports. Nothing is deleted, and the marks touch nothing else.

The fixing half (the targeted runner) is tests/test_integrity_fix.py.
"""
import json
from types import SimpleNamespace

from moonglade import backup as core
from moonglade import integrity as integ
from moonglade import paths
from moonglade.gallery import create_app, save_catalog
from tests.conftest import login_test_client, with_csrf
from tests.test_integrity import _REPORTS_WRITTEN, _jpeg, _png, _row, _tree_hash

# What a mark writes, besides the check's own reports: its file, beside them.
_WRITTEN = _REPORTS_WRITTEN + ("_moonglade/decisions", "_moonglade/decisions/integrity_marks.json")


def _broken_library(tmp_path, deleted_remote_on=("109",)):
    """A temp library with one of each broken row the list shows, beside sound rows:
    a zero-byte file, a truncated (suspect) file, a missing thumbnail, an empty thumbnail,
    a video with no poster, and broken files PixAI no longer has (archive-only)."""
    out = tmp_path
    img = out / "images"
    vid = out / "videos"
    thumbs = out / "gallery" / "thumbs"
    for d in (img, vid, thumbs):
        d.mkdir(parents=True, exist_ok=True)
    png = _png()
    (img / "p_t1_101.png").write_bytes(png)            # sound
    (img / "p_t1_102.png").write_bytes(b"")            # zero-byte, PixAI still has it
    (img / "p_t1_103.png").write_bytes(png[:-12])      # suspect: its end is missing
    (img / "p_t1_106.png").write_bytes(png)            # sound, no thumbnail
    (img / "p_t1_107.png").write_bytes(png)            # sound, empty thumbnail
    (img / "p_t1_109.png").write_bytes(b"")            # zero-byte AND archive-only -> LOST
    (img / "p_t1_112.png").write_bytes(png[:-12])      # suspect AND gone (per-image delete)
    (vid / "p_t1_108.mp4").write_bytes(
        b"\x00\x00\x00\x10ftypisom\x00\x00\x02\x00" + b"\x00\x00\x00\x18moov" + b"\x00" * 16)
    for mid in ("101", "102", "103", "109", "112"):
        (thumbs / (mid + ".jpg")).write_bytes(_jpeg())
    (thumbs / "107.jpg").write_bytes(b"")
    save_catalog(out / "catalog.db", [
        _row(media_id="101", filename="p_t1_101.png", created_at="2026-01-01T00:00:00"),
        _row(media_id="102", filename="p_t1_102.png", created_at="2026-01-02T00:00:00"),
        _row(media_id="103", filename="p_t1_103.png", created_at="2026-01-03T00:00:00"),
        _row(media_id="105", filename="p_t1_105.png", created_at="2026-01-05T00:00:00"),  # missing
        _row(media_id="106", filename="p_t1_106.png", created_at="2026-01-06T00:00:00"),
        _row(media_id="107", filename="p_t1_107.png", created_at="2026-01-07T00:00:00"),
        _row(media_id="108", filename="videos/p_t1_108.mp4", is_video="1",
             created_at="2026-01-08T00:00:00"),
        _row(media_id="109", filename="p_t1_109.png", created_at="2026-01-09T00:00:00",
             deleted_remote="1" if "109" in deleted_remote_on else ""),
        _row(media_id="112", filename="p_t1_112.png", created_at="2026-01-12T00:00:00",
             cloud_deleted_at="2026-09-30T10:00:00Z"),
    ])
    (out / "p_t1_999.png").write_bytes(png)           # uncataloged: never on this list
    integ.verify_library(out, out / "catalog.db", deep=True)
    return out


def _by_id(doc):
    return {r["media_id"]: r for r in doc["rows"]}


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------

def test_the_list_holds_the_broken_rows_the_chips_name(tmp_path):
    out = _broken_library(tmp_path)
    doc = integ.broken_list(out, out / "catalog.db")
    rows = _by_id(doc)
    # zero-byte, suspect, the three thumbnail problems, and a missing file (shown under All,
    # with no chip of its own); never an uncataloged file or an orphan thumbnail
    assert set(rows) == {"102", "103", "105", "106", "107", "108", "109", "112"}
    assert {k: rows[k]["kind"] for k in rows} == {
        "102": "zero", "103": "suspect", "105": "missing", "106": "thumb", "107": "thumb",
        "108": "thumb", "109": "zero", "112": "suspect"}
    assert doc["counts"] == {"all": 8, "zero": 2, "thumb": 3, "suspect": 2, "missing": 1,
                             "lost": 2}
    assert doc["broken"] == 6 and doc["lost"] == 2
    assert doc["verified_at"].endswith("Z") and doc["deep"] is True


def test_each_row_gets_its_pill_and_only_the_action_that_applies(tmp_path):
    out = _broken_library(tmp_path)
    rows = _by_id(integ.broken_list(out, out / "catalog.db"))
    assert (rows["102"]["state"], rows["102"]["action"]) == ("recoverable", "redownload")
    assert (rows["103"]["state"], rows["103"]["action"]) == ("suspect", "redownload")
    assert (rows["106"]["state"], rows["106"]["action"]) == ("recoverable", "rebuild")
    assert (rows["107"]["state"], rows["107"]["action"]) == ("recoverable", "rebuild")
    assert (rows["108"]["state"], rows["108"]["action"]) == ("recoverable", "rebuild")
    # a missing file PixAI still has: RECOVERABLE, re-downloaded to the catalog's own path
    assert (rows["105"]["state"], rows["105"]["action"]) == ("recoverable", "redownload")
    assert rows["105"]["path"] == "p_t1_105.png" and rows["105"]["size"] == ""
    # a broken file PixAI no longer has is LOST and never offers a re-download
    for lost in ("109", "112"):
        assert rows[lost]["state"] == "lost" and rows[lost]["action"] is None, lost
        assert rows[lost]["archive_only"] is True
    assert rows["102"]["path"] == "images/p_t1_102.png" and rows["102"]["size"] == 0
    assert rows["106"]["path"] == "gallery/thumbs/106.jpg"
    assert rows["102"]["thumb"] is True and rows["106"]["thumb"] is False
    assert rows["108"]["is_video"] is True
    assert "corrupt" not in json.dumps(rows)


def test_recoverable_first_then_suspect_then_lost_then_newest(tmp_path):
    out = _broken_library(tmp_path)
    order = [r["media_id"] for r in integ.broken_list(out, out / "catalog.db")["rows"]]
    assert order == ["108", "107", "106", "105", "102", "103", "112", "109"]


def test_lost_rows_say_as_of_when(tmp_path):
    out = _broken_library(tmp_path)
    paths.records_path(out, core.RECONCILE_STAMP).write_text(
        json.dumps({"reconciled_at": "2026-10-02T08:00:00Z"}), encoding="utf-8")
    rows = _by_id(integ.broken_list(out, out / "catalog.db"))
    assert rows["109"]["gone_as_of"] == "2026-10-02"   # the last reconcile that flagged it
    assert rows["112"]["gone_as_of"] == "2026-09-30"   # PixAI's own date for one image
    assert rows["102"]["gone_as_of"] is None


def test_lost_without_a_reconcile_stamp_has_no_date(tmp_path):
    out = _broken_library(tmp_path)
    assert _by_id(integ.broken_list(out, out / "catalog.db"))["109"]["gone_as_of"] is None


def test_a_reconcile_that_finds_it_again_makes_it_recoverable(tmp_path):
    out = _broken_library(tmp_path)
    assert _by_id(integ.broken_list(out, out / "catalog.db"))["109"]["state"] == "lost"
    # the next reconcile clears the flag (it rewrites deleted_remote every run)
    from moonglade.gallery import load_catalog
    rows = load_catalog(out / "catalog.db")
    for r in rows:
        if r["media_id"] == "109":
            r["deleted_remote"] = ""
    save_catalog(out / "catalog.db", rows)
    row = _by_id(integ.broken_list(out, out / "catalog.db"))["109"]
    assert (row["state"], row["action"], row["archive_only"]) == ("recoverable", "redownload", False)


def test_fix_all_counts_recoverable_rows_only(tmp_path):
    out = _broken_library(tmp_path)
    fix = integ.broken_list(out, out / "catalog.db")["fix"]
    assert sorted(fix["redownload"]) == ["102", "103", "105"]
    assert sorted(fix["rebuild"]) == ["106", "107", "108"]
    assert fix["lost"] == 2


def test_an_archive_only_thumbnail_row_is_left_out_of_fix_all(tmp_path):
    """The rule is "never LOST or archive-only": a picture PixAI no longer has keeps its
    per-row Rebuild (local work on a sound file), but Fix all does not count it."""
    out = _broken_library(tmp_path)
    from moonglade.gallery import load_catalog
    rows = load_catalog(out / "catalog.db")
    for r in rows:
        if r["media_id"] == "106":
            r["deleted_remote"] = "1"
    save_catalog(out / "catalog.db", rows)
    doc = integ.broken_list(out, out / "catalog.db")
    row = _by_id(doc)["106"]
    assert (row["state"], row["action"], row["archive_only"]) == ("recoverable", "rebuild", True)
    assert "106" not in doc["fix"]["rebuild"]


def test_the_re_download_size_is_an_estimate_from_the_library(tmp_path):
    out = _broken_library(tmp_path)
    fix = integ.broken_list(out, out / "catalog.db", avg_bytes=3_000_000)["fix"]
    # the zero-byte and the missing file count the library's average (the catalog keeps no
    # byte size); the cut-short one at least its own size
    assert fix["redownload_bytes"] == 9_000_000
    assert integ.broken_list(out, out / "catalog.db")["fix"]["redownload_bytes"] is None


def test_a_missing_file_pixai_no_longer_has_is_lost(tmp_path):
    """Missing AND archive-only: LOST (+ ARCHIVE), so it sits under Lost as well as All, and
    Fix all leaves it alone."""
    out = _broken_library(tmp_path)
    from tests.test_integrity import _row as _r
    save_catalog(out / "catalog.db", [_r(media_id="113", filename="p_t1_113.png",
                                         created_at="2026-01-13T00:00:00", deleted_remote="1")])
    integ.verify_library(out, out / "catalog.db", deep=True)
    doc = integ.broken_list(out, out / "catalog.db")
    row = _by_id(doc)["113"]
    assert (row["kind"], row["state"], row["action"], row["archive_only"]) == (
        "missing", "lost", None, True)
    assert doc["counts"]["missing"] == 2 and doc["counts"]["lost"] == 3
    assert "113" not in doc["fix"]["redownload"]


def test_no_report_is_an_empty_list(tmp_path):
    save_catalog(tmp_path / "catalog.db", [])
    doc = integ.broken_list(tmp_path, tmp_path / "catalog.db")
    assert doc["rows"] == [] and doc["verified_at"] is None
    assert doc["counts"]["all"] == 0


def test_a_row_gone_from_the_catalog_since_the_check_leaves_the_list(tmp_path):
    out = _broken_library(tmp_path)
    from moonglade.gallery import delete_from_catalog
    delete_from_catalog(out / "catalog.db", "102")
    assert "102" not in _by_id(integ.broken_list(out, out / "catalog.db"))


# ---------------------------------------------------------------------------
# Mark lost / Keep as is: a local flag, nothing else
# ---------------------------------------------------------------------------

def test_mark_lost_moves_a_row_to_lost_and_out_of_fix_all(tmp_path):
    out = _broken_library(tmp_path)
    before = _tree_hash(out, skip=_WRITTEN)
    assert integ.set_mark(out, "102", "lost") == ""
    doc = integ.broken_list(out, out / "catalog.db")
    row = _by_id(doc)["102"]
    assert (row["state"], row["action"], row["mark"]) == ("lost", None, "lost")
    assert "102" not in doc["fix"]["redownload"]
    assert doc["counts"]["lost"] == 3 and doc["counts"]["zero"] == 2
    # a local flag among the owner's decisions (the library's _moonglade/decisions/) -- and
    # nothing else
    # changed
    assert json.loads(paths.decisions_path(out, integ.MARKS_FILE).read_text(
        encoding="utf-8"))["marks"]["102"]["mark"] == "lost"
    assert _tree_hash(out, skip=_WRITTEN) == before


def test_undo_puts_the_previous_mark_back(tmp_path):
    out = _broken_library(tmp_path)
    prev = integ.set_mark(out, "102", "lost")
    assert integ.set_mark(out, "102", prev) == "lost"
    row = _by_id(integ.broken_list(out, out / "catalog.db"))["102"]
    assert (row["state"], row["mark"]) == ("recoverable", "")


def test_keep_as_is_quiets_a_lost_row_until_pixai_has_it_again(tmp_path):
    out = _broken_library(tmp_path)
    integ.set_mark(out, "109", "kept")
    row = _by_id(integ.broken_list(out, out / "catalog.db"))["109"]
    assert (row["state"], row["mark"]) == ("lost", "kept")
    from moonglade.gallery import load_catalog
    rows = load_catalog(out / "catalog.db")
    for r in rows:
        if r["media_id"] == "109":
            r["deleted_remote"] = ""
    save_catalog(out / "catalog.db", rows)
    row = _by_id(integ.broken_list(out, out / "catalog.db"))["109"]
    assert row["state"] == "recoverable" and row["action"] == "redownload"


def test_a_mark_is_refused_for_an_unknown_word(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        integ.set_mark(tmp_path, "102", "delete")
    with pytest.raises(ValueError):
        integ.set_mark(tmp_path, "", "lost")


# ---------------------------------------------------------------------------
# The reconcile stamp the LOST line's date comes from
# ---------------------------------------------------------------------------

def test_a_reconcile_stamps_when_it_ran(tmp_path, monkeypatch, pixai):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="a", task_id="GONE", filename="a.png", created_at="2024-01-01T00:00:00")])
    conn = {"edges": [{"node": {"id": "LIVE"}}], "pageInfo": {"hasPreviousPage": False}}
    monkeypatch.setattr(core, "gql", lambda *a, **k: conn)
    core.run_reconcile_deleted(SimpleNamespace(out=str(tmp_path), token=None, page_size=250))
    doc = json.loads(paths.records_path(tmp_path, core.RECONCILE_STAMP).read_text(encoding="utf-8"))
    assert doc["reconciled_at"].endswith("Z") and doc["flagged"] == 1
    assert integ.reconciled_at(tmp_path) == doc["reconciled_at"]


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def _client(out):
    return login_test_client(create_app(out))


def test_the_list_route(tmp_path):
    out = _broken_library(tmp_path)
    cli = _client(out)
    d = cli.get("/api/integrity/broken").get_json()
    assert d["counts"]["all"] == 8
    assert d["read_only"] is False


def test_the_mark_route_checks_the_token_and_the_list(tmp_path):
    out = _broken_library(tmp_path)
    cli = _client(out)
    r = cli.post("/api/integrity/mark", json={"media_id": "102", "mark": "lost"})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]
    r = cli.post("/api/integrity/mark", json=with_csrf(cli, {"media_id": "101", "mark": "lost"}))
    assert r.status_code == 400                       # a sound row is not on the list
    r = cli.post("/api/integrity/mark", json=with_csrf(cli, {"media_id": "102", "mark": "gone"}))
    assert r.status_code == 400
    d = cli.post("/api/integrity/mark",
                 json=with_csrf(cli, {"media_id": "102", "mark": "lost"})).get_json()
    assert d == {"ok": True, "media_id": "102", "mark": "lost", "prev": ""}
    d = cli.post("/api/integrity/mark",
                 json=with_csrf(cli, {"media_id": "102", "mark": ""})).get_json()
    assert d["prev"] == "lost"
    assert integ.read_marks(out) == {}
