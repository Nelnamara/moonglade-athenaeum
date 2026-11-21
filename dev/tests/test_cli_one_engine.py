"""`python -m moonglade` runs ONE engine: the module that runs main() is moonglade.backup.

The 3.21.0 split moved code out of moonglade/backup.py into modules (pixai_client, mirror,
media_tools, organize, ...) that reach the engine with a call-time `from moonglade.backup import
...`. moonglade/__main__.py used to run backup's code as an unregistered `__main__` module, so on
the command line the first such import loaded a SECOND copy of backup.py. Its PixAIError was a
different class from the one the engine's ~48 `except PixAIError` handlers name, its `_VERBOSE`
never saw -v, and its USER_ID never saw _make_session's. The review reproduced `--account` with a
401 dying on a traceback where 3.20 printed a sentence.

This runs the real entry point in a subprocess, offline: a copy of the code folder in an app
folder of the test's own (a throwaway config.json with a made-up key, never the checkout's), and
a `sitecustomize` that answers every HTTP request with a 401 instead of a socket. It holds:
  * the engine that is running (run_account_info's own globals) IS sys.modules["moonglade.backup"],
    and only one module object anywhere was loaded from backup.py;
  * the PixAIError the moved transport (pixai_client) raises is caught by the engine's handler:
    `--account` prints 3.20's sentence and exits 0, no traceback.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap

from tests.conftest import CODE_PACKAGE, REPO_ROOT

PACKAGE = REPO_ROOT / CODE_PACKAGE

# On PYTHONPATH ahead of everything: every HTTP request is a 401, and the first one records which
# module objects were loaded from backup.py and whether the engine that asked is the registered
# one. It then hands over to the next sitecustomize on the path (the suite's network guard).
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

    import requests

    def _engine_frame():
        # main(): run_account_info itself is moonglade/account_api.py's since 3.22 (phase 4)
        f = sys._getframe(1)
        while f is not None:
            if f.f_code.co_name == "main":
                return f
            f = f.f_back
        return None

    def _same_file(a, b):
        return bool(a and b) and (os.path.normcase(os.path.realpath(a))
                                  == os.path.normcase(os.path.realpath(b)))

    def _report():
        registered = sys.modules.get("moonglade.backup")
        engine_file = getattr(registered, "__file__", None)
        copies = {id(m) for m in list(sys.modules.values())
                  if _same_file(getattr(m, "__file__", None), engine_file)}
        engine = _engine_frame()
        return {"copies": len(copies),
                "registered": registered is not None,
                "engine_is_registered": bool(engine is not None and registered is not None
                                             and engine.f_globals is registered.__dict__)}

    class _Unauthorized:
        status_code = 401
        ok = False
        reason = "Unauthorized"
        text = "unauthorized"
        headers = {}
        is_redirect = False
        url = "https://api.pixai.art/graphql"

        def json(self):
            return {"errors": [{"message": "unauthorized"}]}

        def raise_for_status(self):
            raise requests.HTTPError("401 Unauthorized")

    def _request(self, method, url, *a, **k):
        out = os.environ["MG_PROBE_OUT"]
        if not os.path.exists(out):
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(_report(), fh)
        return _Unauthorized()

    requests.Session.request = _request
''')


def test_the_command_line_runs_one_engine_and_catches_its_own_errors(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(PACKAGE, app / CODE_PACKAGE, ignore=shutil.ignore_patterns("__pycache__"))
    # A made-up key and a pinned account id: _make_session needs no network, so the first
    # request is the account read itself.
    (app / "config.json").write_text(json.dumps({"PIXAI_API_KEY": "test-key-not-a-real-one",
                                                 "USER_ID": "1"}), encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(_SITE, encoding="utf-8")
    probe = tmp_path / "probe.json"
    env = dict(os.environ)
    env.pop("PIXAI_TOKEN", None)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(site) + (os.pathsep + old if old else "")
    env["MG_PROBE_OUT"] = str(probe)
    r = subprocess.run([sys.executable, "-m", "moonglade", "--account"], cwd=str(app),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace", env=env)
    assert probe.is_file(), "no request reached the fake:\n" + r.stdout + r.stderr
    seen = json.loads(probe.read_text(encoding="utf-8"))
    assert seen["registered"], "moonglade.backup was never imported"
    assert seen["engine_is_registered"], \
        "the running engine is not sys.modules['moonglade.backup']: " + json.dumps(seen)
    assert seen["copies"] == 1, "backup.py was loaded more than once: " + json.dumps(seen)
    # The moved transport's PixAIError reached the engine's own handler.
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("Account read failed: your API key is missing or expired -- check config.json."
            in r.stdout), r.stdout + r.stderr
