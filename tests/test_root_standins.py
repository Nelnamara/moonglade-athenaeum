"""The root stand-ins (3.20, "the move"): the three old entry scripts keep working for one
release, each by running its module in the moonglade/ package as the main module.

  moonglade_gallery.py  MANDATORY. A launcher that was already running when the install
                        updated relaunches this exact path after the update's restart (exit
                        code 42); without it the app stops. It sets MOONGLADE_VIA_STANDIN=1.
  moonglade_backup.py   old habits, Task Scheduler entries, old docs. One line on stderr.
  moonglade_mcp.py      the existing MCP registrations name this path. Silent: an MCP
                        server's stdout is the protocol.

Each is run here the way its caller runs it: by path, in a fresh interpreter. Arguments and
exit codes pass straight through.
"""
import ast
import os
import runpy
import subprocess
import sys
import textwrap

import pytest

from moonglade import backup as core
from tests.conftest import REPO_ROOT

_STANDINS = ("moonglade_gallery.py", "moonglade_backup.py", "moonglade_mcp.py")
_NOTICE = ("moonglade_backup.py moved: run `python -m moonglade ...` instead; "
           "this stand-in goes in the next release")


def _env(**extra):
    env = dict(os.environ)
    env.pop("MOONGLADE_VIA_STANDIN", None)
    env.update(extra)
    return env


def _run(script, *args, cwd=REPO_ROOT, **env):
    return subprocess.run([sys.executable, str(REPO_ROOT / script)] + list(args),
                          cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=120,
                          encoding="utf-8", errors="replace", env=_env(**env))


@pytest.mark.parametrize("name", _STANDINS)
def test_each_stand_in_is_a_few_lines_that_say_why_and_when_it_goes(name):
    src = (REPO_ROOT / name).read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    assert "3.21" in doc, name + " must say which release removes it"
    code = [ln for ln in src.split('"""')[-1].splitlines() if ln.strip()]
    assert len(code) <= 6, code
    assert 'run_name="__main__", alter_sys=True' in src


# ---- the command-line tool ----------------------------------------------------------------

def test_the_cli_stand_in_runs_the_cli_and_says_once_where_it_went():
    r = _run("moonglade_backup.py", "--version")
    assert r.returncode == 0, r.stderr
    assert core.__version__ in r.stdout
    assert r.stderr.strip() == _NOTICE                  # one line, on stderr, nothing else
    r = _run("moonglade_backup.py", "--help")
    assert r.returncode == 0, r.stderr
    assert "--sync" in r.stdout


def test_the_cli_stand_in_passes_the_exit_code_through():
    r = _run("moonglade_backup.py", "--no-such-flag")
    assert r.returncode == 2                            # argparse's usage error
    assert "--no-such-flag" in r.stderr


def test_the_cli_stand_in_works_from_another_folder(tmp_path):
    """A Task Scheduler entry may name the script by its full path and start somewhere
    else: Python puts the script's own folder first on the path, so the package is found."""
    r = _run("moonglade_backup.py", "--version", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert core.__version__ in r.stdout


# ---- the web server -----------------------------------------------------------------------

def test_the_server_stand_in_starts_the_real_server():
    r = _run("moonglade_gallery.py", "--help")
    assert r.returncode == 0, r.stderr
    assert "--port" in r.stdout and "--out" in r.stdout
    assert r.stderr == ""                       # silent: the old launcher logs it to serve.log


def test_the_server_stand_in_passes_the_exit_code_through():
    r = _run("moonglade_gallery.py", "--no-such-flag")
    assert r.returncode == 2
    assert "--no-such-flag" in r.stderr


def test_the_server_stand_in_says_it_came_through_the_old_path(monkeypatch):
    """The flag is set before the server runs, so the server can tell an old launcher is
    still in charge. Run in-process with the server itself stood in for."""
    monkeypatch.setenv("MOONGLADE_VIA_STANDIN", "0")      # restored after, whatever it was
    calls = []

    def run_module(name, **kw):
        calls.append((name, kw, os.environ.get("MOONGLADE_VIA_STANDIN")))
    monkeypatch.setattr(runpy, "run_module", run_module)
    runpy.run_path(str(REPO_ROOT / "moonglade_gallery.py"))
    assert calls == [("moonglade.gallery", {"run_name": "__main__", "alter_sys": True}, "1")]


# ---- the MCP server -----------------------------------------------------------------------

_FASTMCP_STUB = textwrap.dedent('''
    class FastMCP:
        def __init__(self, name):
            self.name = name
        def tool(self, fn):
            return fn
        def run(self, transport=None):
            print("stub server ran over " + str(transport))
''')


def test_the_mcp_stand_in_runs_the_mcp_server_and_prints_nothing_of_its_own(tmp_path):
    """Started as the registrations start it: by its absolute path, from some other folder.
    A stub fastmcp stands first on the path (the real one is an optional dep, and would sit
    waiting on stdin), so the only stdout is the stub saying the server ran."""
    stub = tmp_path / "stub"
    (stub / "fastmcp" / "utilities").mkdir(parents=True)
    (stub / "fastmcp" / "__init__.py").write_text(_FASTMCP_STUB, encoding="utf-8")
    (stub / "fastmcp" / "utilities" / "__init__.py").write_text("", encoding="utf-8")
    (stub / "fastmcp" / "utilities" / "types.py").write_text(
        "class Image:\n    def __init__(self, data=None, format=None):\n        pass\n",
        encoding="utf-8")
    r = _run("moonglade_mcp.py", cwd=tmp_path, PYTHONPATH=str(stub),
             MOONGLADE_OUT=str(tmp_path / "library"))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "stub server ran over stdio\n"
    assert r.stderr == ""
