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
