"""Symbolic links in an old home, as `ln -s` makes them on Linux and macOS (and `mklink` on
Windows): their target is often written RELATIVE to the folder the link sits in. Every new
home is deeper than the old place (loom\\ -> _moonglade\\loom\\, a login's file ->
_moonglade\\accounts\\<key>\\), so a link renamed as it is would point somewhere else, or at
nothing, while the log said it was moved.

  * Off Windows the link is made again at its new home with its target rewritten -- still
    relative -- so it points at the same place, and the old entry is removed. A full-path
    target is renamed as it is. What a link points at is never copied, moved or deleted.
  * On Windows, where making a link needs a privilege, a relative one stops the start before
    anything moves, with a plain sentence (dev/tests/test_move_links.py covers that path on
    any Windows machine; the real-link test here runs where links can be made).
  * A banner render that is a link is left where it is, with its folder: it may be the only
    copy of the banner the install wears, and would have to be read through the link.

These are NOT Windows-only: the POSIX ones run on Linux CI. A test that needs to make a
symbolic link skips where this user can't (Windows without the privilege).
"""
import json
import os
import sys

import pytest

from moonglade import migrate
from moonglade import setup as msetup
from tests.move_layouts import KEY_NEL, rig, start, write, write_config

BOARD = "storyboard%3Av2%3Aproj%3Ab1.json"

posix = pytest.mark.skipif(sys.platform == "win32",
                           reason="off Windows a relative link is made again, rewritten")
windows = pytest.mark.skipif(sys.platform != "win32",
                             reason="on Windows a relative link stops the start")


def _can_symlink(folder):
    probe = os.path.join(str(folder), ".probe-link")
    try:
        os.symlink("nowhere", probe)
    except (OSError, NotImplementedError, AttributeError):
        return False
    os.unlink(probe)
    return True


@pytest.fixture
def r(tmp_path, monkeypatch):
    if not _can_symlink(tmp_path):
        pytest.skip("this user can't make a symbolic link here (Windows without the privilege)")
    return rig(tmp_path, monkeypatch)


def _a_library(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')


def _same_place(a, b):
    return os.path.realpath(str(a)) == os.path.realpath(str(b))


# ---- the arithmetic, on every platform -----------------------------------------------------------

def test_a_relative_target_is_rewritten_for_the_deeper_folder(tmp_path):
    lib = tmp_path / "Lib"
    up = os.path.join("..", "LoomData")
    got = migrate._relinked(str(lib), up, str(lib / "_moonglade"))
    assert got == os.path.join("..", "..", "LoomData")
    assert os.path.normpath(os.path.join(str(lib / "_moonglade"), got)) == \
        os.path.normpath(str(tmp_path / "LoomData"))
    beside = migrate._relinked(str(lib), "LoomData", str(lib / "_moonglade"))
    assert os.path.normpath(os.path.join(str(lib / "_moonglade"), beside)) == \
        os.path.normpath(str(lib / "LoomData"))


def test_a_full_path_or_an_unchanged_target_is_left_as_it_is(tmp_path):
    lib = tmp_path / "Lib"
    assert migrate._relinked(str(lib), str(tmp_path / "LoomData"),
                             str(lib / "_moonglade")) is None
    assert migrate._relinked(str(lib), os.path.join("..", "x"), str(tmp_path / "Other")) is None
    assert migrate._relinked(str(lib), "", str(lib / "_moonglade")) is None


def test_a_junction_s_target_is_named_without_the_windows_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "readlink", lambda p: "\\\\?\\C:\\Users\\me\\LoomData")
    assert migrate._link_target(tmp_path) == "C:\\Users\\me\\LoomData"
    monkeypatch.setattr(os, "readlink", lambda p: "\\\\?\\UNC\\nas\\share\\LoomData")
    assert migrate._link_target(tmp_path) == "\\\\nas\\share\\LoomData"
    monkeypatch.setattr(os, "readlink", lambda p: "../LoomData")
    assert migrate._link_target(tmp_path) == "../LoomData"


# ---- real links ----------------------------------------------------------------------------------

@posix
def test_relative_and_full_path_links_still_point_where_they_did_after_the_move(r):
    _a_library(r)
    loom_data = r.lib.parent / "LoomData"
    write(loom_data / "kv" / KEY_NEL / BOARD, json.dumps(json.dumps({"name": "beside"})))
    os.symlink(os.path.join("..", "LoomData"), str(r.lib / "loom"))          # a folder, relative
    snips = write(r.lib.parent / "elsewhere" / "snips.json", ["golden hour"])
    (r.lib / "prompt_snippets").mkdir()
    os.symlink(os.path.join("..", "..", "elsewhere", "snips.json"),
               str(r.lib / "prompt_snippets" / (KEY_NEL + ".json")))          # a file, relative
    prefs = write(r.lib.parent / "elsewhere" / "prefs.json", {"guide": "done"})
    (r.lib / "account_prefs").mkdir()
    os.symlink(str(prefs), str(r.lib / "account_prefs" / (KEY_NEL + ".json")))  # a full path
    done = start(r)

    loom = r.lib / "_moonglade" / "loom"
    assert os.path.islink(str(loom)) and not os.path.isabs(os.readlink(str(loom))), \
        "made again, still relative"
    assert _same_place(loom, loom_data)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    assert os.path.islink(str(acc / "snippets.json"))
    assert not os.path.isabs(os.readlink(str(acc / "snippets.json")))
    assert _same_place(acc / "snippets.json", snips)
    assert json.loads((acc / "snippets.json").read_text()) == ["golden hour"]
    assert os.readlink(str(acc / "prefs.json")) == str(prefs), "a full path is renamed as is"
    for old in (r.lib / "loom", r.lib / "prompt_snippets", r.lib / "account_prefs"):
        assert not os.path.lexists(str(old))
    assert json.loads(snips.read_text()) == ["golden hour"], "what it points at is untouched"
    from moonglade import gallery as g
    assert [p.name for p in g._loom_board_files(r.lib)] == [BOARD], "the Loom reads through it"
    said = " ".join(line for _lvl, line in done.report.all_lines())
    assert "its target written as" in said


@posix
def test_a_link_made_again_but_cut_short_before_the_old_one_went_is_finished(r, monkeypatch):
    """The start dies between making the link at its new home and removing the old entry:
    the next start finds both, sees the new one holds the target it journalled, removes the
    old one, and goes on."""
    _a_library(r)
    loom_data = r.lib.parent / "LoomData"
    write(loom_data / "kv" / KEY_NEL / BOARD, json.dumps(json.dumps({"name": "beside"})))
    old = r.lib / "loom"
    os.symlink(os.path.join("..", "LoomData"), str(old))
    real = migrate._unlink_link

    def refuse_the_old_link(p):
        if os.path.normpath(str(p)) == os.path.normpath(str(old)):
            raise PermissionError(13, "refused")
        return real(p)
    monkeypatch.setattr(migrate, "_unlink_link", refuse_the_old_link)
    with pytest.raises(msetup.MoveStopped):
        start(r)
    assert os.path.islink(str(old)) and os.path.islink(str(r.lib / "_moonglade" / "loom"))
    monkeypatch.setattr(migrate, "_unlink_link", real)
    start(r)
    assert not os.path.lexists(str(old))
    assert _same_place(r.lib / "_moonglade" / "loom", loom_data)


@windows
def test_a_real_relative_symbolic_link_stops_the_start_on_windows(r):
    _a_library(r)
    loom_data = r.lib.parent / "LoomData"
    write(loom_data / "kv" / KEY_NEL / BOARD, json.dumps(json.dumps({"name": "beside"})))
    os.symlink("..\\LoomData", str(r.lib / "loom"), target_is_directory=True)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "written from where it sits (..\\LoomData)" in str(e.value)
    assert (r.lib / "jobs.jsonl").is_file(), "nothing moved before the stop"
    assert os.path.islink(str(r.lib / "loom"))


def test_a_banner_render_that_is_a_link_is_left_where_it_is(r):
    """An unrecorded banner render is the only copy of what the install wears, and moves into
    local\\banners\\ -- on another drive for a library away from the program, where a link
    can't be renamed. One that is a link is left where it is, with its folder, and said."""
    _a_library(r)
    art = write(r.lib.parent / "art" / "my-banner.png", b"PNG-ONLY-COPY")
    banners = r.lib / "gallery" / "cache" / "_banners"
    banners.mkdir(parents=True)
    os.symlink(str(art), str(banners / "banner.png"))
    done = start(r)
    assert os.path.islink(str(banners / "banner.png"))
    assert art.read_bytes() == b"PNG-ONLY-COPY"
    assert not (r.local / "banners" / "banner.png").exists()
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file(), "the rest moved"
    said = " ".join(line for _lvl, line in done.report.all_lines())
    assert "_banners" in said and "Left" in said
