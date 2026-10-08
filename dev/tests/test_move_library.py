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
from pathlib import Path

import pytest

from moonglade import gallery as g
from moonglade import migrate
from moonglade import paths
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import (KEY_GONE, KEY_NEL, KEY_NEL_LOWER, db_rows, layout_310,
                                layout_317, layout_c_copy_first, rig, start, write,
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


def test_an_install_on_3_10_to_3_16_moves_whole(r):
    """C: 3.10-3.16 keep every file where 3.17 does, and lack only what came later, so their
    Update (a git pull straight to this version) is followed by the same complete move: no
    file is left behind in an old home, and nothing is lost."""
    layout_310(r)
    done = start(r)
    assert settings.server()["port"] == 5757, "serve.txt's port, as the old launcher used it"
    assert settings.branding()["mark"] == "mark_1"
    assert (r.local / "moonglade.mgpack").read_bytes() == b"PACK-310" * 64
    assert json.loads((r.local / "moonglade.mgpack.version").read_text())["version"] == "3"
    assert json.loads((r.local / "mirror_session.json").read_text()) == {"jwt": "token-310"}
    assert (r.local / "icons" / "mark_1.ico").read_bytes() == b"ICO-1"
    assert (r.local / "logs" / "serve.log").read_text() == "the 3.10 launcher's log\n"
    assert (r.local / "logs" / "moonglade.log").read_text() == "the 3.10 library log\n"
    app = r.lib / "_moonglade"
    for name in ("achievements.json", "telemetry.json", "schedule.json", "jobs.jsonl",
                 "raw_tasks.jsonl", "audit_report.csv"):
        assert (app / "records" / name).is_file(), name
    assert (app / "decisions" / "organize_manifest.csv").is_file()
    acc = app / "accounts" / KEY_NEL
    assert json.loads((acc / "snippets.json").read_text()) == ["a 3.10 snippet"]
    assert json.loads((acc / "views.json").read_text()) == {"mine": "?q=x"}
    assert json.loads((acc / "presets.json").read_text()) == \
        {"scene-a": {"label": "A", "prompt": "p"}}, "the shared presets folded in"
    assert json.loads((app / "loom" / "store.json").read_text())["storyboard:v2:project"]
    assert (app / "loom" / "kv" / KEY_NEL / "storyboard%3Av2%3Aproj%3Ab1.json").is_file()
    assert (app / "loom" / "_frames" / "f1.png").read_bytes() == b"FRAME"
    left_behind = [n for n in ("achievements.json", "telemetry.json", "schedule.json",
                               "jobs.jsonl", "raw_tasks.jsonl", "organize_manifest.csv",
                               "audit_report.csv", "prompt_snippets", "view_presets",
                               "toolbox_presets.json", "logs", "loom", "gallery/cache/_badges")
                   if (r.lib / n).exists()]
    assert left_behind == []
    for n in ("serve.txt", "moonglade.dat", "moonglade.dat.version", "branding.json",
              "mirror_session.json", "serve.log", "_container_cache"):
        assert not (r.app / n).exists(), n
    assert (r.lib / "images" / "a_m1.png").read_bytes() == b"PICTURE"
    assert (r.lib / "catalog.db").read_bytes() == b"CATALOG"
    assert done.report.parked == 0


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


def test_with_no_logins_in_config_the_shared_presets_go_to_the_library_s_own_logins(r):
    """A command-line-only PC's config.json lists no login, but the library holds Nel's files
    (another install's login): the shared presets go to Nel, as they would from that install."""
    layout_317(r, logins=())
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts"
    assert json.loads((acc / KEY_NEL / "presets.json").read_text()) == \
        {"scene-a": {"label": "A", "prompt": "p"}}
    assert not (r.lib / "toolbox_presets.json").exists()


def test_with_config_json_unreadable_the_shared_presets_wait(r):
    """This install's logins can't be known: nothing is given out or deleted on a guess, and
    the shared files are not work for every start."""
    layout_317(r)
    r.cfg.write_text("{ not json", encoding="utf-8")
    with pytest.raises(msetup.MoveStopped):
        _prepare(r)                     # the settings merge needs config.json first
    r.cfg.unlink()                      # a missing config.json: the logins still can't be known
    _prepare(r)
    assert (r.lib / "toolbox_presets.json").is_file(), "nothing is deleted on a guess"
    snap = r.lib / "_moonglade" / ".snapshot"
    zips = sorted(p.name for p in snap.glob("*.zip"))
    _prepare(r)
    assert sorted(p.name for p in snap.glob("*.zip")) == zips


SHARED = {"toolbox_presets.json": ("presets.json", {"scene-a": {"label": "A", "prompt": "p"}}),
          "prompt_snippets.json": ("snippets.json", ["golden hour"]),
          "view_presets.json": ("views.json", {"mine": "?q=moon"})}


def _shared_files_at_the_top(r):
    for name, (_new, doc) in SHARED.items():
        write(r.lib / name, doc)


def test_the_shared_presets_go_to_every_login_the_library_already_holds(r):
    """Two PCs on one library, each with its own config.json: this one lists Nel, the other
    Tania. In 3.10-3.19 every login with no file of its own saw the library's shared files, so
    every login the library already holds gets them -- one with prefs in account_prefs\\, one
    with only Loom boards, one with only a render journal -- not just this config's. The CLI's
    own folder (_local) is not a login."""
    layout_317(r, logins=("Nel",))
    _shared_files_at_the_top(r)
    tania, bo, cy = (paths.account_key(n) for n in ("Tania", "Bo", "Cy"))
    write(r.lib / "account_prefs" / (tania + ".json"), {"theme": "dusk"})
    write(r.lib / "account_prefs" / "_local.json", {"who": "the command line"})
    write(r.lib / "loom" / "kv" / bo / "storyboard%3Av2%3Aproj%3Ab9.json", {"b": 9})
    write(r.lib / "loom" / "_submits" / (cy + ".jsonl"), '{"submit": "c1"}\n')
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts"
    for key in (KEY_NEL, tania, bo, cy):
        for name, (new, doc) in SHARED.items():
            assert json.loads((acc / key / new).read_text()) == doc, (key, new)
    assert not (acc / "_local" / "presets.json").exists()
    for name in SHARED:
        assert not (r.lib / name).exists(), name


def test_with_no_login_anywhere_the_shared_presets_wait_without_counting_as_work(r):
    """No login in config.json and none in the library: there is no one to give the shared
    files to, so they stay where they are -- and they are not old-layout records (the command
    line and the MCP server never read them), not work for every start, and never reset the
    clean-start count, so the safety copy ages out. A login added later gets them at the next
    launcher start."""
    import shutil
    layout_317(r, logins=())
    (r.lib / "account_prefs" / (KEY_NEL + ".json")).unlink()
    shutil.rmtree(r.lib / "loom")                     # no login's boards or render journal
    _shared_files_at_the_top(r)
    _prepare(r)                                       # the first move: everything else
    snap = r.lib / "_moonglade" / ".snapshot"
    zips = sorted(p.name for p in snap.glob("*.zip"))
    assert len(zips) == 1
    for _ in range(3):
        _prepare(r)
        _prepare(r, "cli")                            # never refused
        _prepare(r, "mcp")
    assert sorted(p.name for p in snap.glob("*.zip")) == zips, "no start re-zips them"
    for _ in range(migrate.CLEAN_STARTS + 1):
        _prepare(r, "server").count_clean_start()
    assert not snap.exists(), "the clean-start count was never reset"
    for name in SHARED:
        assert (r.lib / name).is_file(), name

    # A login appears (the web sign-up): the command line still runs, and the next launcher
    # start gives the shared files out.
    write_config(r)
    _prepare(r, "cli")
    _prepare(r, "mcp")
    _prepare(r)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    for name, (new, doc) in SHARED.items():
        assert json.loads((acc / new).read_text()) == doc
        assert not (r.lib / name).exists(), name


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
    # Which of the two the plan meets first follows the folder's sorted listing, and that is
    # case-blind on Windows and case-sensitive elsewhere: "Nel.json" can come first, arrive in
    # the new home, and be parked under that home's name once the newer one comes. Either
    # way the older copy is the one parked, whole.
    parked = [p for p in (r.lib / "_moonglade" / ".snapshot" / "parked").rglob("*")
              if p.is_file()]
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
    """Rehearsal 3: a library's old branding\\ folder (Moonglade's art before it moved beside
    the launcher: marks\\, logo.png...) is not left forever: each file in it is set aside with
    the safety copy (named in the log), the folder goes, and the snapshot rule deletes them in
    time."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    write(r.lib / "branding" / "marks" / "mark_2.png", b"PNG")
    write(r.lib / "branding" / "logo.png", b"LOGO")
    done = _prepare(r)
    assert not (r.lib / "branding").exists()
    parked = sorted(x.name for x in (r.lib / "_moonglade" / ".snapshot" / "parked").rglob("*")
                    if x.is_file())
    assert parked == ["logo.png", "mark_2.png"]
    said = " ".join(line for _lvl, line in done.report.lines)
    assert "branding/marks/mark_2.png" in said and "branding/logo.png" in said


def test_the_legacy_catalog_csv_goes_and_the_catalog_never_does(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    write(r.lib / "catalog.csv", "task_id,media_id,filename,url\nt1,m1,a.png,u\n")
    write(r.lib / "catalog.db", b"CATALOG")
    _prepare(r)
    assert not (r.lib / "catalog.csv").exists()
    assert (r.lib / "catalog.db").read_bytes() == b"CATALOG"
    zips = list((r.lib / "_moonglade" / ".snapshot").glob("*.zip"))
    with zipfile.ZipFile(zips[0]) as zf:
        assert "catalog.csv" in zf.namelist()


# ---- a library is never the program's own folder (#11) ------------------------------------------

def test_a_library_set_to_the_program_s_own_folder_is_refused_by_every_start(r):
    """The library half there would take the Loom's code (<install>\\loom) for the Loom's data.
    Every kind of start refuses it with a plain sentence saying what to change, and nothing in
    the folder moves."""
    write_config(r)
    write(r.app / "loom" / "src" / "main.js", "the Loom's code")
    write(r.app / "moonglade" / "__init__.py", "")
    settings.set_values(library_dir=str(r.app))
    for kind in ("launcher", "server", "cli", "mcp"):
        with pytest.raises(msetup.MoveStopped) as e:
            msetup.prepare(kind)
        assert "Moonglade's own program folder" in str(e.value)
        assert "library_dir" in str(e.value)
    assert (r.app / "loom" / "src" / "main.js").read_text() == "the Loom's code"
    assert not (r.app / "_moonglade").exists()
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare("cli", explicit_out=str(r.app))
    assert "that this run names" in str(e.value)


def test_a_folder_holding_another_install_is_refused(r):
    other = r.lib.parent / "another-install"
    write(other / "local" / "settings.json", {})
    write(other / "loom" / "src" / "main.js", "the Loom's code")
    settings.set_values(library_dir=str(other))
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare("launcher")
    assert "holds a Moonglade program" in str(e.value)
    assert (other / "loom" / "src" / "main.js").is_file()


# ---- an older install still serving the library at its first move (#12) ------------------------

@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="Windows refuses to rename a file another program holds open")
def test_an_older_install_holding_its_log_open_stops_the_first_move(r):
    """3.19's server keeps <library>\\logs\\moonglade.log open while it runs. Its records would
    be moved out from under it (its spend guard among them) before the log refused: the first
    move probes the old logs first, and stops with nothing moved."""
    import subprocess
    import sys
    layout_317(r)
    log = r.lib / "logs" / "moonglade.log"
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import logging, sys, time\n"
         "h = logging.FileHandler(sys.argv[1], encoding='utf-8')\n"
         "h.emit(logging.makeLogRecord({'msg': 'serving'}))\n"
         "print('ready', flush=True)\n"
         "time.sleep(60)\n", str(log)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        with pytest.raises(msetup.MoveStopped) as e:
            _prepare(r)
        assert str(e.value) == migrate.OLDER_RUNNING_WORDS % (log, r.lib)
        assert (r.lib / "train_guard.json").is_file(), "no record moved"
        assert not (r.lib / "_moonglade" / "records").exists() or \
            not list((r.lib / "_moonglade" / "records").iterdir())
    finally:
        holder.kill()
        holder.wait()
    _prepare(r)                                   # closed: the move goes ahead
    assert (r.lib / "_moonglade" / "records" / "train_guard.json").is_file()


# ---- what the stop sentences and the pages read before the move tell the person to do ---------

_ROOT = Path(__file__).resolve().parents[2]
_WIKI = _ROOT / "wiki"
_BOTH_ON_WINDOWS = (
    "Moonglade can tell only when both installs run on Windows and open the same folder (a "
    "shared folder or a NAS share). If either runs on Linux or macOS, close every older install "
    "on the library yourself before the first start. A library kept in step by OneDrive, "
    "Dropbox or another sync tool is a separate copy on each PC, so close every older install "
    "on it yourself first, as on Linux and macOS.")


def _page(name):
    return " ".join((_WIKI / name).read_text(encoding="utf-8").split())


def _move_release_notes():
    """The CHANGELOG section that carries the move's notes: [Unreleased] while it is being
    built, the dated 3.20.0 block once the release is cut. Found by the move's own bullet, so the
    cut (which empties [Unreleased]) never sends this test looking in the wrong section."""
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    at = text.index("**An older Moonglade still using the library stops the start")
    start = text.rfind("\n## [", 0, at)
    end = text.find("\n## [", at)
    return " ".join(text[start:end if end != -1 else len(text)].split())


def test_the_stop_sentences_name_what_actually_stops_an_older_install(r):
    """A 3.10-3.19 server started from its launcher runs under pythonw with no window, and
    closing its browser tab leaves it serving (and holding its log): the sentences name Stop
    server in its Control Panel, its python/pythonw process, its scheduled tasks and a service,
    and the other program that may hold the file."""
    held = migrate.OLDER_RUNNING_WORDS % (r.lib / "logs" / "moonglade.log", r.lib)
    look = migrate._Half("library", r.lib / "_moonglade", migrate._library_roots(r.lib),
                         migrate.Report())
    said = [held] + [migrate._older_live_words(r.lib, [r.lib / "jobs.jsonl"], look, moving)
                     for moving in (True, False)]
    for text in said:
        assert "Stop server in its Control Panel" in text, text
        assert "python or pythonw process" in text, text
        assert "closing its browser tab doesn't stop it" in text, text
        assert "scheduled tasks" in text and "service that starts it" in text, text
        assert "its window" not in text, text
    assert "close the program that has the file open" in held


def test_the_pages_say_windows_tells_only_when_both_installs_run_on_it():
    """Read before an irreversible move: an install on Linux or macOS sees no older install
    anywhere, and none sees one running on Linux or macOS. A library a sync tool keeps in step
    is a separate copy on each PC, whose log the other PC's install never holds: those readers
    close every older install themselves."""
    for name in ("Where-Things-Live.md", "How-It-Works.md"):
        assert _BOTH_ON_WINDOWS in _page(name), name


def test_the_release_notes_and_the_move_s_own_rules_say_the_same():
    """The move's CHANGELOG section (the release notes are cut from it) and the move's docstring:
    the stop at the first move and later, Stop server rather than "close it", and the same
    Windows-and-one-folder limit, sync tools named."""
    notes = _move_release_notes()
    entry = notes[notes.index("**An older Moonglade still using the library stops the start"):]
    entry = entry[:entry.index(" - **")]
    for want in ("at the first move", "**Stop server** in its Control Panel",
                 "closing its browser tab doesn't stop it",
                 "both installs run on Windows and open the same folder",
                 "(a shared folder or a NAS share)", "OneDrive, Dropbox or another sync tool",
                 "a separate copy on each PC", "close every older install"):
        assert want in entry, want
    assert "Close that one" not in notes
    rules = " ".join(migrate.__doc__.split())
    for want in ("both installs run on Windows and open the same folder (a shared folder or a "
                 "NAS share)", "OneDrive, Dropbox or another sync tool",
                 "a separate copy on each PC"):
        assert want in rules, want


def test_the_pages_name_stop_server_and_the_held_log_has_its_own_entry():
    for name in ("Where-Things-Live.md", "Troubleshooting.md"):
        text = _page(name)
        assert "**Stop server** in its Control Panel" in text, name
        assert "closing its browser tab doesn't stop it" in text, name
        assert "its window" not in text, name
    trouble = _page("Troubleshooting.md")
    entry = trouble[trouble.index("*\"Another program has …\\logs\\moonglade.log open …\"*"):]
    entry = entry[:entry.index(" - *")] if " - *" in entry else entry
    for want in ("older Moonglade still running", "scheduled tasks", "**Stop server**",
                 "close the program that has the log open",
                 # #15: how to find which program it is
                 "**Resource Monitor**", "**Associated Handles**", "search for `moonglade.log`"):
        assert want in entry, want


# ---- only what is Moonglade's by its content moves (#10) ----------------------------------------

def _someone_elses_folder(r):
    """A folder of the person's own that shares Moonglade's old names, and nothing else."""
    write(r.lib / "logs" / "camera.log", "not ours\n")
    write(r.lib / "logs" / "2026" / "trip.log", "not ours either\n")
    write(r.lib / "loom" / "weaving.txt", "a real loom\n")
    write(r.lib / "branding" / "client-logo.svg", "<svg/>")
    write(r.lib / "branding.json", {"brand": "Acme"})
    write(r.lib / "catalog.csv", "sku,price\n1,2\n")
    return {p: p.read_bytes() for p in r.lib.rglob("*") if p.is_file()}


def test_a_folder_that_is_not_a_moonglade_library_is_left_exactly_as_it_is(r):
    """#10: a library pointed at a folder of the person's own whose names only match
    Moonglade's old ones (logs\\, loom\\, branding\\, catalog.csv) moves, parks and removes
    nothing, and says once what it left."""
    write_config(r)
    before = _someone_elses_folder(r)
    done = _prepare(r)
    assert {p: p.read_bytes() for p in r.lib.rglob("*") if p.is_file()
            and "_moonglade" not in p.parts} == before
    assert not (r.local / "logs" / "camera.log").exists()
    assert not (r.lib / "_moonglade" / ".snapshot").exists()
    said = " ".join(line for _lvl, line in done.report.lines)
    assert "Left" in said and "aren't Moonglade's" in said
    again = _prepare(r)
    assert again.report.worked["library"] is False


def test_in_a_moonglade_library_only_moonglade_s_own_files_move(r):
    """#10: in a real library, an old home still passes its own content check: the logs\\ hands
    over only moonglade.log and its rotations, the loom\\ only the Loom's own entries; anything
    else of the person's stays where it is, and is named."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    write(r.lib / "logs" / "moonglade.log", "ours\n")
    write(r.lib / "logs" / "moonglade.log.2026-10-01", "ours, rotated\n")
    write(r.lib / "logs" / "camera.log", "not ours\n")
    write(r.lib / "logs" / "2026" / "trip.log", "not ours either\n")
    write(r.lib / "loom" / "kv" / KEY_NEL / "storyboard%3Av2%3Aproj%3Ab1.json", {"b": 1})
    write(r.lib / "loom" / "my-notes.txt", "mine\n")
    write(r.lib / "branding" / "client-logo.svg", "<svg/>")
    write(r.lib / "branding.json", {"brand": "Acme"})
    done = _prepare(r)
    assert (r.local / "logs" / "moonglade.log").read_text() == "ours\n"
    assert (r.local / "logs" / "moonglade.log.2026-10-01").is_file()
    assert (r.lib / "logs" / "camera.log").read_text() == "not ours\n"
    assert (r.lib / "logs" / "2026" / "trip.log").is_file()
    assert (r.lib / "_moonglade" / "loom" / "kv" / KEY_NEL /
            "storyboard%3Av2%3Aproj%3Ab1.json").is_file()
    assert (r.lib / "loom" / "my-notes.txt").read_text() == "mine\n"
    assert (r.lib / "branding" / "client-logo.svg").is_file()
    assert json.loads((r.lib / "branding.json").read_text()) == {"brand": "Acme"}
    assert not list((r.lib / "_moonglade" / ".snapshot").rglob("camera.log*"))
    said = " ".join(line for _lvl, line in done.report.lines)
    assert "camera.log" in said and "my-notes.txt" in said
    assert _prepare(r).report.worked["library"] is False, "not work at every start"


def test_a_log_nothing_of_moonglade_s_writes_never_counts_as_an_older_install(r):
    """#10: after the move, a file another program writes into the library's logs\\ is not an
    older Moonglade still on the library: only moonglade.log* counts."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _prepare(r)
    _written_after_the_move(r.lib / "logs" / "camera.log", "another program\n")
    for kind in ("cli", "mcp", "launcher"):
        msetup.prepare(kind)
    assert (r.lib / "logs" / "camera.log").is_file()


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
