"""The library half of the move (moonglade.migrate.migrate_library): everything of the app's in
a library comes into its _moonglade\\ folder, one home each (SPEC_3.20_REBUILD.md):

  accounts\\<login key>\\   every per-login store (prefs, state, snippets, presets, views)
  loom\\                   the Loom's whole folder
  records\\                achievements (with the skin), telemetry, the schedule, the spend
                          guard, jobs, raw tasks, runs.db, the integrity reports (S6)
  decisions\\              Mark-lost choices, the --organize undo list, curation undo files

and the library's logs come into this install's local\\logs\\. The library itself -- the
catalog, the pictures, the thumbnails -- is never touched. Rebuildable caches (badges, masks,
banner renders) are deleted; a banner render that is the only copy goes to local\\banners\\
and settings.json's worn_banner says the slot wears it (B6). Every login key's files move,
whether or not this install lists the login (X3: another install may share the library); a
file named by a login's plain name goes to that login's folder, and one no login can be found
for stays where it is (S8). The three install-wide preset files are copied into each login
with none of its own, then deleted. The library's dead branding\\ (set aside with the safety
copy), branding.json and catalog.csv go.

Only a launcher or server start moves a library, and only the one this install serves (X1):
the command line, the MCP server and any run naming its own library refuse one still in an
older layout, and every kind stops when an older Moonglade is still writing its old homes.

Layouts: 3.17 (D:'s shape), and C:'s copy-first 3.20 state.
"""
import json
import zipfile

import pytest

from moonglade import gallery as g
from moonglade import migrate
from moonglade import paths
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import (KEY_GONE, KEY_NEL, KEY_NEL_LOWER, db_rows, layout_317,
                                layout_c_copy_first, rig, start, write,
                                write_config)


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _prepare(r, kind="launcher"):
    """A start that may move the library (X1): the launcher's, or the server's."""
    return start(r, kind)


def test_the_3_17_library_moves_into_moonglade(r):
    layout_317(r)
    _prepare(r)
    app = r.lib / "_moonglade"
    rec = app / "records"
    for name in ("achievements.json", "telemetry.json", "schedule.json", "train_guard.json",
                 "reconcile_stamp.json", "jobs.jsonl", "raw_tasks.jsonl", "runs.db",
                 "verify_report.csv"):
        assert (rec / name).is_file(), name
        assert not (r.lib / name).exists(), name
    assert db_rows(rec / "runs.db") == ["r0", "r1", "r2"], "SQLite came across whole"
    assert (app / "decisions" / "organize_manifest.csv").read_text().startswith("old_path")
    assert json.loads((app / "accounts" / KEY_NEL / "prefs.json").read_text()) == \
        {"guide.gallery": "done"}
    assert (app / "loom" / "kv" / KEY_NEL / "storyboard%3Av2%3Aproj%3Ab1.json").is_file()
    assert (app / "loom" / "_submits" / (KEY_NEL + ".jsonl")).read_text() == \
        '{"submit": "s1"}\n'
    assert (r.local / "logs" / "moonglade.log").read_text() == "the library's log\n"
    for gone in ("loom", "logs", "account_prefs", "branding.json", "toolbox_presets.json",
                 "organize_manifest.csv", "gallery/cache/_badges"):
        assert not (r.lib / gone).exists(), gone
    # the library itself is never touched
    assert (r.lib / "catalog.db").read_bytes() == b"CATALOG"
    assert (r.lib / "images" / "a_m1.png").read_bytes() == b"PICTURE"
    assert (r.lib / "gallery" / "thumbs" / "m1.jpg").read_bytes() == b"THUMB"
    journal = json.loads((app / ".journal.json").read_text())
    assert journal["finished"]
    assert journal["items"]["_moonglade/records/train_guard.json"]["state"] == "made"
    assert not (app / ".lock").exists()


def test_the_readers_find_the_moved_records(r):
    layout_317(r)
    _prepare(r)
    assert g.load_ach_state(r.lib)["earned_at"] == {"a1": "2026-09-01"}
    assert g.load_telemetry(r.lib)["counters"] == {"gens": 5}
    from moonglade import runs
    assert runs.RunsStore(r.lib).path.is_file()
    from moonglade import backup as core
    assert core._jobs_path(r.lib).read_text().count("\n") == 2


def test_the_shared_presets_go_to_each_login_with_none_of_its_own(r):
    """D:'s live toolbox_presets.json: copied into every login that has no file of its own
    (what each one saw through the old fallback), then deleted."""
    layout_317(r, logins=("Nel", "Guest"))
    key_guest = paths.account_key("Guest")
    write(r.lib / "toolbox_presets" / (key_guest + ".json"), {"own": {"label": "mine"}})
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts"
    assert json.loads((acc / KEY_NEL / "presets.json").read_text()) == \
        {"scene-a": {"label": "A", "prompt": "p"}}
    assert json.loads((acc / key_guest / "presets.json").read_text()) == \
        {"own": {"label": "mine"}}, "a login's own file is never overwritten"
    assert not (r.lib / "toolbox_presets.json").exists()


def test_with_no_logins_the_shared_presets_wait(r):
    layout_317(r, logins=())
    _prepare(r)
    assert (r.lib / "toolbox_presets.json").is_file(), "nothing is deleted on a guess"


def test_two_logins_get_two_folders_and_another_install_s_login_moves_too(r):
    """`Nel` and `nel` are two logins (a case-safe key each). A key no login in THIS install's
    config.json has may be another install's login on a shared library (X3): its files move
    into accounts\\<key>\\ like any other, and nothing is deleted."""
    write_config(r, AUTH_USERS=[{"username": "Nel", "password_hash": "x"},
                                {"username": "nel", "password_hash": "y"}])
    for key, who in ((KEY_NEL, "Nel"), (KEY_NEL_LOWER, "nel"), (KEY_GONE, "gone")):
        write(r.lib / "account_prefs" / (key + ".json"), {"who": who})
        write(r.lib / "view_presets" / (key + ".json"), {"v": "?q=" + who})
    write(r.lib / "account_state" / (KEY_NEL + ".json"), {"pokes": 3})
    write(r.lib / "prompt_snippets" / (KEY_NEL_LOWER + ".json"), ["a snippet"])
    write(r.lib / "account_prefs" / "_local.json", {"who": "the command line"})
    write(r.lib / "account_prefs" / (KEY_NEL + ".lock"), "")
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts"
    assert json.loads((acc / KEY_NEL / "prefs.json").read_text()) == {"who": "Nel"}
    assert json.loads((acc / KEY_NEL_LOWER / "prefs.json").read_text()) == {"who": "nel"}
    assert json.loads((acc / KEY_NEL / "state.json").read_text()) == {"pokes": 3}
    assert json.loads((acc / KEY_NEL_LOWER / "snippets.json").read_text()) == ["a snippet"]
    assert json.loads((acc / KEY_NEL / "views.json").read_text()) == {"v": "?q=Nel"}
    assert json.loads((acc / "_local" / "prefs.json").read_text()) == \
        {"who": "the command line"}
    assert json.loads((acc / KEY_GONE / "prefs.json").read_text()) == {"who": "gone"}
    assert json.loads((acc / KEY_GONE / "views.json").read_text()) == {"v": "?q=gone"}
    assert sorted(p.name for p in acc.iterdir()) == \
        sorted([KEY_NEL, KEY_NEL_LOWER, KEY_GONE, "_local"])
    zips = list((r.lib / "_moonglade" / ".snapshot").glob("*.zip"))
    with zipfile.ZipFile(zips[0]) as zf:
        assert "account_prefs/%s.json" % KEY_GONE in zf.namelist()
    # and the app reads each login's own folder
    assert g.account_prefs_path(r.lib, "nel") == acc / KEY_NEL_LOWER / "prefs.json"


def test_with_config_unreadable_no_login_s_files_are_dropped(r):
    """A login list that cannot be known removes nothing."""
    write(r.lib / "account_prefs" / (KEY_GONE + ".json"), {"who": "?"})
    _prepare(r)                                  # no config.json at all
    assert (r.lib / "_moonglade" / "accounts" / KEY_GONE / "prefs.json").is_file()


def test_a_file_named_by_a_login_s_plain_name_goes_to_that_login(r):
    """S8: before the hashed keys a store named its file by the login itself. A known login's
    plain-name file goes to its folder."""
    write_config(r, AUTH_USERS=[{"username": "Nel", "password_hash": "x"},
                                {"username": "Nel Smith", "password_hash": "y"}])
    write(r.lib / "view_presets" / "Nel.json", {"plain-name": "before the hashing"})
    write(r.lib / "prompt_snippets" / "Nel%20Smith.json", ["old snippet"])
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts"
    assert json.loads((acc / KEY_NEL / "views.json").read_text()) == \
        {"plain-name": "before the hashing"}
    assert json.loads((paths.account_dir(r.lib, "Nel Smith") / "snippets.json").read_text()) \
        == ["old snippet"]
    assert not (r.lib / "view_presets").exists() and not (r.lib / "prompt_snippets").exists()


def test_a_plain_name_file_and_the_login_s_own_keep_the_newer(r):
    import os
    write_config(r)
    write(r.lib / "view_presets" / (KEY_NEL + ".json"), {"v": "hashed, newer"})
    write(r.lib / "view_presets" / "Nel.json", {"v": "plain, older"})
    os.utime(r.lib / "view_presets" / "Nel.json", (1_500_000_000, 1_500_000_000))
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts"
    assert json.loads((acc / KEY_NEL / "views.json").read_text()) == {"v": "hashed, newer"}
    parked = list((r.lib / "_moonglade" / ".snapshot" / "parked").rglob("Nel.json*"))
    assert [json.loads(x.read_text()) for x in parked] == [{"v": "plain, older"}]


def test_a_plain_name_file_no_login_matches_stays_in_the_library(r):
    """S8: nobody to give it to, so it stays where it is (said in the log), and nothing ever
    deletes it with the safety copy."""
    write_config(r)
    write(r.lib / "view_presets" / "Stranger.json", {"plain-name": "whose?"})
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    done = _prepare(r)
    assert json.loads((r.lib / "view_presets" / "Stranger.json").read_text()) == \
        {"plain-name": "whose?"}
    assert not list((r.lib / "_moonglade").rglob("Stranger.json"))
    assert any("Stranger.json" in line and "where it is" in line
               for _lvl, line in done.report.lines)
    again = _prepare(r)
    assert again.report.worked["library"] is False, "it is not work at every start"


def test_removing_a_login_removes_its_folder(r):
    """S10: the Users tab's remove, and the command line's --remove-web-user."""
    from moonglade import backup as core
    write_config(r)
    folder = paths.account_dir(r.lib, "Nel")
    write(folder / "prefs.json", {"x": 1})
    assert core.remove_login_files(r.lib, "Nel") is True
    assert not folder.exists()
    assert core.remove_login_files(r.lib, "Nel") is False


def test_c_s_copy_first_library(r):
    """The _moonglade\\ copies are the live ones; the library-top copies are what 3.20 copied
    and are unchanged since (MOVED.json's fingerprints), so they go. MOVED.json, the old lock
    and the emptied reports\\ folder go too."""
    lib = layout_c_copy_first(r)
    done = msetup.prepare("launcher")            # the library comes from the merged settings
    assert done.library == lib
    app = lib / "_moonglade"
    rec = app / "records"
    assert json.loads((rec / "achievements.json").read_text())["skin"] == "dusk"
    assert (rec / "jobs.jsonl").read_text() == '{"id": "j1"}\n{"id": "j2"}\n{"id": "j3"}\n'
    assert json.loads((rec / "integrity_report.json").read_text()) == {"format": 1, "live": True}
    assert json.loads((app / "accounts" / KEY_NEL / "prefs.json").read_text()) == \
        {"guide.gallery": "live"}
    assert (r.local / "logs" / "moonglade.log").read_text() == "the live log\n"
    for gone in ("achievements.json", "telemetry.json", "jobs.jsonl", "runs.db",
                 "account_prefs", "logs", "integrity_report.json"):
        assert not (lib / gone).exists(), gone
    for gone in (migrate.OLD_RECORD, migrate.OLD_LOCK, "reports", "logs", "account_prefs",
                 "achievements.json", "runs.db"):
        assert not (app / gone).exists(), gone
    assert not list((app / ".snapshot" / "parked").rglob("*.*")), \
        "every old copy was a recorded, unchanged 3.20 copy"


def test_c_s_old_copy_written_since_is_merged_not_lost(r):
    """An older install wrote the library-top jobs.jsonl after 3.20 copied it: the lines it
    added are merged in, nothing is deleted on a guess."""
    lib = layout_c_copy_first(r)
    with open(lib / "jobs.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": "from-an-old-install"}\n')
    msetup.prepare("launcher")
    lines = (lib / "_moonglade" / "records" / "jobs.jsonl").read_text().splitlines()
    assert lines == ['{"id": "j1"}', '{"id": "j2"}', '{"id": "j3"}',
                     '{"id": "from-an-old-install"}']
    assert not (lib / "jobs.jsonl").exists()


def test_the_banners_b6(r):
    """slot: rebuilt from the pick (deleted). earned: rebuilt from the pack, the choice goes
    into worn_banner. migrated, and a render with no record: the only copy -- it moves whole
    into local\\banners\\ and the slot wears it. Never into the art tree."""
    write_config(r)
    b = r.lib / "gallery" / "cache" / "_banners"
    write(b / "banner.png", b"EARNED-RENDER")
    write(b / "banner.png.json", {"kind": "earned", "banner_id": "great_library"})
    write(b / "login-banner.png", b"MIGRATED")
    write(b / "login-banner.png.json", {"kind": "migrated"})
    write(b / "banner-loom.png", b"NO-RECORD")
    write(r.lib / "gallery" / "cache" / "_masks" / "x.png", b"MASK")
    _prepare(r)
    worn = settings.branding()["worn_banner"]
    assert worn == {"banner_main": {"kind": "earned", "banner_id": "great_library"},
                    "banner_login": {"kind": "migrated"},
                    "banner_loom": {"kind": "migrated"}}
    assert (r.local / "banners" / "login-banner.png").read_bytes() == b"MIGRATED"
    assert (r.local / "banners" / "banner-loom.png").read_bytes() == b"NO-RECORD"
    assert not (r.local / "banners" / "banner.png").exists(), "an earned render is rebuilt"
    assert not (r.lib / "gallery" / "cache" / "_banners").exists()
    assert not (r.lib / "gallery" / "cache" / "_masks").exists()
    assert not g.branding_root().exists() or not list(g.branding_root().rglob("*.png"))
    # what the app serves for the migrated slot is the kept copy
    assert g._served_flat_dir(r.lib, "banner_login") == r.local / "banners"
    assert g._ensure_banner_flat(r.lib, "banner_login") == r.local / "banners" / "login-banner.png"


def test_a_slot_render_is_simply_rebuilt(r):
    write_config(r)
    b = r.lib / "gallery" / "cache" / "_banners"
    write(b / "banner.png", b"SLOT")
    write(b / "banner.png.json", {"kind": "slot", "asset_id": "a1", "transform": {}})
    _prepare(r)
    assert "worn_banner" not in settings.branding()
    assert not (r.local / "banners").exists()


def test_a_library_that_is_not_there_yet_is_left_alone(r):
    write_config(r)
    nowhere = r.lib.parent / "not-yet"
    done = msetup.prepare("cli", explicit_out=str(nowhere))
    assert done.library == nowhere and not nowhere.exists()


def test_a_second_start_finds_nothing_to_move(r):
    layout_317(r)
    _prepare(r)
    done = _prepare(r)
    assert done.report.worked == {"install": False, "library": False}
    assert done.report.lines == []


def test_the_walkers_never_see_the_moved_loom(r):
    """The Loom's frames and cut live under _moonglade\\ now, which every walker prunes."""
    layout_317(r)
    write(r.lib / "loom" / "_frames" / "last.png", b"\x89PNG frame")
    write(r.lib / "loom" / "exports" / "loom_cut.mp4", b"CUT")
    _prepare(r)
    assert (r.lib / "_moonglade" / "loom" / "_frames" / "last.png").is_file()
    seen = [e.rel.as_posix() for e in g.scan_library(r.lib)]
    assert not any("loom" in s or "_moonglade" in s for s in seen), seen


# ---- the library's dead branding folder, and the legacy catalog.csv (rehearsal 3, S9) ----------

def test_the_dead_branding_folder_goes_with_the_safety_copy(r):
    """Rehearsal 3: a library's old branding\\ folder holding files is not left forever: each
    file is set aside with the safety copy (named in the log), the folder goes, and the
    snapshot rule deletes them in time."""
    write_config(r)
    write(r.lib / "branding" / "old" / "orphan.png", b"PNG")
    write(r.lib / "branding" / "mark.txt", "x")
    done = _prepare(r)
    assert not (r.lib / "branding").exists()
    parked = sorted(x.name for x in (r.lib / "_moonglade" / ".snapshot" / "parked").rglob("*")
                    if x.is_file())
    assert parked == ["mark.txt", "orphan.png"]
    said = " ".join(line for _lvl, line in done.report.lines)
    assert "branding/old/orphan.png" in said and "branding/mark.txt" in said


def test_the_legacy_catalog_csv_goes_and_the_catalog_never_does(r):
    write_config(r)
    write(r.lib / "catalog.csv", "media_id,path\nm1,a.png\n")
    write(r.lib / "catalog.db", b"CATALOG")
    _prepare(r)
    assert not (r.lib / "catalog.csv").exists()
    assert (r.lib / "catalog.db").read_bytes() == b"CATALOG"
    zips = list((r.lib / "_moonglade" / ".snapshot").glob("*.zip"))
    with zipfile.ZipFile(zips[0]) as zf:
        assert "catalog.csv" in zf.namelist()


# ---- who may move a library (X1) ----------------------------------------------------------------

_REFUSED = "still in an older Moonglade's layout"


@pytest.mark.parametrize("kind", ["cli", "mcp"])
def test_the_command_line_and_the_mcp_server_never_move_a_library(r, kind):
    """X1: a library still in an older layout is refused, plainly, and nothing in it moves:
    an older install may be serving it right now."""
    layout_317(r)
    settings.set_values(library_dir=str(r.lib))
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare(kind)
    assert _REFUSED in str(e.value) and "Moonglade Launcher" in str(e.value)
    for still in ("train_guard.json", "jobs.jsonl", "achievements.json", "loom", "logs"):
        assert (r.lib / still).exists(), still
    assert not (r.lib / "_moonglade").exists()
    assert settings.server()["port"] == 5757, "the install half still ran"


@pytest.mark.parametrize("kind", ["cli", "mcp", "server"])
def test_a_run_naming_its_own_library_never_moves_it(r, kind):
    """X1: --out / MOONGLADE_OUT name a library for one run, often another install's (C:'s
    Claude tools on D:'s library): never moved, whatever the kind."""
    layout_317(r)
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare(kind, explicit_out=str(r.lib))
    assert _REFUSED in str(e.value) and "MOONGLADE_OUT" in str(e.value)
    assert (r.lib / "train_guard.json").is_file() and not (r.lib / "_moonglade").exists()


def test_once_the_launcher_moved_it_the_command_line_opens_it(r):
    layout_317(r)
    _prepare(r)
    done = msetup.prepare("cli")
    assert done.library == r.lib and done.report.worked["library"] is False
    assert msetup.prepare("mcp", explicit_out=str(r.lib)).library == r.lib


def test_a_library_with_nothing_to_move_needs_no_lock(r, monkeypatch):
    """S2: a read-only library (restored from a disc, a share this user may only read) opened
    in 3.19; with nothing to move it still opens -- no lock is needed to read it."""
    write_config(r)
    _prepare(r)                                  # a fresh library, its journal stamped
    real = migrate.FolderLock.acquire

    def acquire(self, wait=None):
        if "_moonglade" in str(self.path):
            raise migrate.MoveStopped("Moonglade can't write in the library")
        return real(self, wait)
    monkeypatch.setattr(migrate.FolderLock, "acquire", acquire)
    for kind in ("launcher", "server", "cli", "mcp"):
        assert msetup.prepare(kind).library == r.lib


def _written_after_the_move(path, text):
    import os
    write(path, text)
    later = path.stat().st_mtime + 120
    os.utime(path, (later, later))


def test_an_older_install_still_writing_the_library_stops_every_start(r):
    """X1: after the move, an old-layout record written later means an older Moonglade is still
    using this library. Sweeping it would hide that one's records (its spend guard among them),
    so every kind of start stops and says so, and nothing is moved."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _prepare(r)
    _written_after_the_move(r.lib / "train_guard.json",
                            json.dumps({"basic": {"k": {"at": 9.0}}, "retried": {}, "paid": {}}))
    for kind in ("cli", "mcp", "launcher"):
        with pytest.raises(msetup.MoveStopped) as e:
            msetup.prepare(kind)
        assert "An older Moonglade is still using the library" in str(e.value)
        assert "train_guard.json" in str(e.value)
    assert (r.lib / "train_guard.json").is_file(), "nothing was swept"


def test_started_again_with_nothing_more_written_it_brings_that_in(r):
    """Told to close the older Moonglade, the person starts this one again: nothing more was
    written there since, so the move brings in what the older one wrote (merged, not lost)."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _prepare(r)
    _written_after_the_move(r.lib / "jobs.jsonl", '{"id": 1}\n{"id": "older-install"}\n')
    with pytest.raises(msetup.MoveStopped):
        _prepare(r)
    done = _prepare(r)
    assert done.report.worked["library"] is True
    got = (r.lib / "_moonglade" / "records" / "jobs.jsonl").read_text().splitlines()
    assert got == ['{"id": 1}', '{"id": "older-install"}']
    assert not (r.lib / "jobs.jsonl").exists()


def test_a_write_between_the_two_starts_stops_it_again(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _prepare(r)
    _written_after_the_move(r.lib / "jobs.jsonl", '{"id": 1}\n{"id": 2}\n')
    with pytest.raises(msetup.MoveStopped):
        _prepare(r)
    _written_after_the_move(r.lib / "jobs.jsonl", '{"id": 1}\n{"id": 2}\n{"id": 3}\n')
    with pytest.raises(msetup.MoveStopped):
        _prepare(r)
