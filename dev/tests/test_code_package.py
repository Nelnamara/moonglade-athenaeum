"""The code folder (3.20, "the move"): the app's modules live in the `moonglade/` package.

Three claims:
  * the entry points run: `python -m moonglade` is the command-line tool,
    `python -m moonglade.gallery` the web server and `python -m moonglade.mcp_server` the MCP
    server, each passing its exit code through;
  * the package's `__init__` imports nothing, so `-m moonglade.<module>` never meets a copy of
    that module imported before it ran;
  * no module in the package shadows a standard-library or SDK module. Run BY PATH
    (`python moonglade/x.py`), Python puts moonglade/ itself first on sys.path, and a module
    there named `logging` or `mcp` would then win over the real one for every import in the
    process (fastmcp imports `mcp`; everything imports `logging`). That is why the move named
    them logs.py and mcp_server.py.
"""
import ast
import os
import subprocess
import sys
import textwrap

from moonglade import backup as core
from tests.conftest import CODE_PACKAGE, REPO_ROOT

PACKAGE = REPO_ROOT / CODE_PACKAGE

# SDK packages the app runs beside, named by the plan, on top of whatever it imports itself.
_SDKS = {"mcp", "flask", "requests"}


def _module_names(folder):
    """The import names a folder offers when it is first on sys.path: every .py file's stem
    and every sub-folder that is a regular package. (A folder with no __init__.py is only a
    namespace package, which never wins over a real module found later on the path.)"""
    names = set()
    for p in folder.iterdir():
        if p.is_file() and p.suffix == ".py":
            names.add(p.stem)
        elif p.is_dir() and (p / "__init__.py").is_file():
            names.add(p.name)
    return names - {"__init__", "__main__"}


def _third_party_imports(folder):
    """Top-level names the package's own code imports that are neither the package nor the
    standard library: the SDKs it actually uses (fastmcp, PIL, pixeltable, ...)."""
    own = _module_names(folder) | {CODE_PACKAGE}
    found = set()
    for p in folder.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                found |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                found.add(n.module.split(".")[0])
    return found - own - set(sys.stdlib_module_names)


def _shadowing(folder):
    reserved = set(sys.stdlib_module_names) | _SDKS | _third_party_imports(folder)
    return sorted(_module_names(folder) & reserved)


def test_no_module_in_the_package_shadows_the_stdlib_or_an_sdk():
    names = _module_names(PACKAGE)
    assert {"gallery", "backup", "logs", "mcp_server", "paths"} <= names, names
    assert not _shadowing(PACKAGE), _shadowing(PACKAGE)


def test_the_shadow_check_catches_the_names_the_move_avoided(tmp_path):
    for name in ("logging.py", "mcp.py", "flask.py", "gallery.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "__init__.py").write_text("", encoding="utf-8")
    assert _shadowing(tmp_path) == ["flask", "logging", "mcp", "requests"]


def test_the_package_init_imports_nothing():
    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr), \
        "moonglade/__init__.py holds only its docstring"


def _env(**extra):
    env = dict(os.environ)
    env.update(extra)
    return env


def _run(args, timeout=120, **env):
    return subprocess.run([sys.executable] + list(args), cwd=str(REPO_ROOT),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=timeout,
                          encoding="utf-8", errors="replace", env=_env(**env))


def test_python_m_moonglade_is_the_command_line_tool():
    r = _run(["-m", "moonglade", "--version"])
    assert r.returncode == 0, r.stderr
    assert core.__version__ in r.stdout
    r = _run(["-m", "moonglade", "--help"])
    assert r.returncode == 0, r.stderr
    assert "--sync" in r.stdout and "--generate" in r.stdout


def test_python_m_moonglade_passes_the_exit_code_through():
    r = _run(["-m", "moonglade", "--no-such-flag"])
    assert r.returncode == 2                         # argparse's usage error
    assert "--no-such-flag" in r.stderr


def test_python_m_moonglade_gallery_is_the_server():
    r = _run(["-m", "moonglade.gallery", "--help"])
    assert r.returncode == 0, r.stderr
    assert "--port" in r.stdout and "--out" in r.stdout


_FASTMCP_STUB = textwrap.dedent('''
    class FastMCP:
        def __init__(self, name):
            self.name = name
        def tool(self, fn):
            return fn
        def run(self, transport=None):
            print("stub server ran over " + str(transport))
''')


def test_python_m_moonglade_mcp_server_is_the_mcp_server(tmp_path):
    """Its __main__ block runs: the move first (moonglade.setup.prepare), then the tools. A
    stub fastmcp stands first on the path (the real one is an optional dep, and would sit
    waiting on stdin), so `run` just says it was called.

    It runs from a COPY of the code folder in an app folder of this test's own: a real run
    does the install half of the move in its app folder's local/, and that must never be the
    checkout's (dev/tests/conftest.py's _real_machine_files_untouched watches for it)."""
    import shutil
    stub = tmp_path / "stub"
    (stub / "fastmcp" / "utilities").mkdir(parents=True)
    (stub / "fastmcp" / "__init__.py").write_text(_FASTMCP_STUB, encoding="utf-8")
    (stub / "fastmcp" / "utilities" / "__init__.py").write_text("", encoding="utf-8")
    (stub / "fastmcp" / "utilities" / "types.py").write_text(
        "class Image:\n    def __init__(self, data=None, format=None):\n        pass\n",
        encoding="utf-8")
    app = tmp_path / "app"
    shutil.copytree(PACKAGE, app / CODE_PACKAGE,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "library").mkdir()
    r = subprocess.run([sys.executable, "-m", "moonglade.mcp_server"], cwd=str(app),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace",
                       env=_env(PYTHONPATH=str(stub), MOONGLADE_OUT=str(tmp_path / "library")))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "stub server ran over stdio"
    # the move ran first, in this app folder and in the library MOONGLADE_OUT names
    assert (app / "local" / ".journal.json").is_file()
    assert (tmp_path / "library" / "_moonglade" / ".journal.json").is_file()
