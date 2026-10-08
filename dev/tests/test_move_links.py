"""Junctions and symbolic links in an old home (B). The move never walks into one, never copies
what one points at, never deletes through one, and its tree removal never follows one:

  * a link in an old home moves AS A LINK: the link entry itself is renamed into the new home
    on the same drive (a junctioned loom\\ -- the Loom kept on another drive -- keeps working
    from _moonglade\\loom\\, and its files never leave the drive they are on);
  * a link that can't move as a link (its new home is taken; a login store's folder whose
    files would have to split up) is left where it is, and the start stops, before anything
    moves, with a plain sentence;
  * a cache that is a link goes as the link alone; a branding\\ or logs\\ that is one is left;
  * deleting a tree (the safety copy after five clean starts, a cache, a removed folder)
    removes a link inside as the link alone.

Every link here is a real Windows junction in the test's own temp folder (no privilege is
needed to make one), pointing at a folder outside the library.
"""
import json
import os
import stat
import sys

import pytest

from moonglade import migrate
from moonglade import setup as msetup
from tests.move_layouts import KEY_NEL, library_records, rig, start, write, write_config

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="a real Windows junction")

BOARD = "storyboard%3Av2%3Aproj%3Ab1.json"


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _junction(link, target):
    import _winapi
    link.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))
    assert migrate._is_link(link) and not os.path.islink(link), "a junction, not a symlink"
    return link


def _tree(folder):
    """{relative path: bytes} of every file under `folder` (a real folder, walked plainly)."""
    out = {}
    for dirpath, _dirs, files in os.walk(folder):
        for fn in files:
            p = os.path.join(dirpath, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, folder)] = f.read()
    return out


def _elsewhere(r, name):
    return r.lib.parent / "another-drive" / name


def _a_library(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')


def test_a_junctioned_loom_moves_as_the_link_and_its_files_stay_where_they_are(r):
    _a_library(r)
    target = _elsewhere(r, "loom-data")
    write(target / "kv" / KEY_NEL / BOARD, {"title": "kept on another drive"})
    write(target / "exports" / "cut.mp4", b"VIDEO" * 100)
    write(target / "_submits" / (KEY_NEL + ".jsonl"), '{"s": 1}\n')
    before = _tree(target)
    _junction(r.lib / "loom", target)
    done = start(r)
    new = r.lib / "_moonglade" / "loom"
    assert migrate._is_link(new), "the link itself moved"
    assert os.path.realpath(new) == os.path.realpath(target)
    assert not os.path.lexists(r.lib / "loom")
    assert _tree(target) == before, "nothing it points at was copied, moved or deleted"
    lib_files, _links = migrate._scan(r.lib)
    assert not [p for p in lib_files if p.name in ("cut.mp4", BOARD)], \
        "no copy of the link's files landed in the library"
    from moonglade import gallery as g
    assert [p.name for p in g._loom_board_files(r.lib)] == [BOARD], "the Loom reads through it"
    assert any("Moved the link loom" in line for _lvl, line in done.report.items)


def test_a_junction_inside_the_loom_moves_as_a_link(r):
    _a_library(r)
    write(r.lib / "loom" / "kv" / KEY_NEL / BOARD, {"b": 1})
    target = _elsewhere(r, "exports")
    write(target / "cut.mp4", b"VIDEO")
    _junction(r.lib / "loom" / "exports", target)
    start(r)
    loom = r.lib / "_moonglade" / "loom"
    assert json.loads((loom / "kv" / KEY_NEL / BOARD).read_text()) == {"b": 1}
    assert migrate._is_link(loom / "exports")
    assert os.path.realpath(loom / "exports") == os.path.realpath(target)
    assert (target / "cut.mp4").read_bytes() == b"VIDEO"
    assert not os.path.lexists(r.lib / "loom")


def test_a_link_whose_new_home_is_taken_stops_before_anything_moves(r):
    _a_library(r)
    write(r.lib / "_moonglade" / "loom" / "kv" / KEY_NEL / BOARD, {"already": "here"})
    target = _elsewhere(r, "loom-data")
    write(target / "kv" / KEY_NEL / BOARD, {"on": "another drive"})
    before = _tree(target)
    _junction(r.lib / "loom", target)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    text = str(e.value)
    assert "is a link (a junction or a symbolic link)" in text
    assert "already taken" in text and "Nothing it points at was touched" in text
    assert "to %s." % target in text and "\\\\?\\" not in text, "a plain path, no \\\\?\\"
    assert migrate._is_link(r.lib / "loom"), "the link is left where it is"
    assert _tree(target) == before
    assert (r.lib / "jobs.jsonl").is_file(), "nothing moved before the stop"


def test_a_login_store_folder_that_is_a_link_stops_and_is_left(r):
    _a_library(r)
    target = _elsewhere(r, "prefs")
    write(target / (KEY_NEL + ".json"), {"guide": "done"})
    _junction(r.lib / "account_prefs", target)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "can't move as one link" in str(e.value)
    assert migrate._is_link(r.lib / "account_prefs")
    assert json.loads((target / (KEY_NEL + ".json")).read_text()) == {"guide": "done"}


def test_a_junctioned_cache_goes_as_the_link_alone(r):
    _a_library(r)
    target = _elsewhere(r, "badges")
    write(target / "a1.png", b"BADGE")
    _junction(r.lib / "gallery" / "cache" / "_badges", target)
    done = start(r)
    assert not os.path.lexists(r.lib / "gallery" / "cache" / "_badges")
    assert (target / "a1.png").read_bytes() == b"BADGE", "what it pointed at is untouched"
    assert any("Removed the link" in line for _lvl, line in done.report.items)


def test_a_junctioned_branding_or_logs_folder_is_left_where_it_is(r):
    _a_library(r)
    art, logs = _elsewhere(r, "art"), _elsewhere(r, "logs")
    write(art / "marks" / "mark_2.png", b"PNG")
    write(logs / "moonglade.log", "kept elsewhere\n")
    _junction(r.lib / "branding", art)
    _junction(r.lib / "logs", logs)
    done = start(r)
    assert migrate._is_link(r.lib / "branding") and migrate._is_link(r.lib / "logs")
    assert (art / "marks" / "mark_2.png").read_bytes() == b"PNG"
    assert (logs / "moonglade.log").read_text() == "kept elsewhere\n"
    said = " ".join(line for _lvl, line in done.report.all_lines())
    assert "branding" in said and "logs" in said and "Left" in said


def test_deleting_a_tree_never_follows_a_junction(tmp_path):
    """The safety copy's deletion (and every tree the move removes) takes a link inside as
    the link alone: a file read-only in the target keeps its attribute, and stays."""
    target = tmp_path / "elsewhere"
    write(target / "keep.txt", "mine")
    os.chmod(target / "keep.txt", stat.S_IREAD)
    tree = tmp_path / ".snapshot"
    write(tree / "before-the-move.zip", b"ZIP")
    _junction(tree / "parked" / "branding", target)
    migrate._rmtree_whole(tree)
    assert not tree.exists()
    assert (target / "keep.txt").read_text() == "mine"
    assert not os.stat(target / "keep.txt").st_mode & stat.S_IWRITE, "never made writable"
    link = _junction(tmp_path / "cache-link", target)
    migrate._remove(link)
    assert not os.path.lexists(link) and (target / "keep.txt").is_file()
    os.chmod(target / "keep.txt", stat.S_IREAD | stat.S_IWRITE)


def test_the_five_start_deletion_of_the_safety_copy_leaves_a_parked_link_s_target(r):
    _a_library(r)
    art = _elsewhere(r, "art")
    write(art / "marks" / "mark_2.png", b"PNG")
    write(r.lib / "branding" / "logo.png", b"LOGO")
    _junction(r.lib / "branding" / "marks", art / "marks")
    done = start(r, "server")
    parked = r.lib / "_moonglade" / ".snapshot" / "parked" / "branding"
    assert migrate._is_link(parked / "marks"), "the link was set aside as a link"
    for _ in range(migrate.CLEAN_STARTS + 1):
        done.counted = False
        done.count_clean_start()
    assert not (r.lib / "_moonglade" / ".snapshot").exists()
    assert (art / "marks" / "mark_2.png").read_bytes() == b"PNG"


def test_a_junctioned_icon_cache_in_the_app_folder_goes_as_the_link_alone(r):
    write_config(r)
    target = _elsewhere(r, "icons")
    write(target / "marks" / "mark_2.ico", b"ICO")
    _junction(r.app / "_container_cache", target)
    msetup.prepare("cli")
    assert not os.path.lexists(r.app / "_container_cache")
    assert (target / "marks" / "mark_2.ico").read_bytes() == b"ICO"


# ---- every link is checked before anything moves -------------------------------------------------

def _all_records_still_at_the_top(r):
    return all((r.lib / n).exists() for n in ("achievements.json", "jobs.jsonl", "runs.db"))


def test_a_record_that_is_a_link_with_its_home_taken_stops_before_anything_moves(r):
    """A record (or a decision, or a curation undo file) is planned with its own kind, not as
    a link; one that IS a link still moves only as a link, so a taken home stops the start
    before any other record has moved."""
    write_config(r)
    library_records(r.lib)
    (r.lib / "raw_tasks.jsonl").unlink()
    _junction(r.lib / "raw_tasks.jsonl", _elsewhere(r, "raw-tasks"))
    write(r.lib / "_moonglade" / "records" / "raw_tasks.jsonl", '{"t": "already here"}\n')
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "raw_tasks.jsonl is a link" in str(e.value) and "already taken" in str(e.value)
    assert _all_records_still_at_the_top(r), "nothing moved before the stop"
    assert not (r.lib / "_moonglade" / "records" / "achievements.json").exists()


def test_a_link_whose_new_home_is_on_another_drive_stops_before_anything_moves(r, monkeypatch):
    """A link can only be renamed on its own drive: one whose new home is on another (a
    _moonglade that is itself a junction to another drive, say) stops the start before
    anything moves, not after the records went."""
    write_config(r)
    library_records(r.lib)
    target = _elsewhere(r, "loom-data")
    write(target / "kv" / KEY_NEL / BOARD, {"b": 1})
    _junction(r.lib / "loom", target)
    monkeypatch.setattr(migrate, "_same_device", lambda src, dest: not migrate._is_link(src))
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "another drive" in str(e.value)
    assert _all_records_still_at_the_top(r)
    assert migrate._is_link(r.lib / "loom")


def test_a_relative_symbolic_link_stops_on_windows_before_anything_moves(r, monkeypatch):
    """On Windows a symbolic link whose target is written relative to its own folder would
    point somewhere else from its deeper new home, and making it again needs a privilege: the
    start stops, before anything moves, and says how to fix it. (A real symbolic link needs
    that privilege to make, so the junction here reports a relative target;
    test_move_symlinks.py makes real ones where it can.)"""
    write_config(r)
    library_records(r.lib)
    target = _elsewhere(r, "loom-data")
    write(target / "kv" / KEY_NEL / BOARD, {"b": 1})
    _junction(r.lib / "loom", target)
    rel = os.path.join("..", "another-drive", "loom-data")
    monkeypatch.setattr(migrate, "_symlink_text",
                        lambda p: rel if os.path.normcase(str(p)) ==
                        os.path.normcase(str(r.lib / "loom")) else None)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    text = str(e.value)
    assert "written from where it sits (%s)" % rel in text
    assert "point by its full path" in text
    assert _all_records_still_at_the_top(r)
    assert migrate._is_link(r.lib / "loom")


# ---- the copy-first layout's own folders: never through a link -----------------------------------

def test_a_junctioned_local_cache_keeps_its_icons(r):
    """3.20's first build kept the shortcut icons in local\\cache\\marks\\. With local\\cache a
    junction, its icons are never walked (they stay where it points), and the leftover is
    never deleted inside the junction's target either."""
    write_config(r)
    target = _elsewhere(r, "cache")
    write(target / "marks" / "mark_4.ico", b"ICO-4")
    _junction(r.local / "cache", target)
    msetup.prepare("cli")
    assert (target / "marks" / "mark_4.ico").read_bytes() == b"ICO-4"
    assert migrate._is_link(r.local / "cache")


def test_a_junctioned_reports_folder_stops_and_nothing_moves_through_it(r):
    """3.20's _moonglade\\reports\\ that is a junction: its files would split between
    records\\ and decisions\\, so it can't move as one link. The start stops before anything
    moves, and nothing in what it points at is moved or deleted."""
    write_config(r)
    library_records(r.lib)
    target = _elsewhere(r, "reports")
    write(target / "integrity_report.json", {"format": 1})
    write(target / "integrity_report.lock", "1")
    write(target / "curation_pre_import_1.json", {"undo": 1})
    before = _tree(target)
    _junction(r.lib / "_moonglade" / "reports", target)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "reports is a link" in str(e.value) and "can't move as one link" in str(e.value)
    assert _tree(target) == before
    assert _all_records_still_at_the_top(r)


# ---- an older install holding its log through a linked logs\ (round 2, #4) -----------------------

def _hold_open(path):
    """Another process holding `path` open the way 3.19's log handler does while it serves."""
    import subprocess
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import logging, sys, time\n"
         "h = logging.FileHandler(sys.argv[1], encoding='utf-8')\n"
         "h.emit(logging.makeLogRecord({'msg': 'serving'}))\n"
         "print('ready', flush=True)\n"
         "time.sleep(60)\n", str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    assert holder.stdout.readline().strip() == "ready"
    return holder


def test_an_idle_older_install_holding_its_log_through_a_junctioned_logs_folder_stops(r):
    """A logs\\ that is a junction is left where it is, so no log move is planned; the probe
    still looks at the moonglade.log files inside it. With an idle older install holding its
    log, every start stops before any record moves (its spend guard among them)."""
    write_config(r)
    library_records(r.lib)
    logs = _elsewhere(r, "logs")
    write(logs / "moonglade.log", "3.19's log\n")
    _junction(r.lib / "logs", logs)
    holder = _hold_open(logs / "moonglade.log")
    try:
        for _ in range(2):
            with pytest.raises(msetup.MoveStopped) as e:
                start(r)
            assert str(e.value) == migrate.OLDER_RUNNING_WORDS % (
                r.lib / "logs" / "moonglade.log", r.lib)
            assert _all_records_still_at_the_top(r)
            assert (r.lib / "train_guard.json").is_file()
    finally:
        holder.kill()
        holder.wait()
    start(r)                                      # closed: the move goes ahead
    assert (r.lib / "_moonglade" / "records" / "train_guard.json").is_file()
    assert migrate._is_link(r.lib / "logs"), "the linked logs\\ itself is still left"


def test_a_linked_moonglade_log_is_probed_through_what_it_points_at(r, monkeypatch):
    """A moonglade.log that is itself a link is never moved: it is probed by the file it
    points at, so a holder there still stops the start."""
    logs = r.lib / "logs"
    write(logs / "other.txt", "x")
    real_log = write(_elsewhere(r, "logs") / "moonglade.log", "3.19's log\n")
    plan = migrate._Plan()
    plan.log_links.append(logs / "moonglade.log")
    monkeypatch.setattr(migrate, "_is_link",
                        lambda p: os.path.normcase(str(p)) ==
                        os.path.normcase(str(logs / "moonglade.log")))
    monkeypatch.setattr(migrate, "_link_file", lambda p: real_log)
    probed = []
    monkeypatch.setattr(migrate, "_held_open", lambda p: probed.append(str(p)) or True)
    assert migrate._old_log_in_use(plan) == logs / "moonglade.log"
    assert probed == [str(real_log)]


# ---- a link whose target the same plan moves (round 2 #9; round 3 #9, #10) ----------------------

def _pretend_relative(monkeypatch, link, text):
    """The junction `link` reports `text` as a relative target (a real relative symbolic link
    needs a privilege to make on Windows; test_move_symlinks.py makes real ones where it can)."""
    monkeypatch.setattr(migrate, "_symlink_text",
                        lambda p: text if os.path.normcase(str(p)) ==
                        os.path.normcase(str(link)) else None)


def test_a_junction_into_a_folder_the_loom_also_moves_stops_before_anything_moves(r):
    """#9: a junction (mklink /J, the usual way to make loom\\exports\\latest) always points by
    its full path. Renamed as it is, it would point at the old folder the move empties and
    prunes, while the log said what it points at was not touched. It stops the start before
    anything moves, names where its target is going, and still points where it did."""
    _a_library(r)
    write(r.lib / "loom" / "kv" / KEY_NEL / BOARD, {"b": 1})
    write(r.lib / "loom" / "exports" / "2026-10" / "cut.mp4", b"VIDEO")
    _junction(r.lib / "loom" / "exports" / "latest", r.lib / "loom" / "exports" / "2026-10")
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    text = str(e.value)
    assert "latest is a link" in text and "points by its full path" in text
    assert os.path.join("_moonglade", "loom", "exports", "2026-10") in text, "where it goes"
    assert "Delete the link itself" in text
    assert (r.lib / "jobs.jsonl").is_file() and (r.lib / "loom" / "kv").is_dir(), \
        "nothing moved before the stop"
    assert (r.lib / "loom" / "exports" / "latest" / "cut.mp4").read_bytes() == b"VIDEO"


def test_a_junction_into_a_folder_the_move_empties_stops_before_anything_moves(r):
    """A junction into a login store, whose files go one by one into each login's own folder,
    has no one new place to point at: it stops the start before anything moves."""
    _a_library(r)
    write(r.lib / "account_prefs" / (KEY_NEL + ".json"), {"guide": "done"})
    write(r.lib / "loom" / "kv" / KEY_NEL / BOARD, {"b": 1})
    _junction(r.lib / "loom" / "exports" / "prefs", r.lib / "account_prefs")
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    text = str(e.value)
    assert "prefs is a link" in text and "points by its full path" in text
    assert "which the move empties" in text
    assert (r.lib / "account_prefs" / (KEY_NEL + ".json")).is_file()
    assert (r.lib / "jobs.jsonl").is_file()


def test_a_relative_link_to_a_folder_the_move_empties_stops_before_anything_moves(
        r, monkeypatch):
    """A relative link into a folder whose files go one by one to other homes (a login store)
    can't be pointed at its new place: it stops the start, before anything moves, and says
    why."""
    _a_library(r)
    write(r.lib / "account_prefs" / (KEY_NEL + ".json"), {"guide": "done"})
    write(r.lib / "loom" / "kv" / KEY_NEL / BOARD, {"b": 1})
    link = _junction(r.lib / "loom" / "exports" / "prefs", r.lib / "account_prefs")
    _pretend_relative(monkeypatch, link, os.path.join("..", "..", "account_prefs"))
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    text = str(e.value)
    assert "prefs is a link" in text and "which the move empties" in text
    assert (r.lib / "jobs.jsonl").is_file() and (r.lib / "loom" / "kv").is_dir()


def test_a_start_cut_short_after_the_links_moved_finishes_without_a_stop(r, monkeypatch):
    """#10: links move before any file, so a start cut short never leaves a link whose target's
    files have already gone: the next start plans the files alone and finishes. (Planned the
    other way round, the resumed start saw an emptied folder and stopped, or remade the link
    pointing at the folder the move then pruned.) loom\\exports\\latest -> 2026-10 reports a
    relative target here; test_move_symlinks.py follows a real one to its file."""
    _a_library(r)
    write(r.lib / "loom" / "kv" / KEY_NEL / BOARD, {"b": 1})
    write(r.lib / "loom" / "exports" / "2026-10" / "cut.mp4", b"VIDEO")
    link = _junction(r.lib / "loom" / "exports" / "latest",
                     r.lib / "loom" / "exports" / "2026-10")
    _pretend_relative(monkeypatch, link, "2026-10")
    real = migrate._bring

    def die_at_the_first_file(src, dest, kind, half, vouched=False):
        if kind != "link" and not migrate._is_link(src):
            raise migrate._Failed("cut short")
        return real(src, dest, kind, half, vouched=vouched)
    monkeypatch.setattr(migrate, "_bring", die_at_the_first_file)
    with pytest.raises(msetup.MoveStopped):
        start(r)
    new = r.lib / "_moonglade" / "loom" / "exports"
    assert migrate._is_link(new / "latest"), "the link moved first"
    assert (r.lib / "loom" / "exports" / "2026-10" / "cut.mp4").is_file(), "no file yet"
    monkeypatch.setattr(migrate, "_bring", real)
    done = start(r)
    assert (new / "2026-10" / "cut.mp4").read_bytes() == b"VIDEO"
    assert migrate._is_link(new / "latest")
    assert not os.path.lexists(r.lib / "loom")
    said = " ".join(line for _lvl, line in done.report.all_lines())
    assert "is a link" not in said


# ---- the install half checks its links before the settings merge (round 2, #10) ----------------

def test_a_linked_mirror_sign_in_whose_home_is_taken_stops_before_the_settings_merge(r):
    """A link in the install half that can't move as a link stops the start before step 1:
    serve.txt and branding.json are still there, untouched, for the next start."""
    write_config(r)
    write(r.app / "serve.txt", "--port 5757\n")
    write(r.app / "branding.json", {"mark": "mark_2"})
    write(r.local / "mirror_session.json", {"jwt": "already here"})
    _junction(r.app / "mirror_session.json", _elsewhere(r, "session"))
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare("cli")
    assert "mirror_session.json is a link" in str(e.value) and "already taken" in str(e.value)
    assert (r.app / "serve.txt").read_text() == "--port 5757\n"
    assert (r.app / "branding.json").is_file()
    assert migrate._is_link(r.app / "mirror_session.json")


def test_a_linked_mirror_sign_in_beside_a_real_one_stops_before_the_settings_merge(
        r, monkeypatch):
    """#11: with config.json found in another folder (the working directory), the Mirror's
    sign-in has two old places, both going to local\\mirror_session.json. A real one in one and
    a link in the other: the link could only arrive after the real one took its home, so it
    stops the start before step 1 -- serve.txt is still there and settings.json unwritten."""
    from moonglade import backup as core
    from moonglade import paths
    here = r.app.parent / "where-it-was-run"
    write(here / "config.json", {"PIXAI_API_KEY": "sk-test-not-real", "AUTH_SECRET_KEY": "s",
                                 "AUTH_USERS": [{"username": "Nel", "password_hash": "x"}]})
    monkeypatch.setattr(paths, "config_path", lambda: here / "config.json")
    monkeypatch.setattr(core, "_config_path", lambda: here / "config.json")
    write(r.app / "serve.txt", "--port 5757\n")
    write(here / "mirror_session.json", {"jwt": "the live one"})
    _junction(r.app / "mirror_session.json", _elsewhere(r, "session"))
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare("cli")
    text = str(e.value)
    assert "mirror_session.json is a link" in text and "goes to that place too" in text
    assert (r.app / "serve.txt").read_text() == "--port 5757\n", "step 1 never ran"
    assert not (r.local / "settings.json").exists()
    assert json.loads((here / "mirror_session.json").read_text()) == {"jwt": "the live one"}
    assert migrate._is_link(r.app / "mirror_session.json")


def test_a_linked_launcher_log_is_left_where_it_is_and_never_stops_a_start(r):
    write_config(r)
    write(r.app / "serve.txt", "--port 5757\n")
    write(r.local / "logs" / "serve.log", "the new log\n")
    target = _elsewhere(r, "serve-log")
    _junction(r.app / "serve.log", target)
    msetup.prepare("cli")
    assert not (r.app / "serve.txt").exists(), "the settings merge ran"
    assert migrate._is_link(r.app / "serve.log") and target.is_dir()
    assert msetup.prepare("cli").report.worked["install"] is False, "not work at every start"


# ---- links the plan used to miss (round 2, #11) --------------------------------------------------

def test_a_linked_record_sharing_its_home_with_another_copy_stops_before_anything_moves(r):
    """3.20's copy-first _moonglade\\jobs.jsonl and a linked <library>\\jobs.jsonl both go to
    one home: the link could only arrive after the other took it, so the start stops first."""
    write_config(r)
    library_records(r.lib)
    (r.lib / "jobs.jsonl").unlink()
    write(r.lib / "_moonglade" / "jobs.jsonl", '{"id": "copy-first"}\n')
    _junction(r.lib / "jobs.jsonl", _elsewhere(r, "jobs"))
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "jobs.jsonl is a link" in str(e.value) and "goes to that place too" in str(e.value)
    assert (r.lib / "_moonglade" / "jobs.jsonl").is_file(), "the other copy didn't move either"
    assert (r.lib / "achievements.json").is_file()


def test_a_dead_branding_link_on_another_drive_from_the_safety_copy_is_removed_in_place(
        r, monkeypatch):
    """A link in the library's dead branding\\ is set aside by renaming it beside the safety
    copy; where that is on another drive it can't be renamed there, so the link entry alone is
    removed where it is -- what it points at is never touched -- and the start goes on."""
    _a_library(r)
    art = _elsewhere(r, "art")
    write(art / "marks" / "mark_2.png", b"PNG")
    write(r.lib / "branding" / "logo.png", b"LOGO")
    link = _junction(r.lib / "branding" / "marks", art / "marks")
    real = migrate._same_device
    monkeypatch.setattr(migrate, "_same_device",
                        lambda src, dest: False if os.path.normcase(str(src)) ==
                        os.path.normcase(str(link)) else real(src, dest))
    done = start(r)
    assert not os.path.lexists(r.lib / "branding")
    parked = r.lib / "_moonglade" / ".snapshot" / "parked" / "branding"
    assert not os.path.lexists(parked / "marks")
    assert (parked / "logo.png").read_bytes() == b"LOGO"
    assert (art / "marks" / "mark_2.png").read_bytes() == b"PNG"
    said = " ".join(line for _lvl, line in done.report.all_lines())
    assert "Removed the link branding/marks" in said
    [summary] = [line for _lvl, line in done.report.lines
                 if line.startswith("Set aside the library's old branding folder")]
    assert "branding/logo.png" in summary
    assert "branding/marks" not in summary, "#13: only what was really set aside is named"
