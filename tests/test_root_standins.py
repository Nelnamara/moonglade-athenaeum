"""The root stand-ins (3.20, "the move"): the three old entry scripts keep working, each by
running its module in the moonglade/ package as the main module.

  moonglade_gallery.py  MANDATORY, and PERMANENT (DECISIONS 2026-10-05). A launcher from before
                        3.20 relaunches this exact path after an update's restart (exit code
                        42); without it the app stops. An install on 3.17-3.19 can update
                        straight past 3.20 and never meet its gate, so this one never goes.
                        It sets MOONGLADE_VIA_STANDIN=1.
  moonglade_backup.py   old habits, Task Scheduler entries, old docs. One line on stderr.
                        Goes in 3.21.
  moonglade_mcp.py      the existing MCP registrations name this path. Silent: an MCP
                        server's stdout is the protocol. Goes in 3.21.

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
def test_each_stand_in_is_a_few_lines_that_say_why_and_how_long_it_stays(name):
    src = (REPO_ROOT / name).read_text(encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    if name == "moonglade_gallery.py":
        # Permanent: an old launcher can meet it after ANY later update (DECISIONS 2026-10-05).
        assert "stays for good" in doc and "3.17" in doc and "skip" in doc, (
            name + " must say it is permanent, and why")
        assert "3.21" not in doc, name + " must not promise a removal that will not happen"
    else:
        assert "3.21" in doc, name + " must say which release removes it"
    code = [ln for ln in src.split('"""')[-1].splitlines() if ln.strip()]
    assert len(code) <= 8, code
    assert 'run_name="__main__", alter_sys=True' in src


# ---- imported, a stand-in runs nothing --------------------------------------------------------

@pytest.mark.parametrize("module,moved_to", [
    ("moonglade_backup", "moonglade.backup"),
    ("moonglade_gallery", "moonglade.gallery"),
    ("moonglade_mcp", "moonglade.mcp_server"),
])
def test_importing_a_stand_in_raises_and_runs_nothing(monkeypatch, module, moved_to):
    """A process still running OLD code can import a flat name for the first time after the
    update -- an old MCP server's first tag_suggest does `import moonglade_backup`. Were the
    stand-in to run its body on import, that would start a full backup with no flags inside
    the MCP process, its prints corrupting the protocol on stdout. Imported, a stand-in only
    says where its module went. (runpy.run_module is stood in for, so a missing guard here
    records a call instead of really running anything.)"""
    import importlib
    ran = []
    monkeypatch.setattr(runpy, "run_module", lambda name, **kw: ran.append(name))
    monkeypatch.setenv("MOONGLADE_VIA_STANDIN", "0")      # restored after, whatever it was
    monkeypatch.delitem(sys.modules, module, raising=False)
    with pytest.raises(ImportError) as e:
        importlib.import_module(module)
    assert str(e.value) == "%s moved to %s" % (module, moved_to)
    assert ran == []
    assert os.environ["MOONGLADE_VIA_STANDIN"] == "0"
    assert module not in sys.modules


def test_importing_the_cli_stand_in_from_an_old_process_prints_nothing():
    """The MCP case end to end, in a fresh interpreter: nothing on stdout, no backup run."""
    r = subprocess.run([sys.executable, "-c", "import moonglade_backup"], cwd=str(REPO_ROOT),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace", env=_env())
    assert r.returncode == 1
    assert r.stdout == ""
    assert "ImportError: moonglade_backup moved to moonglade.backup" in r.stderr
    assert _NOTICE not in r.stderr


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
    runpy.run_path(str(REPO_ROOT / "moonglade_gallery.py"), run_name="__main__")
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
