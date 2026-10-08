"""moonglade.setup.prepare(kind): the first thing every entry point runs (B2, S8).

  * ORDER. The web server, the command line and the MCP server call prepare() before anything
    reads a setting: on the first start after an update the library, host and port must come
    from the merged settings -- not the defaults an empty settings.json would give (the
    server used to read its port and library before any migration ran).
  * ONE LIBRARY. Each entry point opens the library settings.json names, unless the run names
    its own (--out, MOONGLADE_OUT).
  * A STOP IS A STOP. A move that cannot finish (a lock held past its wait) ends the start
    with its plain sentence; the server returns 3 and the command line exits.

Every install here is the test's own (dev/tests/move_layouts.py rig()).
"""
import json
import sys

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import logs as mlog
from moonglade import migrate
from moonglade import paths
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import read_config, rig, write, write_config


@pytest.fixture
def r(tmp_path, monkeypatch):
    out = rig(tmp_path, monkeypatch)
    yield out
    mlog._reset_for_tests()


def test_prepare_knows_its_kinds(r):
    with pytest.raises(ValueError):
        msetup.prepare("desktop")
    for kind in msetup.KINDS:
        assert msetup.prepare(kind).library == r.app / "pixai_backup"


def test_the_server_s_first_start_reads_the_merged_settings(r, monkeypatch):
    """The B2 trap, end to end: serve.txt pinned port 5757 and config.json named the library.
    The first start after the update must bind 5757 and open that library -- and run the move
    before it reads either one."""
    write_config(r, LIBRARY_DIR=str(r.lib))
    write(r.app / "serve.txt", "--port 5757 --skip-thumbs\n")
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    order = []
    real_prepare, real_server, real_logging = (msetup.prepare, g.resolve_server_settings,
                                               mlog.setup_logging)

    def prepare(kind, explicit_out=None):
        order.append(("prepare", kind))
        return real_prepare(kind, explicit_out=explicit_out)

    def server(*a):
        order.append(("settings", None))
        return real_server(*a)

    def logging_up(**kw):
        order.append(("logging", None))
        return real_logging(**kw)
    bound = {}

    def port_owner(host, port):
        bound.update(host=host, port=port)
        return "other"                         # refuse here: nothing below matters
    monkeypatch.setattr(msetup, "prepare", prepare)
    monkeypatch.setattr(g, "resolve_server_settings", server)
    monkeypatch.setattr(mlog, "setup_logging", logging_up)
    monkeypatch.setattr(g, "port_owner", port_owner)
    monkeypatch.setattr(sys, "argv", ["python -m moonglade.gallery"])
    assert g.main() == 2
    assert order[0] == ("prepare", "server")
    assert order.index(("settings", None)) > 0 and order.index(("logging", None)) > 0
    assert bound["port"] == 5757
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file(), "the library half ran"
    assert (r.lib / "catalog.db").is_file(), "and the server opened the merged library"
    assert not (r.app / "pixai_backup").exists(), "never the default it would have guessed"
    assert settings.launch_args() == ["--skip-thumbs"]


def test_the_server_applies_the_stored_launch_switches(r, monkeypatch):
    write_config(r)
    settings.set_values(launch_args=["--skip-thumbs"], port=5199)
    seen = {}
    monkeypatch.setattr(g, "build_thumbnails",
                        lambda *a, **k: seen.setdefault("built", True))
    monkeypatch.setattr(g, "port_owner", lambda host, port: "other")
    monkeypatch.setattr(sys, "argv", ["python -m moonglade.gallery"])
    assert g.main() == 2
    assert "built" not in seen, "--skip-thumbs from settings.json applied"


def test_an_explicit_out_wins_for_the_server(r, monkeypatch):
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    other = r.lib.parent / "one-off"
    monkeypatch.setattr(g, "port_owner", lambda host, port: "other")
    monkeypatch.setattr(sys, "argv", ["x", "--out", str(other)])
    assert g.main() == 2
    assert (other / "catalog.db").is_file() and settings.library_dir() == str(r.lib)


def test_a_busy_move_stops_the_server_with_its_sentence(r, monkeypatch, capsys):
    import os
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.2)
    r.local.mkdir(parents=True)
    (r.local / ".lock").write_text(str(os.getppid()), encoding="ascii")
    monkeypatch.setattr(sys, "argv", ["x"])
    assert g.main() == 3
    assert "Another Moonglade start is still tidying" in capsys.readouterr().err


def test_the_command_line_prepares_first_and_opens_the_settings_library(r, monkeypatch):
    """S8: with no --out the command line opens the library the Control Panel set."""
    write_config(r, LIBRARY_DIR=str(r.lib))
    write(r.app / "serve.txt", "--port 5300\n")
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    seen = {}
    monkeypatch.setattr(core, "run_list_web_users", lambda args: seen.update(out=args.out))
    monkeypatch.setattr(sys, "argv", ["moonglade", "--list-web-users"])
    core.main()
    assert seen["out"] == str(r.lib)
    assert settings.server()["port"] == 5300 and "LIBRARY_DIR" not in read_config(r)
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file()


def test_the_command_line_s_out_wins(r, monkeypatch):
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    other = r.lib.parent / "elsewhere"
    other.mkdir()
    seen = {}
    monkeypatch.setattr(core, "run_list_web_users", lambda args: seen.update(out=args.out))
    monkeypatch.setattr(sys, "argv", ["moonglade", "--out", str(other), "--list-web-users"])
    core.main()
    assert seen["out"] == str(other)
    assert (other / "_moonglade" / ".journal.json").is_file(), "its library half ran"


def test_a_busy_move_stops_the_command_line(r, monkeypatch):
    import os
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.2)
    r.local.mkdir(parents=True)
    (r.local / ".lock").write_text(str(os.getppid()), encoding="ascii")
    monkeypatch.setattr(sys, "argv", ["moonglade", "--list-web-users"])
    with pytest.raises(SystemExit) as e:
        core.main()
    assert "Another Moonglade start is still tidying" in str(e.value.code)


def test_the_command_line_s_remove_web_user_removes_the_login_s_folder(r, monkeypatch):
    write_config(r, AUTH_USERS=[{"username": "Nel", "password_hash": "x"},
                                {"username": "Guest", "password_hash": "y"}])
    settings.set_values(library_dir=str(r.lib))
    folder = paths.account_dir(r.lib, "Guest")
    write(folder / "prefs.json", {"x": 1})
    monkeypatch.setattr(sys, "argv", ["moonglade", "--remove-web-user", "Guest"])
    core.main()
    assert not folder.exists()
    assert paths.account_dir(r.lib, "Nel").parent.is_dir()


def test_the_mcp_server_prepares_and_binds_the_settings_library(r, monkeypatch):
    pytest.importorskip("fastmcp")
    from moonglade import mcp_server as m
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    ran = []
    monkeypatch.setattr(m.mcp, "run", lambda transport=None: ran.append(transport))
    monkeypatch.delenv("MOONGLADE_OUT", raising=False)
    monkeypatch.setattr(m, "OUT", None)
    monkeypatch.setattr(m, "DB", None)
    assert m.main() == 0
    assert ran == ["stdio"] and m.OUT == r.lib and m.DB == str(r.lib / "catalog.db")
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file()
    other = r.lib.parent / "env-library"
    other.mkdir()
    monkeypatch.setenv("MOONGLADE_OUT", str(other))
    assert m.main() == 0 and m.OUT == other, "MOONGLADE_OUT names one for this server alone"


def test_every_entry_point_calls_prepare_before_it_reads_a_setting():
    """Read off the source: in each entry point the prepare() call comes before the first
    read of the library, host, port or logging."""
    import inspect
    from moonglade import gallery, backup
    for fn, reads in ((gallery.main, ("resolve_server_settings(", "setup_logging(",
                                      "resolve_library_dir(", "_settings.")),
                      (backup.main, ("setup_logging(", "Path(args.out)"))):
        src = inspect.getsource(fn)
        at = src.index("prepare(")
        for word in reads:
            if word in src:
                assert src.index(word) > at, (fn.__module__, word)
