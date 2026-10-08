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

import pytest

from moonglade import migrate
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import (layout_317, layout_c_copy_first, read_config, rig, write,
                                write_config)


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
    msetup.prepare("cli", explicit_out=str(r.lib))
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
    msetup.prepare("cli", explicit_out=str(r.lib))
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
    done = msetup.prepare("cli", explicit_out=str(r.lib))
    b = settings.branding()
    assert b["mark"] == "mark_4" and b["animation"]["anim"] == "aurora", "the live copy"
    assert b["slots"] == {"banner_main": "live"}
    for gone in ("serve.txt", "branding.json", "branding_slots.json", "serve.log",
                 "_container_cache"):
        assert not (r.app / gone).exists(), gone
    for gone in ("serve.txt", "branding.json", "branding_slots.json", "serve.log",
                 migrate.OLD_RECORD, "cache/marks"):
        assert not (r.local / gone).exists(), gone
    assert (r.local / "logs" / "serve.log").read_text() == "the 3.20 launcher's log\n"
    assert (r.local / "icons" / "mark_4.ico").read_bytes() == b"ICO-4"
    assert (r.local / "moonglade.mgpack").read_bytes() == b"PACK-320" * 64
    # 3.20 started serve.log fresh in local\ and never copied the root one, so the two are
    # different files of one name: the newer is kept and the old launcher's is parked.
    parked = sorted((r.local / ".snapshot" / "parked").rglob("*"))
    assert [p.name for p in parked if p.is_file()] == ["serve.log"]
    assert parked[-1].read_text() == "the old launcher's log\n"
    assert done.report.parked == 1


def test_an_old_copy_written_since_3_20_copied_it_is_parked_not_deleted(r):
    layout_c_copy_first(r)
    write(r.app / "branding.json", {"mark": "written-since", "anim": "glow"})
    msetup.prepare("cli", explicit_out=str(r.lib))
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
