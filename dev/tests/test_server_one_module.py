"""`python -m moonglade.gallery` runs ONE server module: main() runs in moonglade.gallery.

`python -m moonglade.gallery` (the launcher's command, `Moonglade Launcher.pyw`) runs gallery.py
as `__main__`, a module nothing registers under its real name. Code that moves out of
create_app (split phase 4) reaches gallery with a call-time `from moonglade.gallery import ...`,
which in the launched server would load a SECOND copy of gallery.py: one whose _SERVER_CONTROL,
_OUTSIDE, exit record and nonce tables main() never wrote. Every in-process test imports the
registered module, so only the launched server would break (odd Stop/Restart, a missing outside
notice, refused nonces). gallery.py's `__main__` block therefore re-dispatches:
`import moonglade.gallery as _server; sys.exit(_server.main())`. The engine's version of the
same fix is moonglade/__main__.py, guarded by test_cli_one_engine.py; this is its twin.

  1. The real command, in a fresh interpreter, from a copy of the code folder: a `sitecustomize`
     wraps argparse.ArgumentParser.parse_args and, on its first call, records from main()'s own
     frame that main()'s globals ARE sys.modules["moonglade.gallery"].__dict__, that the server
     state main() writes is the state an importer gets, and that no module object other than
     `__main__` and the registered one was loaded from gallery.py. `--help` then exits 0.
  2. runpy, in process, with the registered module's main() stood in: the block calls THAT
     main(), and the SystemExit code is what it returned (0 stop, 42 restart, 2 and 3 refusals:
     the launcher's contract). sys.argv is `--help`, so a regressed block that calls its own
     main() stops at argparse instead of starting anything.
  3. It fires: against a copy of the package with the old `sys.exit(main())` block, case 1's
     probe reports main() running outside the registered module.
"""
import ast
import json
import os
import runpy
import shutil
import subprocess
import sys
import textwrap
import warnings

import pytest

from tests.conftest import CODE_PACKAGE, REPO_ROOT

PACKAGE = REPO_ROOT / CODE_PACKAGE

# The state main() writes and moved routes will read (split phase 4 design, 3.8).
SERVER_STATE = ("_SERVER_CONTROL", "_OUTSIDE", "_OUTSIDE_FIXING", "_EXIT_LOCK", "_SERVER_START")

# On PYTHONPATH ahead of everything. The first parse_args call (main()'s own) writes the report;
# then the real parse_args runs, so `--help` prints and exits 0 as it always has. It hands over to
# the next sitecustomize on the path first (the suite's network guard).
_SITE = textwrap.dedent('''
    import json, os, sys

    _here = os.path.dirname(os.path.abspath(__file__))

    def _chain():
        for d in sys.path:
            if os.path.abspath(d or os.curdir) == _here:
                continue
            p = os.path.join(d or os.curdir, "sitecustomize.py")
            if os.path.isfile(p):
                import importlib.util
                spec = importlib.util.spec_from_file_location("_next_sitecustomize", p)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return

    _chain()

    import argparse

    _real_parse_args = argparse.ArgumentParser.parse_args

    def _same_file(a, b):
        return bool(a and b) and (os.path.normcase(os.path.realpath(a))
                                  == os.path.normcase(os.path.realpath(b)))

    def _report(frame):
        import importlib
        main_mod = sys.modules.get("__main__")
        gallery_file = getattr(main_mod, "__file__", None)
        registered = sys.modules.get("moonglade.gallery")
        others = sorted({getattr(m, "__name__", "?") for m in list(sys.modules.values())
                         if _same_file(getattr(m, "__file__", None), gallery_file)
                         and m is not main_mod and m is not registered})
        out = {"caller": frame.f_code.co_name,
               "main_module_is_gallery_py": _same_file(gallery_file,
                                                       os.environ["MG_GALLERY_FILE"]),
               "registered_before_main": registered is not None,
               "main_is_registered": bool(registered is not None
                                          and frame.f_globals is registered.__dict__),
               "other_copies": others}
        imported = importlib.import_module("moonglade.gallery")
        out["state_is_imported"] = {
            n: (n in frame.f_globals and getattr(imported, n, None) is frame.f_globals[n])
            for n in json.loads(os.environ["MG_STATE_NAMES"])}
        return out

    def _parse_args(self, *a, **k):
        out = os.environ["MG_PROBE_OUT"]
        if not os.path.exists(out):
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(_report(sys._getframe(1)), fh)
        return _real_parse_args(self, *a, **k)

    argparse.ArgumentParser.parse_args = _parse_args
''')


def _launch(tmp_path, package_dir):
    """Run `python -m moonglade.gallery --help` from an app folder holding a copy of
    `package_dir`, with the probe on PYTHONPATH. -> (report dict or None, CompletedProcess)."""
    app = tmp_path / "app"
    shutil.copytree(package_dir, app / CODE_PACKAGE, ignore=shutil.ignore_patterns("__pycache__"))
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_SITE, encoding="utf-8")
    probe = tmp_path / "probe.json"
    env = dict(os.environ)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(site) + (os.pathsep + old if old else "")
    env["MG_PROBE_OUT"] = str(probe)
    env["MG_GALLERY_FILE"] = str(app / CODE_PACKAGE / "gallery.py")
    env["MG_STATE_NAMES"] = json.dumps(SERVER_STATE)
    r = subprocess.run([sys.executable, "-m", "moonglade.gallery", "--help"], cwd=str(app),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace", env=env)
    seen = json.loads(probe.read_text(encoding="utf-8")) if probe.is_file() else None
    return seen, r


def _one_server_failures(seen):
    """What case 1 holds, as a list of failures (empty = one server module)."""
    if seen is None:
        return ["parse_args was never called"]
    bad = []
    if seen["caller"] != "main":
        bad.append("the first parse_args call came from %r, not main()" % seen["caller"])
    if not seen["main_module_is_gallery_py"]:
        bad.append("__main__ was not loaded from the copy's gallery.py")
    if not seen["main_is_registered"]:
        bad.append("main() runs outside sys.modules['moonglade.gallery']")
    for name, same in sorted(seen["state_is_imported"].items()):
        if not same:
            bad.append("main()'s %s is not the object an importer of moonglade.gallery gets"
                       % name)
    if seen["other_copies"]:
        bad.append("other module objects were loaded from gallery.py: %r" % seen["other_copies"])
    return bad


def test_the_launched_server_runs_main_in_the_registered_module(tmp_path):
    seen, r = _launch(tmp_path, PACKAGE)
    assert _one_server_failures(seen) == [], json.dumps(seen) + "\n" + r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
    assert "--port" in r.stdout and "--out" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("code", [0, 2, 3, 42])
def test_the_entry_block_runs_the_registered_main_and_passes_its_code_through(code, monkeypatch):
    from moonglade import gallery as g

    calls = []

    def stand_in():
        caller = sys._getframe(1)
        calls.append({"caller_is_registered": caller.f_globals is g.__dict__,
                      "caller_name": caller.f_globals.get("__name__")})
        return code

    monkeypatch.setattr(g, "main", stand_in)
    # A regressed block that calls its own main() stops here, at argparse's --help, and starts
    # nothing; the assertions below then fail on the stand-in never having run.
    monkeypatch.setattr(sys, "argv", ["moonglade.gallery", "--help"])
    with warnings.catch_warnings():
        # runpy warns that moonglade.gallery is already imported: that is the point here.
        warnings.filterwarnings("ignore", message=".*found in sys.modules.*",
                                category=RuntimeWarning)
        with pytest.raises(SystemExit) as stopped:
            runpy.run_module("moonglade.gallery", run_name="__main__", alter_sys=True)
    assert len(calls) == 1, "the entry block did not call moonglade.gallery's main()"
    assert calls[0] == {"caller_is_registered": False, "caller_name": "__main__"}, calls
    assert sys.modules["moonglade.gallery"] is g
    assert stopped.value.code == code


def test_case_one_fires_on_the_old_entry_block(tmp_path):
    """The self-test: a copy of the package whose gallery.py ends with the pre-split block
    `sys.exit(main())` runs main() in the unregistered __main__, and case 1 says so."""
    pkg = tmp_path / "pkg"
    shutil.copytree(PACKAGE, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    gp = pkg / "gallery.py"
    text = gp.read_text(encoding="utf-8")
    tree = ast.parse(text)
    last = tree.body[-1]
    assert (isinstance(last, ast.If) and isinstance(last.test, ast.Compare)
            and ast.unparse(last.test) == "__name__ == '__main__'"), \
        "gallery.py no longer ends with its __main__ block"
    lines = text.split("\n")
    lines[last.lineno - 1:] = ['if __name__ == "__main__":', "    sys.exit(main())", ""]
    gp.write_text("\n".join(lines), encoding="utf-8")
    seen, r = _launch(tmp_path / "run", pkg)
    failures = _one_server_failures(seen)
    assert "main() runs outside sys.modules['moonglade.gallery']" in failures, \
        json.dumps(seen) + "\n" + r.stderr
    assert r.returncode == 0, r.stdout + r.stderr       # --help itself still worked
