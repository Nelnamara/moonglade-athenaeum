"""moonglade.setup.prepare(kind): the first thing every entry point runs (B2, S8).

  * ORDER. The web server, the command line and the MCP server call prepare() before anything
    reads a setting: on the first start after an update the library, host and port must come
    from the merged settings -- not the defaults an empty settings.json would give (the
    server used to read its port and library before any migration ran).
  * ONE LIBRARY. Each entry point opens the library settings.json names, unless the run names
    its own (--out, MOONGLADE_OUT). Only the launcher and the server move a library's files,
    and only that one (X1): the command line and the MCP server refuse a library still in an
    older layout.
  * A SECOND SERVER BOWS OUT FIRST (S1): the port is checked before the move, from the
    settings as the move will leave them.
  * A STOP IS A STOP. A move that cannot finish (a lock held past its wait) ends the start
    with its plain sentence; the server returns 3 (the sentence behind PREPARE_MARK, which the
    launcher shows) and the command line exits.
  * THE CLEAN-START COUNT (S1): a server counts its start once it has served a while or was
    stopped cleanly, never at prepare().
  * AN UNREADABLE settings.json (S4) stops every start with a sentence: never the default
    library, never a write over it.

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
    bound, early = {}, {}

    def port_owner(host, port):
        if not early:                          # the check before the move: nothing there
            early.update(host=host, port=port)
            order.append(("port", None))
            return ""
        bound.update(host=host, port=port)
        return "other"                         # refuse here: nothing below matters
    monkeypatch.setattr(msetup, "prepare", prepare)
    monkeypatch.setattr(g, "resolve_server_settings", server)
    monkeypatch.setattr(mlog, "setup_logging", logging_up)
    monkeypatch.setattr(g, "port_owner", port_owner)
    monkeypatch.setattr(sys, "argv", ["python -m moonglade.gallery"])
    assert g.main() == 2
    assert order[:2] == [("port", None), ("prepare", "server")]
    assert early["port"] == 5757, "the port before the move is the one the merge will keep"
    assert order.index(("settings", None)) > 1 and order.index(("logging", None)) > 1
    assert bound["port"] == 5757
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file(), "the library half ran"
    assert (r.lib / "catalog.db").is_file(), "and the server opened the merged library"
    assert not (r.app / "pixai_backup").exists(), "never the default it would have guessed"
    assert settings.launch_args() == ["--skip-thumbs"]


def _refused_after_the_move():
    """port_owner for a test that stops main() at the bind-time check: free before the move,
    taken after it."""
    calls = []

    def port_owner(host, port):
        calls.append(port)
        return "" if len(calls) == 1 else "other"
    return port_owner


def test_the_server_applies_the_stored_launch_switches(r, monkeypatch):
    write_config(r)
    settings.set_values(launch_args=["--skip-thumbs"], port=5199)
    seen = {}
    monkeypatch.setattr(g, "build_thumbnails",
                        lambda *a, **k: seen.setdefault("built", True))
    monkeypatch.setattr(g, "port_owner", _refused_after_the_move())
    monkeypatch.setattr(sys, "argv", ["python -m moonglade.gallery"])
    assert g.main() == 2
    assert "built" not in seen, "--skip-thumbs from settings.json applied"


def test_an_explicit_out_wins_for_the_server(r, monkeypatch):
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    other = r.lib.parent / "one-off"
    monkeypatch.setattr(g, "port_owner", _refused_after_the_move())
    monkeypatch.setattr(sys, "argv", ["x", "--out", str(other)])
    assert g.main() == 2
    assert (other / "catalog.db").is_file() and settings.library_dir() == str(r.lib)


def test_a_busy_move_stops_the_server_with_its_sentence(r, monkeypatch, capsys):
    import os
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.2)
    monkeypatch.setattr(g, "port_owner", lambda host, port: "")
    r.local.mkdir(parents=True)
    (r.local / ".lock").write_text(str(os.getppid()), encoding="ascii")
    monkeypatch.setattr(sys, "argv", ["x"])
    assert g.main() == 3
    err = capsys.readouterr().err
    assert g.PREPARE_MARK + "Another Moonglade start is still tidying" in err, \
        "the launcher finds the sentence behind its mark (S10)"


def test_a_second_server_bows_out_before_the_move(r, monkeypatch):
    """S1: a server started while another answers on its port moves nothing."""
    write_config(r)
    settings.set_values(library_dir=str(r.lib), port=5222)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    ran = []
    monkeypatch.setattr(msetup, "prepare", lambda *a, **k: ran.append(1))
    monkeypatch.setattr(g, "port_owner", lambda host, port: "moonglade" if port == 5222 else "")
    monkeypatch.setattr(sys, "argv", ["x"])
    assert g.main() == 2
    assert ran == [] and (r.lib / "jobs.jsonl").is_file()


class _Served:
    """werkzeug's make_server, stood in for: binds nothing, and serve_forever returns at once
    as a Control Panel Stop would make it."""

    def __init__(self, *a, **k):
        pass

    def serve_forever(self):
        return None

    def shutdown(self):
        pass

    def server_close(self):
        pass


def test_a_server_stopped_cleanly_counts_its_start_and_prepare_alone_never_does(
        r, monkeypatch):
    """S1: the count is the server's, after it served: prepare() never counts (a server that
    refused its port has run it too)."""
    import werkzeug.serving
    write_config(r)
    settings.set_values(library_dir=str(r.lib), launch_args=["--skip-thumbs"], port=5223)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    counted = []
    real = msetup.Prepared.count_clean_start

    def count(self):
        counted.append(self.kind)
        return real(self)
    monkeypatch.setattr(msetup.Prepared, "count_clean_start", count)
    monkeypatch.setattr(g, "port_owner", _refused_after_the_move())
    monkeypatch.setattr(sys, "argv", ["x"])
    assert g.main() == 2
    assert counted == [], "refused at its port: not a clean start"
    monkeypatch.setattr(g, "port_owner", lambda host, port: "")
    monkeypatch.setattr(werkzeug.serving, "make_server", _Served)
    monkeypatch.setattr(g, "_health_prime", lambda *a, **k: None)
    monkeypatch.setattr(g, "_outside_prime", lambda *a, **k: None)
    monkeypatch.setattr(g, "register_pack_file_type", lambda *a, **k: None)
    assert g.main() == 0
    assert counted == ["server"]
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert journal["skip_next"] is False, "the start after the move was the one not counted"


def test_the_server_counts_only_after_it_has_served_a_while():
    """Read off main(): a timer of CLEAN_SERVE_S after the bind, and a Stop (exit 0) -- never
    a Restart (42) on its own."""
    import inspect
    src = inspect.getsource(g.main)
    assert src.index("_make_server(") < src.index("CLEAN_SERVE_S") < src.index(
        "srv.serve_forever()")
    assert 'get("exit_code", 0) == 0' in src
    assert g.CLEAN_SERVE_S >= 300


def test_an_unreadable_settings_file_stops_every_start(r, monkeypatch, capsys):
    """S4: never the default library, never a write over the person's settings."""
    write_config(r)
    r.local.mkdir(parents=True, exist_ok=True)
    (r.local / "settings.json").write_text('{"library_dir": "D:\\lib", ', encoding="utf-8")
    for kind in msetup.KINDS:
        with pytest.raises(msetup.MoveStopped) as e:
            msetup.prepare(kind)
        assert "settings file" in str(e.value) and "damaged" in str(e.value)
    assert (r.local / "settings.json").read_text(encoding="utf-8") == \
        '{"library_dir": "D:\\lib", '
    monkeypatch.setattr(g, "port_owner", lambda host, port: "")
    monkeypatch.setattr(sys, "argv", ["x"])
    assert g.main() == 3
    assert not (r.app / "pixai_backup").exists(), "the default library was never opened"


def test_a_settings_file_written_with_a_byte_order_mark_reads(r):
    write_config(r)
    r.local.mkdir(parents=True, exist_ok=True)
    (r.local / "settings.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"library_dir": str(r.lib), "port": 5151}).encode())
    done = msetup.prepare("cli")
    assert done.library == r.lib and settings.server()["port"] == 5151


def test_the_command_line_prepares_first_and_opens_the_settings_library(r, monkeypatch):
    """S8: with no --out the command line opens the library the Control Panel set. It brings
    an older install's settings across (the install half runs for every kind)."""
    write_config(r, LIBRARY_DIR=str(r.lib))
    write(r.app / "serve.txt", "--port 5300\n")
    seen = {}
    monkeypatch.setattr(core, "run_list_web_users", lambda args: seen.update(out=args.out))
    monkeypatch.setattr(sys, "argv", ["moonglade", "--list-web-users"])
    core.main()
    assert seen["out"] == str(r.lib)
    assert settings.server()["port"] == 5300 and "LIBRARY_DIR" not in read_config(r)


def test_the_command_line_refuses_a_library_still_in_an_older_layout(r, monkeypatch):
    """X1: it never moves a library's files (an older install may be serving it), so it says
    plainly what to do instead, and stops."""
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    monkeypatch.setattr(sys, "argv", ["moonglade", "--list-web-users"])
    with pytest.raises(SystemExit) as e:
        core.main()
    assert "older Moonglade's layout" in str(e.value.code)
    assert (r.lib / "jobs.jsonl").is_file() and not (r.lib / "_moonglade").exists()


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
    assert not (other / "_moonglade").exists(), "a run naming its library changes nothing in it"


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
    ran = []
    monkeypatch.setattr(m.mcp, "run", lambda transport=None: ran.append(transport))
    monkeypatch.delenv("MOONGLADE_OUT", raising=False)
    monkeypatch.setattr(m, "OUT", None)
    monkeypatch.setattr(m, "DB", None)
    assert m.main() == 0
    assert ran == ["stdio"] and m.OUT == r.lib and m.DB == str(r.lib / "catalog.db")
    other = r.lib.parent / "env-library"
    other.mkdir()
    monkeypatch.setenv("MOONGLADE_OUT", str(other))
    assert m.main() == 0 and m.OUT == other, "MOONGLADE_OUT names one for this server alone"


def test_the_mcp_server_never_logs_to_stdout(r, monkeypatch):
    """#13: the MCP server's stdout is its JSON-RPC channel to Claude. Its logging must have no
    handler on stdout -- a warning (the move's own, the catalog's 'migration deferred', a
    thread's crash) would land in the client's stream as a line that isn't JSON."""
    pytest.importorskip("fastmcp")
    import io
    import logging
    from moonglade import mcp_server as m
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    write(r.app / "_container_cache" / "marks" / "x.ico", b"ICO")   # a move with lines to log
    channel = io.StringIO()
    monkeypatch.setattr(sys, "stdout", channel)
    monkeypatch.setattr(m.mcp, "run", lambda transport=None: None)
    monkeypatch.delenv("MOONGLADE_OUT", raising=False)
    monkeypatch.setattr(m, "OUT", None)
    monkeypatch.setattr(m, "DB", None)
    mlog._reset_for_tests()
    assert m.main() == 0
    on_stdout = [h for h in logging.getLogger().handlers
                 if isinstance(h, logging.StreamHandler)
                 and getattr(h, "stream", None) in (channel, sys.__stdout__)]
    assert on_stdout == [], "a root-logger handler writes to the MCP's stdout"
    logging.getLogger("moonglade.gallery").warning("migration deferred: locked")
    logging.getLogger("some.library").error("a third-party error")
    assert channel.getvalue() == ""


def test_the_mcp_server_never_moves_another_install_s_library(r, monkeypatch, capsys):
    """X1: C:'s Claude tools registered with MOONGLADE_OUT on D:'s live 3.17 library. The MCP
    server must not move D:'s records (its spend guard among them) out from under it."""
    pytest.importorskip("fastmcp")
    from moonglade import mcp_server as m
    write_config(r)
    d_lib = r.lib.parent / "d-library"
    write(d_lib / "train_guard.json", {"basic": {"k": {"at": 1.0}}, "retried": {}, "paid": {}})
    write(d_lib / "jobs.jsonl", '{"id": 1}\n')
    ran = []
    monkeypatch.setattr(m.mcp, "run", lambda transport=None: ran.append(transport))
    monkeypatch.setenv("MOONGLADE_OUT", str(d_lib))
    assert m.main() == 3 and ran == []
    assert "older Moonglade's layout" in capsys.readouterr().err
    assert (d_lib / "train_guard.json").is_file() and not (d_lib / "_moonglade").exists()


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
