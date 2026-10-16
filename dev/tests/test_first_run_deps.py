"""A first start installs what Moonglade needs (issue #87).

A new install used to stop with "Flask is required for the gallery server": the packages were
installed only by the one-click update, and a first install relied on a manual `pip install`
that on Windows often landed in a different Python than the one that opens Moonglade Launcher
(which runs the server with its own sys.executable). Now `moonglade/deps.py` finds what
requirements.txt names that this Python lacks, and the launcher names it and, on a Yes, installs
it with this same Python before it starts the server.

Claims:
  * deps.requirements reads a requirements file the way pip would for names only: comments,
    options, specifiers and extras go; a false `python_version` marker drops the line;
  * deps.missing judges presence with importlib.metadata, never a version;
  * the pip commands (the launcher's, and the one a person pastes) use this Python, and the
    paste prefers python.exe over pythonw.exe so pip's output is seen;
  * deps.install never raises and hands back the end of pip's output;
  * deps.py imports only the standard library, because it runs before any other package exists;
  * the launcher checks before it starts the server, installs only after a Yes, and says plainly
    what to run when it was not allowed to, or when pip did not do it.

The .pyw runs on import, so it is run with runpy and every outside effect stood in for, the same
way dev/tests/test_launcher_gets_ready_first.py runs it.
"""
import ast
import importlib.metadata
import os
import pathlib
import runpy
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
import webbrowser

import pytest

from moonglade import deps, paths
from tests.conftest import REPO_ROOT, stub_code_module

LAUNCHER = REPO_ROOT / "Moonglade Launcher.pyw"


# ---- deps.requirements ------------------------------------------------------------------------

_SAMPLE = """\
# the first comment
requests
truststore ; python_version >= "2.7"
legacy-only ; python_version < "3.0"
future-only ; python_version >= "99.0"
Pillow>=10,<12   # pinned, with a comment
numpy        # an inline comment
             # that carries on, on a line of its own
flask[async]==3.0.*
-r other-requirements.txt
-e ./some/folder
--index-url https://example.invalid/simple

zeroconf>=0.130
pytest_mock
windows-only ; sys_platform == "win32"
named @ https://example.invalid/named.zip
https://example.invalid/bare.whl
Requests
"""


def _write(tmp_path, text, name="requirements.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_requirements_reads_only_the_names(tmp_path):
    got = deps.requirements(_write(tmp_path, _SAMPLE))
    assert got == ["requests", "truststore", "Pillow", "numpy", "flask", "zeroconf",
                   "pytest_mock", "windows-only", "named"]


_MARKERS = """\
old-enough ; python_version >= "2.7"
too-old ; python_version < "2.7"
new-enough ; python_version < "99.0"
too-new ; python_version >= "99.0"
too-new-single ; python_version > '99.0'
"""


def test_a_false_python_version_marker_drops_the_line_and_a_true_one_keeps_it(tmp_path):
    got = deps.requirements(_write(tmp_path, _MARKERS))
    assert got == ["old-enough", "new-enough"]


@pytest.mark.parametrize("marker, holds", [
    ('python_version >= "3.10"', False), ('python_version < "3.10"', True),
    ('python_version == "3.9"', True), ('python_version != "3.9"', False),
    ('python_version <= "3.9"', True), ('python_version > "3.9"', False),
    ('python_version ~= "3.9"', True), ('python_version ~= "3.10"', False),
    ("python_version>='3.9'", True),
    ('sys_platform == "win32"', True),                       # any other marker counts as true
    ('python_version >= "3.10" and sys_platform == "win32"', True),
    ("", True),
])
def test_the_python_version_marker_is_judged_on_this_python(monkeypatch, marker, holds):
    monkeypatch.setattr(sys, "version_info", (3, 9, 1, "final", 0))
    assert deps._marker_holds(marker) is holds


def test_a_name_is_listed_once_however_it_is_spelled(tmp_path):
    path = _write(tmp_path, "pytest-mock\nPytest_Mock>=1\npytest.mock\n")
    assert deps.requirements(path) == ["pytest-mock"]


def test_a_file_saved_with_a_byte_order_mark_reads_fine(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_bytes(b"\xef\xbb\xbfrequests\r\nflask\r\n")
    assert deps.requirements(path) == ["requests", "flask"]


# ---- deps.missing -----------------------------------------------------------------------------

def _installed(monkeypatch, names):
    """Stand in for importlib.metadata.distribution: only `names` are installed. It is given
    no version to compare, because deps never asks for one."""
    def distribution(name):
        if name in names:
            return types.SimpleNamespace(version="0.0.1")
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata, "distribution", distribution)


def test_missing_names_what_is_not_installed(tmp_path, monkeypatch):
    path = _write(tmp_path, "requests\nflask\nPillow\npytest_mock\nzeroconf>=0.130\n")
    _installed(monkeypatch, {"requests", "pillow", "pytest-mock"})
    assert deps.missing(path) == ["flask", "zeroconf"]


def test_missing_is_empty_when_everything_is_there(tmp_path, monkeypatch):
    path = _write(tmp_path, "requests\nflask\n")
    _installed(monkeypatch, {"requests", "flask"})
    assert deps.missing(path) == []


def test_missing_judges_presence_not_version(tmp_path, monkeypatch):
    """A package pinned above what is installed is still present: an old one is the update's
    business, and must never hold a start."""
    path = _write(tmp_path, "flask>=99.0\n")
    _installed(monkeypatch, {"flask"})
    assert deps.missing(path) == []


def test_with_nothing_installed_everything_the_app_names_is_missing(monkeypatch):
    _installed(monkeypatch, set())
    req = paths.requirements_path()
    assert deps.missing(req) == deps.requirements(req)
    assert "flask" in deps.missing(req)


# ---- the pip commands -------------------------------------------------------------------------

def test_the_install_command_is_this_pythons_own_pip(tmp_path):
    req = tmp_path / "requirements.txt"
    assert deps.install_command(req) == [sys.executable, "-m", "pip", "install", "-r", str(req)]


# An absolute folder with no space in it, whatever the platform, so what is typed is known.
_ROOT = os.path.abspath(os.sep + "moonglade")
_SPACED = os.path.join(_ROOT, "Moonglade Athenaeum")


def test_the_command_a_person_pastes_is_one_line_when_nothing_needs_quotes(monkeypatch):
    """Command Prompt and PowerShell both run it as it stands."""
    exe = os.path.join(_ROOT, "py", "python.exe")
    req = os.path.join(_ROOT, "requirements.txt")
    monkeypatch.setattr(sys, "executable", exe)
    assert deps.manual_command(req) == "%s -m pip install -r %s" % (exe, req)
    assert deps.ensurepip_command() == "%s -m ensurepip" % exe


def test_the_requirements_file_is_given_by_its_full_path(monkeypatch):
    monkeypatch.setattr(sys, "executable", os.path.join(_ROOT, "py", "python.exe"))
    assert os.path.abspath("requirements.txt") in deps.manual_command("requirements.txt")


def test_a_path_with_a_space_is_quoted_and_each_shell_gets_its_own_line(monkeypatch):
    exe = os.path.join(_ROOT, "py", "python.exe")
    req = os.path.join(_SPACED, "requirements.txt")             # an install in a folder with a space
    monkeypatch.setattr(sys, "executable", exe)
    typed = '%s -m pip install -r "%s"' % (exe, req)             # only the path that needs it
    assert deps.manual_command(req) == (
        "In Command Prompt: %s\nIn PowerShell: & %s" % (typed, typed))


def test_a_python_in_a_folder_with_a_space_is_quoted_too(monkeypatch):
    exe = os.path.join(_SPACED, "python.exe")
    req = os.path.join(_ROOT, "requirements.txt")
    monkeypatch.setattr(sys, "executable", exe)
    typed = '"%s" -m pip install -r %s' % (exe, req)
    assert deps.manual_command(req) == (
        "In Command Prompt: %s\nIn PowerShell: & %s" % (typed, typed))
    ensure = '"%s" -m ensurepip' % exe
    assert deps.ensurepip_command() == (
        "In Command Prompt: %s\nIn PowerShell: & %s" % (ensure, ensure))


def test_a_person_is_given_python_exe_when_the_launcher_runs_under_pythonw(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    (tmp_path / "python.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    req = tmp_path / "requirements.txt"
    assert deps.console_python() == str(tmp_path / "python.exe")
    pasted = deps.manual_command(req)
    assert deps._quoted(str(tmp_path / "python.exe")) + " -m pip install -r " in pasted
    assert "pythonw" not in pasted
    # the launcher's own command still uses the interpreter that runs it
    assert deps.install_command(req)[0] == str(tmp_path / "pythonw.exe")


def test_pythonw_stays_when_there_is_no_python_exe_beside_it(tmp_path, monkeypatch):
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert deps.console_python() == str(tmp_path / "pythonw.exe")
    assert deps._quoted(str(tmp_path / "pythonw.exe")) + " -m pip" in deps.manual_command(
        tmp_path / "r.txt")


# ---- deps.install -----------------------------------------------------------------------------

def _pip(monkeypatch, result=None, raises=None):
    """Stand in for subprocess.run: record how pip was started, hand back `result` (or raise)."""
    calls = []

    def run(cmd, **kw):
        calls.append(types.SimpleNamespace(cmd=list(cmd), **kw))
        if raises is not None:
            raise raises
        return result
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_install_runs_pip_from_the_app_folder_with_no_window_and_a_limit(tmp_path, monkeypatch):
    req = _write(tmp_path, "requests\n")
    log = tmp_path / "logs" / "serve.log"
    log.parent.mkdir()
    log.write_text("[launcher] earlier line\n", encoding="utf-8")
    out = "\n".join("line %d" % i for i in range(1, 31)) + "\n"
    calls = _pip(monkeypatch, types.SimpleNamespace(returncode=0, stdout=out))

    code, tail = deps.install(req, log)

    assert code == 0
    assert tail.splitlines() == ["line %d" % i for i in range(16, 31)]      # the last fifteen
    (call,) = calls
    assert call.cmd == deps.install_command(req)
    assert call.cwd == str(tmp_path)
    assert call.timeout == 900
    assert call.creationflags == deps._NO_WINDOW
    assert call.stdin is subprocess.DEVNULL
    assert call.stdout is subprocess.PIPE and call.stderr is subprocess.STDOUT
    said = log.read_text(encoding="utf-8")
    assert said.startswith("[launcher] earlier line\n")                      # appended, not over
    assert "line 1\n" in said and "line 30" in said


def test_install_on_windows_asks_for_no_console_window():
    if sys.platform == "win32":
        assert deps._NO_WINDOW == 0x08000000


def test_install_hands_back_a_failed_pips_code_and_words(tmp_path, monkeypatch):
    req = _write(tmp_path, "requests\n")
    _pip(monkeypatch, types.SimpleNamespace(
        returncode=1, stdout="ERROR: No matching distribution found for flask\n\n"))
    code, tail = deps.install(req, tmp_path / "serve.log")
    assert code == 1
    assert tail == "ERROR: No matching distribution found for flask"


def test_install_never_raises_when_pip_cannot_be_started(tmp_path, monkeypatch):
    req = _write(tmp_path, "requests\n")
    log = tmp_path / "serve.log"
    _pip(monkeypatch, raises=FileNotFoundError("no such python"))
    code, tail = deps.install(req, log)
    assert code != 0
    assert "FileNotFoundError" in tail and "no such python" in tail
    assert "no such python" in log.read_text(encoding="utf-8")


def test_install_never_raises_when_pip_does_not_finish(tmp_path, monkeypatch):
    req = _write(tmp_path, "requests\n")
    _pip(monkeypatch, raises=subprocess.TimeoutExpired(["pip"], 900, output=b"Collecting flask\n"))
    code, tail = deps.install(req, tmp_path / "serve.log")
    assert code != 0
    assert "Collecting flask" in tail and "did not finish" in tail


def test_install_never_raises_when_the_log_cannot_be_written(tmp_path, monkeypatch):
    req = _write(tmp_path, "requests\n")
    _pip(monkeypatch, types.SimpleNamespace(returncode=0, stdout="ok\n"))
    code, tail = deps.install(req, tmp_path)           # a folder, so it cannot be opened to append
    assert (code, tail) == (0, "ok")


# ---- deps.py runs before anything is installed ------------------------------------------------

def test_deps_imports_only_the_standard_library():
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:
        pytest.skip("sys.stdlib_module_names needs Python 3.10")
    tree = ast.parse((REPO_ROOT / "moonglade" / "deps.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import reaches into the moonglade package"
            imported.add((node.module or "").split(".")[0])
    assert imported, "the walk found no imports at all"
    outside = sorted(imported - set(stdlib))
    assert not outside, "moonglade/deps.py runs before any package is installed, but imports " \
        + ", ".join(outside)


# ---- the launcher -----------------------------------------------------------------------------

class _NoThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def _ready():
    return types.SimpleNamespace(summary=lambda: "", write_log=lambda: None)


@pytest.fixture
def launch(monkeypatch, tmp_path):
    import ctypes

    def _launch(lacking=(), windows=True, answers=(6,), pip=(0, ""), check_raises=False):
        """`lacking`: what deps.missing answers on each call (the last one repeats). `answers`:
        what the message boxes return in turn (6 is Yes). `pip`: what deps.install returns."""
        run = types.SimpleNamespace(events=[], started=[], boxes=[], installs=[], asked=[],
                                    exit=None)
        lacking = [list(x) for x in lacking] or [[]]
        answers = list(answers)

        def missing(path):
            run.events.append("missing")
            run.asked.append(path)
            if check_raises:
                raise RuntimeError("the check broke")
            return list(lacking.pop(0)) if len(lacking) > 1 else list(lacking[0])

        def install(path, log_path):
            run.events.append("install")
            run.installs.append((path, log_path))
            return pip

        def popen(cmd, **kw):
            run.events.append("popen")
            run.started.append(types.SimpleNamespace(cmd=list(cmd), **kw))
            return types.SimpleNamespace(wait=lambda: 0)

        def box(hwnd, text, title, flags):
            run.events.append("box")
            run.boxes.append(types.SimpleNamespace(text=text, title=title, flags=flags))
            answer = answers.pop(0) if answers else 1
            if isinstance(answer, Exception):          # a desktop that cannot show a box
                raise answer
            return answer

        monkeypatch.setattr(deps, "missing", missing)
        monkeypatch.setattr(deps, "install", install)
        monkeypatch.setattr(subprocess, "Popen", popen)
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: (_ for _ in ()
                            ).throw(urllib.error.URLError("refused")))
        monkeypatch.setattr(webbrowser, "open", lambda url: None)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(threading, "Thread", _NoThread)
        monkeypatch.setattr(sys, "path", list(sys.path))
        monkeypatch.setattr(sys, "platform", "win32" if windows else "linux")
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(
            user32=types.SimpleNamespace(MessageBoxW=box)), raising=False)
        stub_code_module(monkeypatch, "setup", types.SimpleNamespace(
            prepare=lambda kind: _ready(), peek_server=lambda: {"port": 5000}))
        monkeypatch.chdir(tmp_path)              # it changes directory; this puts it back
        try:
            runpy.run_path(str(LAUNCHER), run_name="__main__")
        except SystemExit as e:
            run.exit = e.code
        return run
    return _launch


def _serve_log():
    return (paths.logs_dir() / "serve.log").read_text(encoding="utf-8")


def test_with_nothing_missing_the_launcher_carries_on_as_before(launch):
    run = launch()
    assert run.events == ["missing", "popen"]            # checked, then started; no box, no pip
    assert run.asked == [paths.requirements_path()]
    assert run.boxes == [] and run.installs == [] and run.exit is None


def test_a_missing_package_is_asked_about_and_installed_on_a_yes_before_the_server_starts(launch):
    run = launch(lacking=[["flask", "numpy"], []], answers=(6,), pip=(0, "Successfully installed"))
    assert run.events == ["missing", "box", "install", "missing", "popen"]
    (box,) = run.boxes
    assert box.title == "Moonglade Athenaeum"
    assert box.flags == 0x4 | 0x20                       # MB_YESNO | MB_ICONQUESTION
    assert box.text == (
        "Moonglade needs some Python packages that aren't installed yet: flask, numpy.\n\n"
        "Install them now? This runs pip for the Python that runs Moonglade:\n"
        + sys.executable + "\n\nIt can take a minute or two. Moonglade starts when it's done.")
    # pip is run for the requirements file, writing to serve.log
    assert run.installs == [(paths.requirements_path(), paths.logs_dir() / "serve.log")]
    assert len(run.started) == 1 and run.exit is None
    log = _serve_log()
    assert "[launcher] Moonglade needs some Python packages that aren't installed yet: " \
        "flask, numpy." in log
    assert "[launcher] Installed flask, numpy." in log


def test_a_no_installs_nothing_and_says_what_to_run(launch):
    run = launch(lacking=[["flask"]], answers=(7, 1))
    assert run.events == ["missing", "box", "box"]       # the question, then the stop
    assert run.installs == [] and run.started == [] and run.exit == 1
    stop = run.boxes[1]
    assert "Moonglade needs some Python packages that aren't installed yet: flask." in stop.text
    assert "To install them, run:\n" + deps.manual_command(paths.requirements_path()) in stop.text
    assert "To install them, run:" in _serve_log()


def test_a_box_that_cannot_be_shown_is_a_no(launch):
    run = launch(lacking=[["flask"]], answers=(OSError("no desktop"), 1))
    assert run.installs == [] and run.started == [] and run.exit == 1
    assert "To install them, run:" in _serve_log()


def test_off_windows_there_is_no_box_and_nothing_installs(launch, capsys):
    run = launch(lacking=[["flask"]], windows=False)
    assert run.boxes == [] and run.installs == [] and run.started == [] and run.exit == 1
    err = capsys.readouterr().err
    assert "aren't installed yet: flask." in err
    assert "To install them, run:\n" + deps.manual_command(paths.requirements_path()) in err


def test_pip_failing_says_its_code_its_last_words_and_the_command_to_run(launch):
    run = launch(lacking=[["flask"], ["flask"]], answers=(6, 1),
                 pip=(1, "ERROR: Could not find a version that satisfies flask"))
    assert run.started == [] and run.exit == 1
    stop = run.boxes[1].text
    assert stop.startswith("Moonglade couldn't get ready to start.\n\n")
    assert "Installing the packages didn't work (pip ended with code 1). " \
        "The end of local\\logs\\serve.log says:\n\n" \
        "ERROR: Could not find a version that satisfies flask\n\n" \
        "To install them by hand, run:\n" + deps.manual_command(paths.requirements_path()) in stop


def test_pip_saying_yes_but_the_package_still_missing_does_not_start_the_server(launch):
    run = launch(lacking=[["flask"], ["flask"]], answers=(6, 1), pip=(0, "Requirement satisfied"))
    assert run.events == ["missing", "box", "install", "missing", "box"]
    assert run.started == [] and run.exit == 1
    assert "pip ended with code 0" in run.boxes[1].text


def test_a_python_with_no_pip_is_told_so(launch):
    run = launch(lacking=[["flask"], ["flask"]], answers=(6, 1),
                 pip=(1, "C:\\Python\\python.exe: No module named pip"))
    stop = run.boxes[1].text
    assert "this Python has no pip" in stop
    assert "python.org" in stop and "includes pip" in stop
    assert deps.ensurepip_command() in stop
    assert "To install them by hand" not in stop
    assert run.started == [] and run.exit == 1


def test_an_install_folder_with_a_space_gets_a_line_for_each_shell(launch, monkeypatch):
    spaced = os.path.join(_SPACED, "requirements.txt")
    monkeypatch.setattr(paths, "requirements_path", lambda: pathlib.Path(spaced))
    run = launch(lacking=[["flask"]], answers=(7, 1))
    stop = run.boxes[1].text
    assert run.exit == 1 and run.installs == []
    assert "To install them, run:\nIn Command Prompt: " in stop
    assert '-m pip install -r "%s"\nIn PowerShell: & ' % spaced in stop
    assert stop.endswith('-r "%s"' % spaced)


def test_a_check_that_breaks_never_stops_a_start(launch):
    run = launch(check_raises=True)
    assert run.events == ["missing", "popen"]
    assert run.boxes == [] and run.exit is None


def test_the_launcher_checks_after_getting_ready_and_before_the_shortcuts_and_the_server():
    src = LAUNCHER.read_text(encoding="utf-8")
    body = [n for n in ast.parse(src).body if not isinstance(n, ast.FunctionDef)]

    def first(pred):
        return next(i for i, n in enumerate(body) if any(pred(x) for x in ast.walk(n)))
    ready = first(lambda x: isinstance(x, ast.Call) and getattr(x.func, "attr", "") == "prepare")
    check = first(lambda x: isinstance(x, ast.Call)
                  and getattr(x.func, "id", "") == "_packages_it_needs")
    shortcuts = first(lambda x: isinstance(x, ast.Constant) and x.value == "moonglade-shortcuts")
    loop = next(i for i, n in enumerate(body) if isinstance(n, ast.While))
    assert ready < check < shortcuts < loop
    # and the check is of requirements.txt, with deps.missing, ahead of the one place that starts it
    assert "_deps.missing(req)" in src and "_paths.requirements_path()" in src
    assert src.index("_deps.missing(req)") < src.index("subprocess.Popen(cmd")
