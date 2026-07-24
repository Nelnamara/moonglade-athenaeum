"""Tests for filesystem-dependent functions (already_downloaded, catalog, load_token)."""
import csv
import json
import os
from pathlib import Path

import pytest

import pixai_gallery_backup as core


# ---------------------------------------------------------------------------
# already_downloaded
# ---------------------------------------------------------------------------

def test_already_downloaded_finds_flat(tmp_path):
    (tmp_path / "cool_prompt_task1_mid999.png").write_bytes(b"fakeimage")
    result = core.already_downloaded(tmp_path, "mid999")
    assert result is not None
    assert result.name.endswith("mid999.png")


def test_already_downloaded_finds_in_subfolder(tmp_path):
    sub = tmp_path / "batches" / "my_batch"
    sub.mkdir(parents=True)
    (sub / "01_mid888.webp").write_bytes(b"fakeimage")
    result = core.already_downloaded(tmp_path, "mid888")
    assert result is not None


def test_already_downloaded_returns_none_when_missing(tmp_path):
    assert core.already_downloaded(tmp_path, "nonexistent") is None


def test_already_downloaded_ignores_part_files(tmp_path):
    (tmp_path / "task_mid777.png.part").write_bytes(b"partial")
    assert core.already_downloaded(tmp_path, "mid777") is None


def test_already_downloaded_ignores_zero_byte(tmp_path):
    (tmp_path / "task_mid666.png").write_bytes(b"")
    assert core.already_downloaded(tmp_path, "mid666") is None


def test_already_downloaded_multiple_exts_returns_first(tmp_path):
    (tmp_path / "task_mid555.jpg").write_bytes(b"img")
    result = core.already_downloaded(tmp_path, "mid555")
    assert result is not None


# ---------------------------------------------------------------------------
# load_token
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_creds(tmp_path, monkeypatch):
    """Neutralize any real config.json / env so load_token's fallback chain is
    tested in isolation. Without this, a real PIXAI_API_KEY in the developer's
    config.json (loaded into core._cfg at import) short-circuits every fallback
    and these tests fail on machines that have a live config."""
    monkeypatch.setattr(core, "_cfg", {})
    monkeypatch.setattr(core, "__file__", str(tmp_path / "pixai_gallery_backup.py"))
    monkeypatch.chdir(tmp_path)            # no config.json / token.txt in CWD
    monkeypatch.delenv("PIXAI_API_KEY", raising=False)
    monkeypatch.delenv("PIXAI_TOKEN", raising=False)
    return tmp_path


def test_load_token_from_cli(isolated_creds):
    assert core.load_token("mytoken") == "mytoken"


def test_load_token_from_env(isolated_creds, monkeypatch):
    monkeypatch.setenv("PIXAI_TOKEN", "envtoken")
    assert core.load_token() == "envtoken"


def test_load_token_from_file(isolated_creds):
    (isolated_creds / "token.txt").write_text("filetoken\n", encoding="utf-8")
    assert core.load_token() == "filetoken"


def test_load_token_strips_whitespace(isolated_creds, monkeypatch):
    monkeypatch.setenv("PIXAI_TOKEN", "  tok  ")
    assert core.load_token() == "tok"


def test_load_token_raises_when_none(isolated_creds):
    with pytest.raises(core.PixAIError, match="No credential"):
        core.load_token()


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

def test_load_config_reads_file(tmp_path):
    cfg = {"USER_ID": "u1", "U3T": "t1", "PERSISTED_QUERY_HASH": "h1"}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypath_module_file = str(tmp_path / "pixai_gallery_backup.py")
    # Temporarily redirect module __file__ and reload config
    orig = core.__file__
    try:
        core.__file__ = monkeypath_module_file
        result = core._load_config()
    finally:
        core.__file__ = orig
    assert result["USER_ID"] == "u1"
    assert result["U3T"] == "t1"


def test_load_config_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "__file__", str(tmp_path / "pixai_gallery_backup.py"))
    monkeypatch.chdir(tmp_path)  # prevent CWD fallback from finding a real config.json
    result = core._load_config()
    assert result == {}


# ---------------------------------------------------------------------------
# run_import_local + run_generate (preview)
# ---------------------------------------------------------------------------

from types import SimpleNamespace
from pixai_gallery import load_catalog as _load_cat


def test_import_local_scans_and_is_idempotent(tmp_path):
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "myclip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "art.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    res = core.run_import_local(SimpleNamespace(out=str(tmp_path), import_local=""))
    assert res["imported"] == 2 and res["skipped"] == 0
    assert len(res["media_ids"]) == 2                      # the web importer tags a collection off these
    rows = {r["filename"]: r for r in _load_cat(tmp_path / "catalog.db")}
    assert rows["videos/myclip.mp4"]["source"] == "local"
    assert rows["videos/myclip.mp4"]["is_video"] == "1"
    assert rows["images/art.png"]["source"] == "local"
    assert rows["images/art.png"]["is_video"] == ""
    # re-run imports nothing new
    assert core.run_import_local(SimpleNamespace(out=str(tmp_path), import_local=""))["imported"] == 0


def test_import_local_skips_already_backed_up_pixai_files(tmp_path):
    """Regression: an organized PixAI file is named <mediaid>.ext and its catalog
    'filename' string may differ from the on-disk path, but media_id_of() matches
    the existing row -- so import must NOT re-catalog it as a duplicate 'local'."""
    from pixai_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} |
                      {"media_id": "375806477215601884", "filename": "images/old_name.png"}])
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "2023-10" / "375806477215601884.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    res = core.run_import_local(SimpleNamespace(out=str(tmp_path), import_local=""))
    assert res["imported"] == 0          # recognized as already backed up
    assert res["skipped"] == 1
    # catalog still has exactly one row, no 'local' duplicate
    rows = _load_cat(db)
    assert len(rows) == 1 and rows[0]["source"] != "local"


def test_import_local_skips_deleted_quarantine(tmp_path):
    """B11 (audit 2026-07-21): purge_media_local() moves a purged image to _deleted/
    AND clears its catalog row -- so an internal (no explicit path) --import-local
    scan that doesn't skip _deleted/ finds the orphaned file, sees no existing row/
    media_id for it, and resurrects it as a brand-new source='local' row. A purged
    image must stay purged, not come back to life on the next --import-local."""
    from pixai_gallery import DELETED_DIRNAME
    qdir = tmp_path / DELETED_DIRNAME
    qdir.mkdir(parents=True)
    (qdir / "old_prompt_task1_999.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    res = core.run_import_local(SimpleNamespace(out=str(tmp_path), import_local=""))
    assert res["imported"] == 0, "a file under _deleted/ was resurrected as a new local row"
    assert _load_cat(tmp_path / "catalog.db") == []


def test_import_local_external_copies_in(tmp_path):
    ext = tmp_path / "external"; ext.mkdir()
    (ext / "outside.png").write_bytes(b"\x89PNG\r\n\x1a\ny")
    out = tmp_path / "backup"
    res = core.run_import_local(SimpleNamespace(out=str(out), import_local=str(ext)))
    assert res["imported"] == 1
    assert (out / "imported" / "outside.png").exists()   # copied into the backup


def test_video_poster_thumb_noop_without_ffmpeg(tmp_path, monkeypatch):
    # ffmpeg absent -> returns False gracefully, no thumbnail written
    monkeypatch.setattr(core, "_ffmpeg_path", lambda: "")
    vid = tmp_path / "clip.mp4"; vid.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    thumb = tmp_path / "out.jpg"
    assert core.video_poster_thumb(vid, thumb) is False
    assert not thumb.exists()


def test_import_local_video_no_crash_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_ffmpeg_path", lambda: "")
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "v.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    res = core.run_import_local(SimpleNamespace(out=str(tmp_path), import_local=""))
    assert res["imported"] == 1   # cataloged fine; just no poster


def _mp4(*types):
    """Build a minimal mp4 from top-level boxes (each an 8-byte header + tiny payload)."""
    import struct
    out = b""
    for t in types:
        pay = b"\x00" * 8
        out += struct.pack(">I", 8 + len(pay)) + t + pay
    return out


def test_mp4_faststart_detection(tmp_path):
    """moov BEFORE mdat = faststart (iOS-streamable); moov after = not."""
    fs = tmp_path / "fs.mp4"; fs.write_bytes(_mp4(b"ftyp", b"moov", b"mdat"))
    nf = tmp_path / "nf.mp4"; nf.write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
    assert core._mp4_is_faststart(fs) is True
    assert core._mp4_is_faststart(nf) is False


def test_video_faststart_noop_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_ffmpeg_path", lambda: "")
    nf = tmp_path / "nf.mp4"; nf.write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
    before = nf.read_bytes()
    assert core.video_faststart(nf) is False       # no ffmpeg -> graceful no-op
    assert nf.read_bytes() == before               # original untouched


def test_video_faststart_skips_already_faststart(tmp_path, monkeypatch):
    # ffmpeg 'present' but the file is already faststart -> short-circuits, no remux attempt
    monkeypatch.setattr(core, "_ffmpeg_path", lambda: "ffmpeg")
    fs = tmp_path / "fs.mp4"; fs.write_bytes(_mp4(b"ftyp", b"moov", b"mdat"))
    assert core.video_faststart(fs) is False
    assert core.video_faststart(tmp_path / "x.webm") is False   # non-mp4 ignored


def test_run_faststart_videos_no_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_ffmpeg_path", lambda: "")
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "a.mp4").write_bytes(_mp4(b"ftyp", b"mdat", b"moov"))
    res = core.run_faststart_videos(SimpleNamespace(out=str(tmp_path)))
    assert res["fixed"] == 0 and res["total"] == 1


def test_import_local_skips_branding_folder(tmp_path, monkeypatch):
    """The branding folder (banner/logo/marks) is app chrome, NOT gallery content —
    a backup scan must never sweep it into the catalog, or the gallery fills with UI art."""
    from pixai_gallery import load_catalog
    monkeypatch.setattr(core, "_ffmpeg_path", lambda: "")
    (tmp_path / "branding" / "marks").mkdir(parents=True)
    (tmp_path / "branding" / "banner.png").write_bytes(b"\x89PNG\r\n\x1a\ny")
    (tmp_path / "branding" / "marks" / "m1.png").write_bytes(b"\x89PNG\r\n\x1a\ny")
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "v.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    res = core.run_import_local(SimpleNamespace(out=str(tmp_path), import_local=""))
    assert res["imported"] == 1                       # only the video, not the 2 branding pngs
    files = [r.get("filename", "") for r in load_catalog(tmp_path / "catalog.db")]
    assert not any("branding" in f for f in files)     # branding stayed out of the gallery
    assert any(f.endswith("v.mp4") for f in files)


def test_organize_normalizes_to_month_descriptive_no_batches(tmp_path):
    from pixai_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "task_id": "T1",
            "prompt_preview": "alpha", "created_at": "2024-03-01T00:00:00", "filename": "alpha_T1_m1.png"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m2", "task_id": "T2",
            "prompt_preview": "beta", "created_at": "2024-05-01T00:00:00", "filename": "m2.png"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "m3", "task_id": "T3",
            "prompt_preview": "gamma", "created_at": "2024-06-01T00:00:00", "filename": "01_m3.png"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "loc", "source": "local", "filename": "imported/keep.png"},
    ])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "alpha_T1_m1.png").write_bytes(b"a")           # flat
    (tmp_path / "2024-05").mkdir(); (tmp_path / "2024-05" / "m2.png").write_bytes(b"b")  # old bare month
    (tmp_path / "batches" / "g").mkdir(parents=True)
    (tmp_path / "batches" / "g" / "01_m3.png").write_bytes(b"c")          # legacy batch
    (tmp_path / "imported").mkdir(); (tmp_path / "imported" / "keep.png").write_bytes(b"L")  # user import

    args = SimpleNamespace(out=str(tmp_path), name_length=60, name_sep="_", convert=None,
                           dry_run=False, embed_metadata=False, jpeg_quality=92,
                           jpeg_bg="white", keep_webp=False, progress=None)
    core.cmd_organize(args, tmp_path, tmp_path / "images", db)

    assert (tmp_path / "2024-03" / "alpha_T1_m1.png").exists()            # flat -> month
    assert (tmp_path / "2024-05" / "beta_T2_m2.png").exists()             # bare -> descriptive
    assert (tmp_path / "2024-06" / "gamma_T3_m3.png").exists()            # batch -> month
    assert not (tmp_path / "batches").exists()                           # batches flattened away
    assert (tmp_path / "imported" / "keep.png").exists()                 # import left alone
    assert (tmp_path / "organize_manifest.csv").exists()                 # reversible
    by = {r["media_id"]: r for r in load_catalog(db)}
    assert by["m2"]["filename"] == "beta_T2_m2.png" and by["m2"]["batch"] == ""

    # idempotent: a second run moves nothing
    args2 = SimpleNamespace(**{**vars(args)})
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        core.cmd_organize(args2, tmp_path, tmp_path / "images", db)
    assert "already organized" in buf.getvalue()


def test_organize_never_touches_deleted_quarantine(tmp_path):
    """B11 (audit 2026-07-21), highest-severity of the five: cmd_organize's skip_dirs
    named gallery/, _duplicates/, videos/, imported/ -- never _deleted/. It's the
    only one of the five B11 walks that actually MOVES files, so a file quarantined
    there (e.g. a stale remnant from an earlier purge-then-redownload cycle, still
    sharing its media_id with the live, currently-cataloged copy) gets treated as a
    normal organize candidate: same media_id -> same catalog row -> same target path
    as the REAL file, so it collides with it in the move plan. Depending on rglob
    ordering that collision either hard-deletes the _deleted/ copy outright (the
    _same_bytes 'redundant' branch, no confirmation, no _duplicates/ safety net) or
    replaces it into the organized tree in place of the live file. Either way the
    _deleted/ file must never be touched at all -- this asserts exactly that,
    regardless of which of the two on-disk copies the walk happens to visit first."""
    from pixai_gallery import save_catalog, CATALOG_FIELDS, DELETED_DIRNAME
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m9", "task_id": "T9",
        "prompt_preview": "alpha", "created_at": "2024-03-01T00:00:00", "filename": "alpha_T9_m9.png"}])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "alpha_T9_m9.png").write_bytes(b"SAMEBYTES")   # the live, cataloged copy
    qdir = tmp_path / DELETED_DIRNAME
    qdir.mkdir()
    (qdir / "old_m9.png").write_bytes(b"SAMEBYTES")                      # stale quarantine remnant

    args = SimpleNamespace(out=str(tmp_path), name_length=60, name_sep="_", convert=None,
                           dry_run=False, embed_metadata=False, jpeg_quality=92,
                           jpeg_bg="white", keep_webp=False, progress=None)
    core.cmd_organize(args, tmp_path, tmp_path / "images", db)

    assert (qdir / "old_m9.png").exists(), (
        "a file under _deleted/ was moved or deleted by cmd_organize -- quarantine is not immune")
    assert (qdir / "old_m9.png").read_bytes() == b"SAMEBYTES"
    assert (tmp_path / "2024-03" / "alpha_T9_m9.png").exists()           # the real file organized fine


def test_undo_organize_reverts_moves(tmp_path):
    from pixai_gallery import save_catalog, CATALOG_FIELDS
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1", "task_id": "T1",
        "prompt_preview": "alpha", "created_at": "2024-03-01T00:00:00", "filename": "alpha_T1_m1.png"}])
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "alpha_T1_m1.png").write_bytes(b"a")
    args = SimpleNamespace(out=str(tmp_path), name_length=60, name_sep="_", convert=None,
                           dry_run=False, embed_metadata=False, jpeg_quality=92,
                           jpeg_bg="white", keep_webp=False, progress=None)
    core.cmd_organize(args, tmp_path, tmp_path / "images", db)
    assert (tmp_path / "2024-03" / "alpha_T1_m1.png").exists()
    core.cmd_undo_organize(SimpleNamespace(out=str(tmp_path), dry_run=False), tmp_path)
    assert (tmp_path / "images" / "alpha_T1_m1.png").exists()             # back to original
    assert not (tmp_path / "2024-03" / "alpha_T1_m1.png").exists()
    assert not (tmp_path / "organize_manifest.csv").exists()              # manifest cleared


def _organize_args(out):
    return SimpleNamespace(out=str(out), name_length=60, name_sep="_", convert=None,
                           dry_run=False, embed_metadata=False, jpeg_quality=92,
                           jpeg_bg="white", keep_webp=False, progress=None)


def test_organize_drops_byte_identical_duplicate(tmp_path):
    """INVARIANT 5's byte-safe half: two on-disk copies of the SAME media_id (a stray
    re-download, an old batches/ copy alongside a flat one, etc.) collapse onto the
    same YYYY-MM destination. When they are byte-identical, cmd_organize must unlink
    the redundant one and keep exactly one file -- this is the one line in the whole
    command that unlink()s a real file on a path that runs live by default (no
    --dry-run gate), so it must never fire on the wrong side of a comparison."""
    from pixai_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "dup1", "task_id": "T9",
        "prompt_preview": "dup", "created_at": "2024-07-01T00:00:00"}])
    (tmp_path / "images").mkdir()
    loc_a = tmp_path / "images" / "dup1.png"
    loc_b = tmp_path / "images" / "extra_dup1.png"
    loc_a.write_bytes(b"identical-bytes")
    loc_b.write_bytes(b"identical-bytes")

    core.cmd_organize(_organize_args(tmp_path), tmp_path, tmp_path / "images", db)

    dst = tmp_path / "2024-07" / "dup_T9_dup1.png"
    assert dst.exists() and dst.read_bytes() == b"identical-bytes"
    assert not loc_a.exists()          # both original locations consumed: one moved...
    assert not loc_b.exists()          # ...the other recognized as a redundant dupe and unlinked
    by = {r["media_id"]: r for r in load_catalog(db)}
    assert by["dup1"]["filename"] == "dup_T9_dup1.png"


def test_organize_keeps_differing_content_side_by_side(tmp_path):
    """INVARIANT 5's other half: two on-disk copies of the SAME media_id that are NOT
    byte-identical (a genuine conflict, not a redundant dupe) must both survive --
    cmd_organize must never silently pick one and discard the other's real content."""
    from pixai_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    save_catalog(db, [{f: "" for f in CATALOG_FIELDS} | {"media_id": "dup2", "task_id": "T8",
        "prompt_preview": "dup", "created_at": "2024-07-01T00:00:00"}])
    (tmp_path / "images").mkdir()
    loc_a = tmp_path / "images" / "dup2.png"
    loc_b = tmp_path / "images" / "extra_dup2.png"
    loc_a.write_bytes(b"content-A")
    loc_b.write_bytes(b"totally-different-content-B")

    core.cmd_organize(_organize_args(tmp_path), tmp_path, tmp_path / "images", db)

    dst = tmp_path / "2024-07" / "dup_T8_dup2.png"
    assert dst.exists()
    survivors = [p for p in (loc_a, loc_b) if p.exists()]
    assert len(survivors) == 1, "exactly one of the two original locations should remain untouched"
    surviving_bytes = {dst.read_bytes(), survivors[0].read_bytes()}
    assert surviving_bytes == {b"content-A", b"totally-different-content-B"}   # neither lost


def test_reconcile_flags_deleted_server_side(tmp_path, monkeypatch):
    from pixai_gallery import save_catalog, CATALOG_FIELDS, load_catalog
    db = tmp_path / "catalog.db"
    old = "2024-01-01T00:00:00"
    save_catalog(db, [
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "a", "task_id": "LIVE1", "filename": "a.png", "created_at": old},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "b", "task_id": "GONE", "filename": "b.png", "created_at": old},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "c", "task_id": "NEW", "filename": "c.png", "created_at": "2099-01-01T00:00:00"},
        {f: "" for f in CATALOG_FIELDS} | {"media_id": "L", "task_id": "GONE2", "filename": "L.png", "source": "local", "created_at": old},
    ])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    conn = {"edges": [{"node": {"id": "LIVE1"}}], "pageInfo": {"hasPreviousPage": False}}
    monkeypatch.setattr(core, "gql", lambda *a, **k: conn)
    res = core.run_reconcile_deleted(SimpleNamespace(out=str(tmp_path), token=None, page_size=250))
    assert res["live"] == 1 and res["flagged"] == 1
    by = {r["media_id"]: r for r in load_catalog(db)}
    assert by["b"]["deleted_remote"] == "1"      # task gone from feed, old -> flagged
    assert by["a"]["deleted_remote"] == ""       # still live -> not flagged
    assert by["c"]["deleted_remote"] == ""       # too recent -> not flagged (propagation grace)
    assert by["L"]["deleted_remote"] == ""       # local import -> never flagged


def test_generate_preview_spends_nothing(tmp_path):
    a = SimpleNamespace(prompt="elf", negative="", model="", width=512, height=512,
                        steps=25, cfg=7.0, count=1, seed=None, params_json="",
                        confirm=False, out=str(tmp_path))
    assert core.run_generate(a) == {"submitted": False}


# ---------------------------------------------------------------------------
# SQLite catalog helpers
# ---------------------------------------------------------------------------

from pixai_gallery import (CATALOG_FIELDS, init_db, save_catalog, load_catalog,
                            update_rating, delete_from_catalog,
                            update_prompt_full, bulk_replace_prompt,
                            migrate_csv_to_db, export_csv, _db_is_empty)


def _make_row(**kwargs):
    """Return a full catalog row dict with blank defaults for unset fields."""
    return {f: "" for f in CATALOG_FIELDS} | kwargs


def test_db_is_empty_missing_file(tmp_path):
    assert _db_is_empty(tmp_path / "nonexistent.db") is True


def test_db_is_empty_fresh_init(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    assert _db_is_empty(db) is True


def test_db_is_empty_after_rows_saved(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_make_row(media_id="m1")])
    assert _db_is_empty(db) is False


def test_init_db_creates_table(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    assert db.exists()
    import sqlite3
    con = sqlite3.connect(str(db))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()
    assert "catalog" in tables


def test_migrations_backfill_every_field_added_after_the_original_schema(tmp_path):
    """Schema changes are a three-place contract (docs/architecture.md): CATALOG_FIELDS,
    _CREATE_TABLE, and _MIGRATIONS must all agree. A fresh checkout's CREATE TABLE
    already has every CATALOG_FIELDS column -- that half is exercised by every test in
    this suite that pushes `{f: "" for f in CATALOG_FIELDS}` through save_catalog
    (INSERT fails immediately if _CREATE_TABLE is missing one). Nothing exercises the
    OTHER half: _MIGRATIONS is what actually reaches an EXISTING install's catalog.db
    (run on every _connect()), so forgetting an ALTER TABLE entry for a newly added
    field breaks upgraders silently while a fresh checkout's suite stays green.

    This simulates exactly that existing install: a catalog.db holding ONLY the columns
    present since the SQLite schema's very first commit (cc2aeb1, 2026-06-13, "replace
    catalog.csv with SQLite (catalog.db)") -- the one moment a column could enter
    _CREATE_TABLE with zero pre-existing databases around to migrate. Every
    CATALOG_FIELDS entry added since then must arrive via _MIGRATIONS, or this
    "existing" database never gains it, forever. (Checked against git log: every field
    added after that commit -- batch, artwork_id/title/..., loras, negative_prompt/
    clip_skip, is_video/poster_media_id/video_duration, source, deleted_remote,
    collections, blurhash/nsfw_scores -- landed in CATALOG_FIELDS and _MIGRATIONS in the
    SAME commit each time; no historical instance of the drift this test guards against
    was found. The test is not vacuous regardless -- see the report for the mutation
    check that proves it fails when a migration entry is missing.)"""
    import sqlite3
    from pixai_gallery import CATALOG_FIELDS, _connect

    original_fields = [   # cc2aeb1's _CREATE_TABLE, verbatim -- none of these have ever
        "task_id", "media_id", "filename", "url", "width", "height",   # needed a migration
        "prompt_preview", "status", "created_at", "prompt_full", "natural_prompt",
        "seed", "steps", "sampler", "cfg_scale", "model_id", "model_name", "rating",
    ]
    db = tmp_path / "ancient_catalog.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE catalog ({})".format(
        ", ".join(("media_id TEXT PRIMARY KEY" if f == "media_id" else "{} TEXT".format(f))
                  for f in original_fields)))
    con.commit()
    con.close()

    _connect(db).close()   # the real upgrade path load_catalog/save_catalog always take

    con = sqlite3.connect(str(db))
    cols = {r[1] for r in con.execute("PRAGMA table_info(catalog)").fetchall()}
    con.close()
    missing = [f for f in CATALOG_FIELDS if f not in cols]
    assert not missing, (
        "field(s) {} are in CATALOG_FIELDS with no _MIGRATIONS entry that adds them -- "
        "an existing install's catalog.db (predating that field) would never gain this "
        "column".format(missing))


def test_migration_adds_paid_credit_to_existing_db_without_data_loss(tmp_path):
    """paid_credit (added 2026-07-23) followed the three-place contract; this locks the
    upgrade path for a real pre-paid_credit install: a catalog.db built from every
    column EXCEPT paid_credit, holding a populated row, must gain the column via
    _MIGRATIONS on a plain _connect() with the existing row's data intact -- and the
    migrated db must round-trip a real credit value."""
    import sqlite3
    from pixai_gallery import _connect

    assert "paid_credit" in CATALOG_FIELDS   # the contract half: the field exists at all
    pre_fields = [f for f in CATALOG_FIELDS if f != "paid_credit"]
    db = tmp_path / "pre_paid_credit.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE catalog ({})".format(
        ", ".join(("media_id TEXT PRIMARY KEY" if f == "media_id" else "{} TEXT".format(f))
                  for f in pre_fields)))
    con.execute("INSERT INTO catalog (media_id, task_id, filename, rating) VALUES (?,?,?,?)",
                ("m1", "t1", "keep.png", "5"))
    con.commit()
    con.close()

    rows = load_catalog(db)          # load_catalog -> _connect() runs _MIGRATIONS
    assert rows[0]["media_id"] == "m1" and rows[0]["filename"] == "keep.png"
    assert rows[0]["rating"] == "5"                 # no data loss
    assert rows[0]["paid_credit"] in ("", None)     # migrated in, blank default

    row = dict(rows[0])
    row["paid_credit"] = "2750"
    save_catalog(db, [row])
    got = load_catalog(db)[0]
    assert got["paid_credit"] == "2750" and got["filename"] == "keep.png"
    _connect(db).close()             # re-connect after the fact stays harmless (idempotent)


def test_catalog_stats_totals_paid_credit_once_per_task(tmp_path, capsys):
    """--catalog-stats spend total: paid_credit is a TASK-level cost repeated on each of
    the task's media rows, so a 2-image batch must count once, not twice. '0' rows are
    real free gens (a task in the tally, adding nothing); '' rows are untracked and must
    not be counted as free."""
    save_catalog(tmp_path / "catalog.db", [
        _make_row(media_id="a1", task_id="t1", filename="a1.png", paid_credit="100"),
        _make_row(media_id="a2", task_id="t1", filename="a2.png", paid_credit="100"),
        _make_row(media_id="b1", task_id="t2", filename="b1.png", paid_credit="0"),
        _make_row(media_id="c1", task_id="t3", filename="c1.png"),   # untracked ('')
    ])
    core.run_catalog_stats(SimpleNamespace(out=str(tmp_path), progress=None))
    out = capsys.readouterr().out
    assert "Credits tracked" in out
    assert "100 spent across 2 tasks (1 free)" in out


def test_save_and_load_roundtrip(tmp_path):
    db = tmp_path / "catalog.db"
    rows = [
        _make_row(media_id="m1", task_id="t1", filename="a.png", prompt_preview="cat"),
        _make_row(media_id="m2", task_id="t2", filename="b.png", prompt_preview="dog"),
    ]
    save_catalog(db, rows)
    loaded = load_catalog(db)
    assert len(loaded) == 2
    by_id = {r["media_id"]: r for r in loaded}
    assert by_id["m1"]["prompt_preview"] == "cat"
    assert by_id["m2"]["filename"] == "b.png"


def test_save_catalog_upserts_not_duplicates(tmp_path):
    """Re-saving the same media_id updates the row, never inserts a duplicate."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_make_row(media_id="m1", filename="old.png")])
    save_catalog(db, [_make_row(media_id="m1", filename="new.png")])
    loaded = load_catalog(db)
    assert len(loaded) == 1
    assert loaded[0]["filename"] == "new.png"


def test_save_catalog_preserves_prior_session_rows(tmp_path):
    """Rows from a previous session that aren't in the current batch are kept."""
    db = tmp_path / "catalog.db"
    save_catalog(db, [_make_row(media_id="m_old", filename="old.png")])
    save_catalog(db, [_make_row(media_id="m_new", filename="new.png")])
    loaded = load_catalog(db)
    ids = {r["media_id"] for r in loaded}
    assert "m_old" in ids
    assert "m_new" in ids


def test_update_rating_changes_one_row(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _make_row(media_id="m1", rating=""),
        _make_row(media_id="m2", rating="2"),
    ])
    update_rating(db, "m1", 5)
    by_id = {r["media_id"]: r for r in load_catalog(db)}
    assert by_id["m1"]["rating"] == "5"
    assert by_id["m2"]["rating"] == "2"  # untouched


def test_update_rating_clear_to_zero(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_make_row(media_id="m1", rating="4")])
    update_rating(db, "m1", 0)
    loaded = load_catalog(db)
    assert loaded[0]["rating"] == ""


def test_delete_from_catalog_removes_row(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _make_row(media_id="m1"),
        _make_row(media_id="m2"),
    ])
    delete_from_catalog(db, "m1")
    loaded = load_catalog(db)
    assert len(loaded) == 1
    assert loaded[0]["media_id"] == "m2"


def test_delete_nonexistent_is_safe(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_make_row(media_id="m1")])
    delete_from_catalog(db, "does_not_exist")
    assert len(load_catalog(db)) == 1


def test_update_prompt_full_edits_one_row(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _make_row(media_id="m1", prompt_full="old prompt"),
        _make_row(media_id="m2", prompt_full="keep me"),
    ])
    update_prompt_full(db, "m1", "brand new prompt")
    by_id = {r["media_id"]: r for r in load_catalog(db)}
    assert by_id["m1"]["prompt_full"] == "brand new prompt"
    assert by_id["m2"]["prompt_full"] == "keep me"  # untouched


def test_bulk_replace_prompt_counts_only_changed(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _make_row(media_id="m1", prompt_full="red cat"),
        _make_row(media_id="m2", prompt_full="red dog"),
        _make_row(media_id="m3", prompt_full="blue bird"),  # no match -> unchanged
    ])
    n = bulk_replace_prompt(db, ["m1", "m2", "m3"], "red", "green")
    assert n == 2
    by_id = {r["media_id"]: r for r in load_catalog(db)}
    assert by_id["m1"]["prompt_full"] == "green cat"
    assert by_id["m2"]["prompt_full"] == "green dog"
    assert by_id["m3"]["prompt_full"] == "blue bird"


def test_bulk_replace_prompt_empty_find_is_noop(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_make_row(media_id="m1", prompt_full="x")])
    assert bulk_replace_prompt(db, ["m1"], "", "y") == 0


def test_migrate_csv_to_db(tmp_path):
    csv_path = tmp_path / "catalog.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        w.writeheader()
        w.writerow(_make_row(media_id="m1", filename="img.png", rating="3"))
    db = tmp_path / "catalog.db"
    n = migrate_csv_to_db(csv_path, db)
    assert n == 1
    loaded = load_catalog(db)
    assert loaded[0]["media_id"] == "m1"
    assert loaded[0]["rating"] == "3"


def test_migrate_csv_to_db_is_idempotent(tmp_path):
    """Running migration twice must not duplicate rows."""
    csv_path = tmp_path / "catalog.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CATALOG_FIELDS)
        w.writeheader()
        w.writerow(_make_row(media_id="m1", filename="img.png"))
    db = tmp_path / "catalog.db"
    migrate_csv_to_db(csv_path, db)
    migrate_csv_to_db(csv_path, db)
    assert len(load_catalog(db)) == 1


def test_migrate_csv_missing_file_returns_zero(tmp_path):
    db = tmp_path / "catalog.db"
    n = migrate_csv_to_db(tmp_path / "nonexistent.csv", db)
    assert n == 0


def test_export_csv_roundtrip(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _make_row(media_id="m1", filename="a.png", rating="5"),
        _make_row(media_id="m2", filename="b.png", rating=""),
    ])
    csv_out = tmp_path / "export.csv"
    export_csv(db, csv_out)
    assert csv_out.exists()
    with open(csv_out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    by_id = {r["media_id"]: r for r in rows}
    assert by_id["m1"]["rating"] == "5"
    assert set(rows[0].keys()) == set(CATALOG_FIELDS)


def test_count_backup_images_excludes_thumbnails(tmp_path):
    """The disk counter must count ORIGINALS only -- not the one-per-image gallery/thumbs
    previews (which made files-on-disk look ~2x the catalog) and not quarantined _duplicates."""
    import pixai_gallery_backup as core
    (tmp_path / "images").mkdir()
    (tmp_path / "2026-07").mkdir()
    (tmp_path / "gallery" / "thumbs").mkdir(parents=True)
    (tmp_path / "_duplicates").mkdir()
    (tmp_path / "images" / "a_1.png").write_bytes(b"x" * 100)      # original
    (tmp_path / "2026-07" / "b_2.webp").write_bytes(b"y" * 200)   # original (month folder)
    (tmp_path / "gallery" / "thumbs" / "1.jpg").write_bytes(b"t")   # thumbnail -> excluded
    (tmp_path / "gallery" / "thumbs" / "2.jpg").write_bytes(b"t")   # thumbnail -> excluded
    (tmp_path / "_duplicates" / "c_3.png").write_bytes(b"z")         # quarantined -> excluded
    (tmp_path / "images" / "half.part").write_bytes(b"nope")         # partial -> excluded
    n, b, thumbs = core._count_backup_images(tmp_path)
    assert n == 2 and b == 300          # two originals, their bytes; grid/thumbs/dupes excluded
    assert thumbs == 2                  # thumbnails reported separately, not in the total
