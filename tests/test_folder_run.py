"""`python "<app folder>\\moonglade" ...` works from any folder (3.20, the root clean-up).

Before 3.20 a scheduled task or a script ran `python C:\\...\\moonglade_backup.py --sync` from
wherever it liked. The root stand-ins are gone, and `python -m moonglade` finds the package only
through the working directory, so the code folder itself is the command now: Python runs a
folder's __main__.py, and moonglade/__main__.py puts the app's folder on sys.path in its own
place. Claims:
  * run as a folder from somewhere else entirely, it is the command-line tool, exit code and all;
  * run as a relative folder from the app's own folder, likewise;
  * `python -m moonglade` from the app's folder keeps working (tests/test_code_package.py);
  * the code folder never stays on sys.path, so none of its modules (paths, logs, assets, ...)
    is importable under its bare name for the rest of the process.
"""
import json
import os
import subprocess
import sys
import textwrap

from moonglade import backup as core
from tests.conftest import CODE_PACKAGE, REPO_ROOT

PACKAGE = REPO_ROOT / CODE_PACKAGE

# Imported at start-up from PYTHONPATH; at exit it reports what the process's path ended up as.
_PROBE = textwrap.dedent('''
    import atexit, json, os, sys

    def _report():
        pkg = os.environ["MG_PROBE_PACKAGE"]
        bare = sorted(n for n in sys.modules
                      if "." not in n and n not in ("__main__", "__init__")
                      and os.path.isfile(os.path.join(pkg, n + ".py")))
        with open(os.environ["MG_PROBE_OUT"], "w", encoding="utf-8") as f:
            json.dump({"path": [os.path.abspath(p or os.curdir) for p in sys.path],
                       "bare": bare}, f)

    atexit.register(_report)
''')


def _env(**extra):
    env = dict(os.environ)
    env.update(extra)
    return env


def _run(args, cwd, env=None, timeout=120):
    return subprocess.run([sys.executable] + list(args), cwd=str(cwd), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env)


def test_the_code_folder_runs_from_any_folder(tmp_path):
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    r = _run([str(PACKAGE), "--version"], cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    assert core.__version__ in r.stdout
    r = _run([str(PACKAGE), "--help"], cwd=elsewhere)
    assert r.returncode == 0, r.stderr
    assert "--sync" in r.stdout


def test_it_passes_the_exit_code_through(tmp_path):
    r = _run([str(PACKAGE), "--no-such-flag"], cwd=tmp_path)
    assert r.returncode == 2                         # argparse's usage error
    assert "--no-such-flag" in r.stderr


def test_the_relative_folder_runs_from_the_app_folder():
    r = _run([CODE_PACKAGE, "--version"], cwd=REPO_ROOT)
    assert r.returncode == 0, r.stderr
    assert core.__version__ in r.stdout


def test_python_m_moonglade_still_runs_from_the_app_folder():
    r = _run(["-m", CODE_PACKAGE, "--version"], cwd=REPO_ROOT)
    assert r.returncode == 0, r.stderr
    assert core.__version__ in r.stdout


def test_the_code_folder_takes_its_own_place_off_the_path(tmp_path):
    """Python puts a run folder first on sys.path. Left there, `import paths` or `import logs`
    would find the app's own modules by their bare names, and a module of the same name from
    anything else would lose to them. The app's folder takes that first place instead."""
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "sitecustomize.py").write_text(_PROBE, encoding="utf-8")
    out = tmp_path / "report.json"
    env = _env(PYTHONPATH=str(probe), MG_PROBE_OUT=str(out),
               MG_PROBE_PACKAGE=str(PACKAGE))
    r = _run([str(PACKAGE), "--version"], cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    norm = [os.path.normcase(p) for p in report["path"]]
    assert norm[0] == os.path.normcase(str(REPO_ROOT)), report["path"][:3]
    assert os.path.normcase(str(PACKAGE)) not in norm
    assert report["bare"] == [], "importable by a bare name: %s" % report["bare"]
