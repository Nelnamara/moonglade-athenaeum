"""About names what 3.20 left in the old places (3.20.0, "the move", item 4).

3.18's line ("An old moonglade.dat is still beside the pack. It's safe to delete.") becomes a
short list of every old copy the app no longer reads and that is safe to delete once the
owner has checked the new version: the copied machine files, the old serve logs, the old
serve.txt, the library's copied records and reports, and the library-side branding.json
nothing has read since 2026-07. Read from the disk on each ask, so a name leaves the list the
moment its file is deleted. One line, in About's existing stamp style -- no new element.
"""
import json
import os

import pytest

from moonglade import assets as ma
from moonglade import gallery as g
from moonglade import migrate as mig
from moonglade import paths
from tests.conftest import login_client

_REAL_LOCAL_PATH = paths.local_path
_REAL_LOCAL_DIR = paths.local_dir
_REAL_OLD_LOCAL_PATH = paths.old_local_path
SEP = os.sep


def _w(p, data="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data, encoding="utf-8")
    return p


@pytest.fixture
def app(tmp_path, monkeypatch):
    root = tmp_path / "app"
    root.mkdir()
    monkeypatch.setattr(paths, "APP_ROOT", root)
    monkeypatch.setattr(paths, "local_path", _REAL_LOCAL_PATH)
    monkeypatch.setattr(paths, "local_dir", _REAL_LOCAL_DIR)
    monkeypatch.setattr(paths, "old_local_path", _REAL_OLD_LOCAL_PATH)
    monkeypatch.setattr(paths, "config_path", lambda: root / "config.json")
    _w(root / "config.json", "{}")
    _w(root / "moonglade.mgpack", "PACK")
    _w(root / "branding.json", '{"mark": "mark_4"}')
    _w(root / "serve.txt", "--port 5757")
    _w(root / "serve.log", "old console\n")
    _w(root / "serve.log.1", "older console\n")
    _w(root / "mirror_session.json", '{"jwt": "not-a-real-token"}')
    return root


@pytest.fixture
def lib(tmp_path):
    out = tmp_path / "pixai_backup"
    _w(out / "catalog.db", "")
    _w(out / "2023-10" / "a_1.png")
    _w(out / "achievements.json", "{}")
    _w(out / "train_guard.json", "{}")
    _w(out / "logs" / "moonglade.log", "old\n")
    _w(out / "organize_manifest.csv", "old_path,new_path,ts\n")
    _w(out / "branding.json", "{}")                     # library-side, unread since 2026-07
    return out


def _names(items, where):
    return [n for w, n in items if w == where]


def test_nothing_is_left_over_before_the_move(app, lib):
    """An install not yet brought across reads everything where it is: nothing is a leftover
    -- except the library-side branding.json, which nothing reads at all."""
    items = mig.leftovers(lib)
    assert _names(items, "app") == []
    assert _names(items, "library") == ["branding.json (unused)"]


def _launcher_started(app):
    """What the new launcher does after its tidy: open its fresh local/serve.log."""
    _w(app / "local" / "serve.log", "")


def test_after_the_move_the_old_copies_are_listed(app, lib):
    _launcher_started(app)
    mig.migrate_local()
    mig.migrate_library(lib)
    items = mig.leftovers(lib)
    assert _names(items, "app") == ["branding.json", "serve.txt", "serve.log", "serve.log.1"]
    assert _names(items, "library") == [
        "achievements.json", "logs" + SEP, "organize_manifest.csv", "branding.json (unused)"]
    # moved things are not left anywhere; config.json and the library itself never are
    flat = [n for _, n in items]
    for never in ("moonglade.mgpack", "mirror_session.json", "train_guard.json", "config.json",
                  "catalog.db", "2023-10" + SEP):
        assert never not in flat, never


def test_the_list_is_read_live_and_empties_as_files_are_deleted(app, lib):
    mig.migrate_local()
    mig.migrate_library(lib)
    (app / "serve.log.1").unlink()
    (lib / "branding.json").unlink()
    items = mig.leftovers(lib)
    assert "serve.log.1" not in _names(items, "app")
    assert "branding.json (unused)" not in _names(items, "library")
    for name in ("branding.json", "serve.txt", "serve.log"):
        (app / name).unlink()
    for name in ("achievements.json", "organize_manifest.csv"):
        (lib / name).unlink()
    import shutil
    shutil.rmtree(lib / "logs")
    assert mig.leftovers(lib) == []
    assert mig.leftovers_note([]) == ""


def test_the_note_is_one_plain_line(app, lib):
    _launcher_started(app)
    mig.migrate_local()
    mig.migrate_library(lib)
    note = mig.leftovers_note(mig.leftovers(lib))
    assert note == (
        "Safe to delete once you've checked this version works: branding.json, serve.txt, "
        "serve.log and serve.log.1 in the app folder; achievements.json, logs" + SEP + ", "
        "organize_manifest.csv and branding.json (unused) in the library folder.")
    assert "\n" not in note


def test_about_shows_it_as_the_packs_note(app, lib):
    mig.migrate_local()
    mig.migrate_library(lib)
    info = g.art_pack_info(g._container_path(), out_dir=lib)
    assert info["installed"] is True
    assert info["note"] == mig.leftovers_note(mig.leftovers(lib))
    assert g.about_payload("3.20.0", g._container_path(), out_dir=lib)["pack"]["note"] == \
        info["note"]


def test_the_pre_v7_name_left_in_the_app_folder_is_listed(app, lib):
    """3.18's rename finding both names leaves the old one where it was: still listed."""
    _w(app / ma.LEGACY_NAME, "an older pack")
    mig.migrate_local()
    assert ma.LEGACY_NAME in _names(mig.leftovers(), "app")


def test_the_about_route_names_the_librarys_leftovers(lib):
    """Through the real route, for the library the server serves (conftest's own app folder
    for this test has nothing in it)."""
    mig.migrate_library(lib)
    cli = login_client(lib)
    note = cli.get("/api/help/about").get_json()["pack"].get("note", "")
    assert "achievements.json" in note and "in the library folder" in note
    (lib / "achievements.json").unlink()
    note = cli.get("/api/help/about").get_json()["pack"].get("note", "")
    assert "achievements.json" not in note


def test_the_branding_choice_in_use_is_never_called_unused(tmp_path, monkeypatch):
    """Where a library and the machine files share a folder (an app folder used as its own
    library), the branding.json there is the one in use, not the old library-side copy."""
    monkeypatch.setattr(paths, "local_path", lambda name: tmp_path / name)
    _w(tmp_path / "branding.json", '{"mark": "mark_4"}')
    assert mig.leftovers(tmp_path) == []


def test_the_old_icon_cache_is_never_called_a_leftover(app):
    """A Desktop shortcut made before 3.20 takes its icon from _container_cache/marks/, so the
    old cache is copied, not moved, and kept -- and About never calls it safe to delete."""
    _w(app / "_container_cache" / "marks" / "mark_4.ico", "ico")
    mig.migrate_local()
    assert (app / "local" / "cache" / "marks" / "mark_4.ico").is_file()
    assert (app / "_container_cache" / "marks" / "mark_4.ico").is_file()
    names = _names(mig.leftovers(), "app")
    assert not [n for n in names if "cache" in n], names


# ---- review round: an old copy that changed after it was brought across ------------------

def test_the_manifest_records_each_sources_fingerprint(app, lib):
    mig.migrate_library(lib)
    doc = json.loads((lib / "_moonglade" / "MOVED.json").read_text(encoding="utf-8"))
    by = {e["name"]: e for e in doc["entries"]}
    st = (lib / "achievements.json").stat()
    assert by["achievements.json"]["source_print"] == {"size": st.st_size,
                                                        "mtime_ns": st.st_mtime_ns}
    folder = by["logs"]["source_print"]
    assert folder["files"] == 1
    assert folder["size"] == (lib / "logs" / "moonglade.log").stat().st_size
    assert folder["newest_mtime_ns"] == (lib / "logs" / "moonglade.log").stat().st_mtime_ns


def test_an_old_copy_changed_since_the_move_is_not_called_safe_to_delete(app, lib, caplog):
    """Edits made on 3.19 after a rollback, or by an older install still using the same
    library: the old copy is now newer than the one 3.20 uses. About must not offer it for
    deletion; the log says so, once."""
    import logging
    mig.migrate_library(lib)
    old = lib / "achievements.json"
    old.write_text('{"earned": {"something": 1}}', encoding="utf-8")
    os.utime(old, ns=(old.stat().st_atime_ns, old.stat().st_mtime_ns + 5_000_000_000))
    (lib / "logs" / "moonglade.3.19.log").write_text("a line from 3.19\n", encoding="utf-8")
    with caplog.at_level(logging.DEBUG, logger="moonglade"):
        first = [n for _, n in mig.leftovers(lib)]
        second = [n for _, n in mig.leftovers(lib)]
    for names in (first, second):
        assert "achievements.json" not in names and "logs" + SEP not in names
        assert "organize_manifest.csv" in names                 # unchanged: still listed
    said = [r.getMessage() for r in caplog.records if r.name == mig.LOGGER_NAME]
    assert len([m for m in said if "achievements.json" in m]) == 1
    assert len([m for m in said if "logs" in m]) == 1
    note = mig.leftovers_note(mig.leftovers(lib))
    assert "achievements" not in note and "changed" not in note
