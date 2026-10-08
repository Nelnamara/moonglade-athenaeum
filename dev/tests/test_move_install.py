"""The install half of the move (moonglade.migrate.migrate_install): an older install's machine
files come into local\\ -- the art pack and its marker, the Mirror's sign-in, the launcher's
serve.log*, the shortcut icons -- and the old places are emptied (DECISIONS 2026-10-05: the
app cleans up after itself).

The layouts it accepts (S14): 3.17 (the pack still under its pre-v7 name), 3.19, and C:'s
copy-first 3.20 state, whose MOVED.json fingerprints tell a copy 3.20 made (deleted) from an
old file written since (parked, never deleted on a guess). The shortcut icons go to
local\\icons\\ before the old icon cache is deleted. Before the first move the small settings
files are zipped into local\\.snapshot\\ -- never the pack, never the Mirror's token.
"""
import json
import zipfile
from pathlib import Path

import pytest

from moonglade import migrate
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import (layout_317, layout_c_copy_first, read_config, rig, start,
                                write, write_config)


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _zip_names(folder):
    zips = list((folder / ".snapshot").glob("*.zip"))
    assert len(zips) == 1, zips
    with zipfile.ZipFile(zips[0]) as zf:
        return set(zf.namelist())


def test_the_3_17_install_moves_into_local(r):
    layout_317(r)
    start(r)
    # the pre-v7 pack rename, then the move; the marker follows its own pack
    assert (r.local / "moonglade.mgpack").read_bytes() == b"PACK-317" * 64
    assert json.loads((r.local / "moonglade.mgpack.version").read_text())["version"] == "6"
    for gone in ("moonglade.dat", "moonglade.dat.version", "moonglade.mgpack",
                 "moonglade.mgpack.version", "mirror_session.json", "serve.log", "serve.txt",
                 "branding.json", "_container_cache"):
        assert not (r.app / gone).exists(), gone
    assert json.loads((r.local / "mirror_session.json").read_text()) == {"jwt": "token-317"}
    assert (r.local / "logs" / "serve.log").read_text() == "the launcher's log\n"
    assert (r.local / "icons" / "mark_2.ico").read_bytes() == b"ICO-2"
    assert settings.branding()["mark"] == "mark_2"
    assert settings.server()["port"] == 5757
    journal = json.loads((r.local / ".journal.json").read_text())
    assert journal["finished"] and journal["settings_merged"]
    assert journal["items"]["local/moonglade.mgpack"]["state"] == "made"
    assert not (r.local / ".lock").exists()


def test_the_snapshot_holds_the_small_settings_files_and_never_the_pack_or_token(r):
    layout_317(r)
    write_config(r, PORT=5000, READ_ONLY=True)
    start(r)
    names = _zip_names(r.local)
    assert {"serve.txt", "branding.json"} <= names
    assert "config.json (the keys moved to settings.json).json" in names
    assert not any("mgpack" in n or "moonglade.dat" in n or "mirror_session" in n
                   for n in names)


def test_the_moved_config_keys_are_kept_in_the_snapshot(r):
    write_config(r, PORT=5151, LIBRARY_DIR=str(r.lib))
    msetup.prepare("cli")
    zips = list((r.local / ".snapshot").glob("*.zip"))
    with zipfile.ZipFile(zips[0]) as zf:
        kept = json.loads(zf.read("config.json (the keys moved to settings.json).json"))
    assert kept == {"LIBRARY_DIR": str(r.lib), "PORT": 5151}
    assert "PIXAI_API_KEY" not in json.dumps(kept), "never a credential in the snapshot"


def test_a_fresh_install_has_nothing_to_move(r):
    done = msetup.prepare("cli")
    assert done.report.worked["install"] is False
    journal = json.loads((r.local / ".journal.json").read_text())
    assert journal["finished"] and not journal.get("snapshot")
    assert not (r.local / ".snapshot").exists()
    assert not (r.local / "settings.json").exists()


def test_c_s_copy_first_install_keeps_the_live_copies_and_removes_the_recorded_old_ones(r):
    """The local\\ copies are the ones 3.20 was using; the root copies are exactly what 3.20
    copied (MOVED.json's fingerprints match), so they are its leftovers and go."""
    layout_c_copy_first(r)
    done = start(r)
    b = settings.branding()
    assert b["mark"] == "mark_4" and b["animation"]["anim"] == "aurora", "the live copy"
    assert b["slots"] == {"banner_main": "live"}
    for gone in ("serve.txt", "branding.json", "branding_slots.json", "serve.log",
                 "_container_cache"):
        assert not (r.app / gone).exists(), gone
    for gone in ("serve.txt", "branding.json", "branding_slots.json", "serve.log",
                 migrate.OLD_RECORD, "cache/marks"):
        assert not (r.local / gone).exists(), gone
    assert (r.local / "icons" / "mark_4.ico").read_bytes() == b"ICO-4"
    assert (r.local / "moonglade.mgpack").read_bytes() == b"PACK-320" * 64
    # 3.20 started serve.log fresh in local\ and never copied the root one, so the two are
    # different files of one name: a log is merged, the older one's lines first -- nothing
    # either holds goes to the snapshot (to be deleted with it).
    assert (r.local / "logs" / "serve.log").read_text() == \
        "the old launcher's log\nthe 3.20 launcher's log\n"
    assert not (r.local / ".snapshot" / "parked").exists()
    assert done.report.parked == 0


def test_an_old_copy_written_since_3_20_copied_it_is_parked_not_deleted(r):
    layout_c_copy_first(r)
    write(r.app / "branding.json", {"mark": "written-since", "anim": "glow"})
    start(r)
    assert settings.branding()["mark"] == "mark_4", "the copy 3.20 was using still wins"
    parked = list((r.local / ".snapshot" / "parked").rglob("branding.json*"))
    assert len(parked) == 1
    assert json.loads(parked[0].read_text())["mark"] == "written-since"


def test_two_packs_keep_the_one_in_local(r):
    write(r.app / "moonglade.mgpack", b"OLD")
    write(r.app / "moonglade.mgpack.version", "{}")
    write(r.local / "moonglade.mgpack", b"NEW")
    msetup.prepare("cli")
    assert (r.local / "moonglade.mgpack").read_bytes() == b"NEW"
    assert not (r.app / "moonglade.mgpack").exists()
    assert not (r.app / "moonglade.mgpack.version").exists()


def test_a_marker_never_lands_beside_a_pack_it_does_not_describe(r):
    """A marker with no pack beside it describes nothing: it is removed, never moved."""
    write(r.app / "moonglade.mgpack.version", {"version": "9"})
    write(r.local / "moonglade.mgpack", b"NEW")
    msetup.prepare("cli")
    assert not (r.local / "moonglade.mgpack.version").exists()
    assert not (r.app / "moonglade.mgpack.version").exists()


def test_two_mirror_sign_ins_keep_the_newer_and_never_park_a_token(r):
    import os
    write(r.app / "mirror_session.json", {"jwt": "old"})
    write(r.local / "mirror_session.json", {"jwt": "new"})
    os.utime(r.app / "mirror_session.json", (1, 1))
    msetup.prepare("cli")
    assert json.loads((r.local / "mirror_session.json").read_text()) == {"jwt": "new"}
    assert not (r.app / "mirror_session.json").exists()
    assert not (r.local / ".snapshot").exists() or not list(
        (r.local / ".snapshot").rglob("mirror_session*"))


def test_the_launcher_logs_keep_their_rotation_names(r):
    for n, text in (("serve.log", "0"), ("serve.log.1", "1"), ("serve.log.3", "3")):
        write(r.app / n, text)
    msetup.prepare("cli")
    assert [p.name for p in sorted((r.local / "logs").iterdir())] == \
        ["serve.log", "serve.log.1", "serve.log.3"]


def test_the_config_keys_leave_through_the_atomic_writer(r, monkeypatch):
    from moonglade import backup as core
    seen = {}
    real = core._save_config

    def spy(cfg):
        seen["locked"] = core._accounts_lock.locked()
        seen["keys"] = sorted(cfg)
        return real(cfg)
    monkeypatch.setattr(core, "_save_config", spy)
    write_config(r, HOST="0.0.0.0")
    msetup.prepare("cli")
    assert seen["locked"] is True
    assert "HOST" not in seen["keys"] and "PIXAI_API_KEY" in seen["keys"]
    assert "HOST" not in read_config(r)


# ---- the settings merge, step by step (X2) ------------------------------------------------------

class _Cut(BaseException):
    """A start that dies mid-merge (a power cut, a Task Manager kill)."""


def _c_disagreement(r):
    """C:'s exact case: serve.txt pins pixai_backup and 5057, config.json's LIBRARY_DIR names
    another install's library."""
    write_config(r, LIBRARY_DIR=r"D:\Moonglade Athenaeum\pixai_backup", PORT=5000)
    write(r.app / "serve.txt", "--out pixai_backup --port 5057\n")
    (r.app / "pixai_backup").mkdir()


@pytest.mark.parametrize("cut_at", ["before-keys", "before-sources"])
def test_a_merge_cut_short_keeps_what_settings_json_holds(r, monkeypatch, cut_at):
    """X2: the first start merged (pixai_backup, 5057) and was cut short before config.json's
    keys were dropped, or before serve.txt was deleted. The next start must never read the
    LIBRARY_DIR left behind as a new choice: settings.json's library and port win."""
    _c_disagreement(r)
    with monkeypatch.context() as m:
        if cut_at == "before-keys":
            def drop(report):
                raise _Cut()
            m.setattr(migrate, "_drop_config_keys", drop)
        else:
            real = migrate._remove

            def remove(p):
                if p.name == "serve.txt":
                    raise _Cut()
                return real(p)
            m.setattr(migrate, "_remove", remove)
        with pytest.raises(_Cut):
            msetup.prepare("cli")
    if cut_at == "before-keys":
        assert "LIBRARY_DIR" in read_config(r), "the keys were still there when it stopped"
        (r.app / "serve.txt").unlink()           # only the config key is left to read
    else:
        assert "LIBRARY_DIR" not in read_config(r), "the keys go before serve.txt does"
        assert (r.app / "serve.txt").is_file()
    journal = json.loads((r.local / ".journal.json").read_text())
    assert journal["merge"]["values"]["library_dir"] == "pixai_backup"
    (r.local / ".lock").unlink(missing_ok=True)
    done = msetup.prepare("cli")
    assert settings.library_dir() == "pixai_backup" and settings.server()["port"] == 5057
    assert done.library == r.app / "pixai_backup", "never the other install's library"
    cfg = read_config(r)
    assert "LIBRARY_DIR" not in cfg and "PORT" not in cfg
    assert not (r.app / "serve.txt").exists()
    assert json.loads((r.local / ".journal.json").read_text())["merge"]["state"] == "done"


def test_a_merge_cut_short_puts_back_a_value_settings_json_lost(r, monkeypatch):
    _c_disagreement(r)
    with monkeypatch.context() as m:
        def drop(report):
            raise _Cut()
        m.setattr(migrate, "_drop_config_keys", drop)
        with pytest.raises(_Cut):
            msetup.prepare("cli")
    (r.local / "settings.json").unlink()
    msetup.prepare("cli")
    assert settings.library_dir() == "pixai_backup" and settings.server()["port"] == 5057


def test_the_config_keys_go_before_serve_txt(r, monkeypatch):
    _c_disagreement(r)
    order = []
    real_drop, real_remove = migrate._drop_config_keys, migrate._remove

    def drop(report):
        order.append("keys")
        return real_drop(report)

    def remove(p):
        order.append(p.name)
        return real_remove(p)
    monkeypatch.setattr(migrate, "_drop_config_keys", drop)
    monkeypatch.setattr(migrate, "_remove", remove)
    msetup.prepare("cli")
    assert order.index("keys") < order.index("serve.txt")


def test_one_moved_key_is_said_in_the_singular(r):
    write_config(r, HOST="0.0.0.0")
    done = msetup.prepare("cli")
    assert "Removed HOST from config.json: it lives in settings.json now." in [
        line for _lvl, line in done.report.lines]


# ---- the pack's marker (N1), and the app's own dead files at the root (S9) ------------------------

def test_a_marker_left_behind_by_a_cut_short_move_follows_its_pack(r, monkeypatch):
    """The pack came across and the start was cut short before its marker did: the marker
    still describes that pack, so it follows rather than being deleted (no re-download)."""
    write(r.app / "moonglade.mgpack", b"PACK" * 64)
    write(r.app / "moonglade.mgpack.version", {"version": "7"})
    real = migrate._bring

    def bring(src, dest, kind, half, vouched=False):
        if Path(src).name == "moonglade.mgpack.version":
            raise _Cut()
        return real(src, dest, kind, half, vouched)
    with monkeypatch.context() as m:
        m.setattr(migrate, "_bring", bring)
        with pytest.raises(_Cut):
            msetup.prepare("cli")
    assert (r.local / "moonglade.mgpack").is_file() and not (r.app / "moonglade.mgpack").exists()
    (r.local / ".lock").unlink(missing_ok=True)
    msetup.prepare("cli")
    assert json.loads((r.local / "moonglade.mgpack.version").read_text()) == {"version": "7"}
    assert not (r.app / "moonglade.mgpack.version").exists()


def test_the_apps_own_dead_files_at_the_root_go(r):
    """S9: the desktop GUI's settings file and an empty stray catalog.db are the app's own dead
    files: the move removes them (the GUI file goes into the safety copy first)."""
    write(r.app / "pixai_gui_settings.json", {"geometry": "x"})
    write(r.app / "catalog.db", b"")
    msetup.prepare("cli")
    assert not (r.app / "pixai_gui_settings.json").exists()
    assert not (r.app / "catalog.db").exists()
    assert "pixai_gui_settings.json" in _zip_names(r.local)


def test_a_catalog_db_with_anything_in_it_at_the_root_is_never_touched(r):
    write(r.app / "catalog.db", b"SQLite format 3\x00 something")
    msetup.prepare("cli")
    assert (r.app / "catalog.db").read_bytes().startswith(b"SQLite format 3")


# ---- one rename on one volume; the copy across volumes (rehearsal 6) -----------------------------

def test_the_art_pack_is_renamed_on_one_volume_not_copied(r, monkeypatch):
    write(r.app / "moonglade.mgpack", b"PACK" * 64)
    copied = []
    real = migrate._copy_into

    def copy_into(src, tmp, kind):
        copied.append(Path(src).name)
        return real(src, tmp, kind)
    monkeypatch.setattr(migrate, "_copy_into", copy_into)
    msetup.prepare("cli")
    assert (r.local / "moonglade.mgpack").read_bytes() == b"PACK" * 64
    assert "moonglade.mgpack" not in copied
    item = json.loads((r.local / ".journal.json").read_text())["items"]["local/moonglade.mgpack"]
    assert (item["state"], item["how"], item["src"]) == ("made", "renamed", "moonglade.mgpack")


def test_across_volumes_the_pack_is_copied_and_keeps_its_time(r, monkeypatch):
    import os
    write(r.app / "moonglade.mgpack", b"PACK" * 64)
    os.utime(r.app / "moonglade.mgpack", (1_600_000_000, 1_600_000_000))
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
    msetup.prepare("cli")
    assert (r.local / "moonglade.mgpack").stat().st_mtime == 1_600_000_000
    item = json.loads((r.local / ".journal.json").read_text())["items"]["local/moonglade.mgpack"]
    assert item["state"] == "made" and item["sha256"]


def test_the_move_writes_one_line_per_file_to_moonglade_log(r):
    """Rehearsal 5: the docs say local\\logs\\moonglade.log lists what was brought across. The
    launcher never sets logging up, so its start appends the lines itself (write_log)."""
    layout_317(r)
    done = start(r)
    done.write_log()
    log = (r.local / "logs" / "moonglade.log").read_text(encoding="utf-8")
    assert "Moved moonglade.mgpack to local/moonglade.mgpack" in log
    assert "Moved jobs.jsonl to _moonglade/records/jobs.jsonl" in log
    assert "Removed serve.txt: what it held is in local/settings.json now." in log
    assert "Moved jobs.jsonl" not in done.summary(), "serve.log gets the overview only"


# ---- the dead Python leftovers at the root (#6, #7, #15) -----------------------------------------

_DEAD_PY = ("__pycache__", ".pytest_cache", "tests", "tools", "docs", "screenshots")


def test_the_dead_python_leftovers_at_the_root_go(r):
    """git keeps an ignored file when an update deletes the tracked ones beside it: 3.19's root
    bytecode, pytest's cache, and tests\\ and tools\\ holding only __pycache__\\ outlive the
    update. The move removes them (rebuildable or dead: nothing goes in the safety copy)."""
    layout_317(r)
    done = start(r)
    for n in _DEAD_PY:
        assert not (r.app / n).exists(), n
    said = " ".join(line for _lvl, line in done.report.lines)
    assert "Removed __pycache__\\ from the app folder" in said
    assert "Removed tests\\ from the app folder" in said
    assert not any(".pyc" in n or "pytest_cache" in n for n in _zip_names(r.local))


def test_a_root_folder_holding_a_real_file_is_never_removed(r):
    from tests.move_layouts import dead_python_leftovers
    write_config(r)
    dead_python_leftovers(r.app)
    write(r.app / "tests" / "test_mine.py", "def test_x(): pass\n")
    write(r.app / "docs" / "notes.md", "mine\n")
    write(r.app / "__pycache__" / "notes.txt", "a real file in the cache folder\n")
    write(r.app / ".pytest_cache" / "my-results.txt", "outside pytest's own v\\ folder\n")
    (r.app / ".pytest_cache" / "CACHEDIR.TAG").unlink()          # no longer pytest's
    done = start(r)
    for kept in ("tests/test_mine.py", "tests/__pycache__", "docs/notes.md",
                 "__pycache__/notes.txt", "__pycache__/moonglade_backup.cpython-311.pyc",
                 ".pytest_cache/my-results.txt"):
        assert (r.app / kept).exists(), kept
    for gone in ("tools", "screenshots"):
        assert not (r.app / gone).exists(), gone
    said = " ".join(line for _lvl, line in done.report.items)
    assert "Left tests\\ in the app folder: it holds files of its own." in said


def test_an_install_already_moved_tidies_them_at_its_next_start(r):
    """C:'s case: the install moved before this fix; its next start removes them."""
    from tests.move_layouts import dead_python_leftovers
    write_config(r)
    start(r)
    dead_python_leftovers(r.app)
    done = start(r)
    assert done.report.worked["install"] is True
    for n in _DEAD_PY:
        assert not (r.app / n).exists(), n
    assert start(r).report.worked["install"] is False, "then nothing at every start"
