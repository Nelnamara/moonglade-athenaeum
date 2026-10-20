"""Install Moonglade.cmd: the first-time setup for a Windows PC that may have no Python at all.

A person with no Python cannot run anything Python to get Python, so the setup is a plain batch
file at the install root. It finds a Python 3.10 or newer (the py launcher, then python on PATH;
the Microsoft Store's "python" stub does not count), installs one for the user only with winget if
there is none, installs requirements.txt with that Python, and starts Moonglade Launcher.pyw with
the pythonw.exe beside it. `--check` only reports what it found and what it would do.

What this file holds:

  * the file exists and is CRLF (cmd.exe's labels and goto misbehave with bare LF), and
    .gitattributes pins it that way so a checkout keeps it;
  * it names the winget id, `--scope user`, requirements.txt and "Moonglade Launcher.pyw", and
    never asks for administrator rights;
  * on Windows, `--check` exits 0 and reports a Python it found without installing or starting
    anything; and a whole run in a scratch copy (a stub launcher, an empty requirements.txt)
    reaches the launcher through the pythonw.exe beside the Python it found.

The batch file is read as text and run through cmd.exe; none of it needs the app's own modules.
"""
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from tests.conftest import REPO_ROOT

SETUP = REPO_ROOT / "Install Moonglade.cmd"
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="a Windows batch file runs on Windows only")


def _text():
    return SETUP.read_bytes().decode("ascii")      # ASCII only: a batch file reads in the console's code page


def test_the_setup_file_exists_at_the_install_root():
    assert SETUP.is_file()
    assert SETUP.parent == REPO_ROOT


def test_the_setup_file_has_windows_line_endings_and_is_plain_ascii():
    raw = SETUP.read_bytes()
    raw.decode("ascii")                             # raises on any non-ASCII byte
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "a bare LF line ending in a batch file"
    assert b"\r" not in raw.replace(b"\r\n", b""), "a bare CR in a batch file"


def test_git_checks_the_setup_file_out_with_crlf():
    if not shutil.which("git"):
        pytest.skip("git is not on this machine")
    r = subprocess.run(["git", "check-attr", "eol", "--", SETUP.name], cwd=str(REPO_ROOT),
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=60)
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    assert r.stdout.decode("utf-8").strip().endswith("eol: crlf")


def test_it_names_what_it_installs_and_starts():
    text = _text()
    assert "Python.Python.3.13" in text
    assert "--scope user" in text
    assert "winget install -e --id Python.Python.3.13 --scope user" in text
    assert "--accept-package-agreements" in text and "--accept-source-agreements" in text
    assert "-m pip install -r requirements.txt" in text
    assert "Moonglade Launcher.pyw" in text
    assert "pythonw.exe" in text
    assert "--check" in text


def test_it_says_how_to_install_python_by_hand_when_winget_cannot():
    text = _text()
    assert 'start "" "https://www.python.org/downloads/"' in text
    assert "Add python.exe to PATH" in text
    assert "pause" in text.lower()


def test_it_quotes_every_path_it_prints():
    # An unquoted `echo ... %~dp0` runs whatever follows an "&" in a folder name (and eats a "^").
    for line in _text().splitlines():
        if line.lstrip().lower().startswith("echo") and ("%~dp0" in line or "%PYEXE%" in line):
            assert '"%~dp0' in line or '"%PYEXE%"' in line, line


def test_it_says_when_python_was_just_installed_not_that_nothing_needed_installing():
    text = _text()
    assert 'set "INSTALLED=1"' in text
    assert "if defined INSTALLED echo  Step 2 of 4: Python is installed." in text
    assert "if not defined INSTALLED echo  Step 2 of 4: Python is ready, nothing to install." in text


def test_it_reads_the_probe_back_in_the_consoles_code_page():
    # A user name with an accent puts a non-ASCII letter in the Python path. Python writes the
    # probe file in the ANSI page unless told otherwise, and "for /f" reads it in the console's
    # CURRENT code page (what chcp shows), which is the OEM page only until something changes it
    # (a console set to UTF-8, an AutoRun chcp). So the probe asks the console, and falls back to
    # the OEM page only when there is no console or no codec for its page.
    text = _text()
    assert "GetConsoleOutputCP()" in text
    assert "reconfigure(encoding=" in text and "else 'oem')" in text


def test_it_says_what_to_do_next_time():
    text = _text()
    assert "Moonglade is opening in your browser." in text
    assert "Next time, just double-click Moonglade Launcher." in text


def test_it_never_needs_administrator_rights():
    low = _text().lower()
    for forbidden in ("--scope machine", "scope machine", "runas", "-verb", "gsudo", "psexec",
                      "sudo ", "net session", "reg add hklm", "start-process"):
        assert forbidden not in low, forbidden


def test_it_does_not_trust_the_stale_path_after_installing_python():
    # The window's PATH was read before the install, so the new Python is found by where a
    # per-user install puts it, not by PATH.
    text = _text()
    assert r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe" in text
    assert r"%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" in text
    assert r"%SystemRoot%\py.exe" in text


def test_it_only_counts_a_python_that_prints_its_version_and_is_310_or_newer():
    # The Store's "python" is a stub that opens the Store: running it with -c prints no path
    # and exits nonzero, so a Python counts only if this probe succeeds.
    text = _text()
    assert "sys.version_info" in text and "(3, 10)" in text
    assert "sys.executable" in text


def _live_docs():
    docs = [REPO_ROOT / "README.md", REPO_ROOT / "CONTRIBUTING.md"] + sorted((REPO_ROOT / "wiki").glob("*.md"))
    return [(d, d.read_text(encoding="utf-8")) for d in docs]


def test_every_live_doc_states_the_same_python_minimum_the_setup_file_enforces():
    # The setup file accepts a Python 3.10 or newer; a doc that says 3.9 sends someone with a
    # 3.9 to a setup that then refuses it. (CHANGELOG.md is history and may say what it said.)
    assert "(3, 10)" in _text()
    for doc, text in _live_docs():
        assert not re.search(r"Python 3\.9|python-3\.9|3\.9\+", text), "%s still says Python 3.9" % doc.name
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "python-3.10%2B" in readme
    setup_doc = (REPO_ROOT / "wiki" / "Setup.md").read_text(encoding="utf-8")
    assert "Python 3.10 or newer (`python --version`)" in setup_doc


def test_the_setup_doc_says_the_setup_file_does_not_run_from_a_network_share():
    setup_doc = (REPO_ROOT / "wiki" / "Setup.md").read_text(encoding="utf-8")
    assert "network share" in setup_doc and r"\\server\share" in setup_doc
    assert "copy the folder to the PC first" in setup_doc


# ---- running it (Windows only) ----------------------------------------------------------------

def _run(script, args="", cwd=None, env=None, timeout=300, codepage=None):
    """`cmd /s /c ""<script>" <args>"`, the quoting that survives a space in the file's name, with
    no stdin so a `pause` or `timeout` ends at once.

    `codepage` runs it in a console of its own (no window) set to that code page with `chcp`,
    whatever console this test run inherited: a run from a UTF-8 console and one from a plain
    OEM-437 console must both pass, and `chcp` on the inherited console would change it for
    everything else attached to it."""
    flags = 0
    if codepage:
        # "chcp 437>nul" would redirect handle 7 and leave the page at 43, so the space matters
        cmd = 'cmd /s /c "chcp %d >nul & "%s" %s"' % (codepage, script, args)
        flags = subprocess.CREATE_NO_WINDOW
    else:
        cmd = 'cmd /s /c ""%s" %s"' % (script, args)
    r = subprocess.run(cmd, cwd=str(cwd or script.parent), env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
                       creationflags=flags)
    try:
        text = r.stdout.decode("cp%d" % codepage if codepage else "oem", errors="replace")   # the console's own page
    except LookupError:
        text = r.stdout.decode("cp437", errors="replace")
    return r.returncode, text


def _found_path(out):
    """The python.exe the setup file reported, or None when it found none."""
    lines = [ln.rstrip() for ln in out.splitlines()]
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Found Python ") and ln.rstrip().endswith(":") and i + 1 < len(lines):
            return lines[i + 1].strip().strip('"')            # the path is printed in quotes
    return None


@WINDOWS
def test_check_reports_what_it_found_and_installs_nothing():
    code, out = _run(SETUP, "--check")
    assert code == 0, out
    assert "[check]" in out and "Nothing was installed or started." in out
    # none of the real steps ran
    assert "Step 3 of 4" not in out and "Step 4 of 4" not in out
    assert "Collecting" not in out and "Successfully installed" not in out
    assert "Moonglade is opening in your browser." not in out
    found = _found_path(out)
    if found is None:
        # No Python 3.10+ on this machine's PATH or py launcher: it says so and what it would do.
        assert "No usable Python 3.10 or newer was found" in out
        assert "winget" in out or "python.org" in out
        return
    assert os.path.isfile(found), out
    assert found.lower().endswith("python.exe")
    # the path it reported really is a Python 3.10 or newer
    probe = subprocess.run([found, "-c", "import sys; print(sys.version_info[:2] >= (3, 10))"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=60)
    assert probe.stdout.decode().strip() == "True"
    assert "-m pip install -r requirements.txt" in out
    assert "Moonglade Launcher.pyw" in out


@WINDOWS
def test_check_leaves_no_probe_file_behind(tmp_path):
    # Its own TEMP, so another run's probe (a parallel test, a second double-click) can't count.
    env = dict(os.environ, TEMP=str(tmp_path), TMP=str(tmp_path))
    code, out = _run(SETUP, "--check", env=env)
    assert code == 0, out
    assert not list(tmp_path.glob("moonglade_probe*")), list(tmp_path.iterdir())


def test_each_check_has_its_own_probe_folder():
    # Two runs at once (a double double-click, or tests in parallel) used to share one fixed probe
    # file in %TEMP%, so one could read or delete the other's answer. A %RANDOM% name alone is not
    # enough: cmd seeds %RANDOM% from the clock in whole seconds, so windows started in the same
    # second draw the same numbers. Each check makes its own folder with mkdir, which succeeds for
    # one process only, and retries a capped number of times.
    text = SETUP.read_text(encoding="utf-8")
    sub = text[text.index(":new_probe"):]
    assert 'mkdir "%PROBEDIR%"' in sub and "goto :new_probe_try" in sub
    assert "lss 50" in sub                                         # never loops forever
    assert 'rmdir /s /q "%PROBEDIR%"' in text                     # and cleans up after reading


@WINDOWS
def test_two_checks_started_together_each_find_their_own_python(tmp_path):
    """Two setup windows in the same second, each with a different Python first on PATH, must each
    report their own: the shared probe file let one read the other's answer."""
    import concurrent.futures as cf
    pys = []
    for name in ("one", "two"):
        venv_dir = tmp_path / ("py " + name)
        made = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=300)
        py = venv_dir / "Scripts" / "python.exe"
        if made.returncode != 0 or not py.is_file():
            pytest.skip("could not make a venv here")
        pys.append(py)
    apps = []
    for name in ("one", "two"):
        app = tmp_path / ("app " + name)
        app.mkdir()
        (app / SETUP.name).write_bytes(SETUP.read_bytes())
        (app / "requirements.txt").write_text("# none\n", encoding="utf-8")
        (app / "Moonglade Launcher.pyw").write_text("", encoding="utf-8")
        apps.append(app)
    system32 = os.path.join(os.environ["SystemRoot"], "System32")
    for _round in range(4):
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(_run, apps[i] / SETUP.name, "--check",
                                env=dict(os.environ, PATH=str(pys[i].parent) + os.pathsep + system32))
                    for i in range(2)]
            results = [f.result() for f in futs]
        for i, (code, out) in enumerate(results):
            assert code == 0, out
            assert _found_path(out) == str(pys[i]), out


@WINDOWS
def test_check_says_where_it_is_when_the_file_is_moved_out_of_the_app_folder(tmp_path):
    lone = tmp_path / SETUP.name
    lone.write_bytes(SETUP.read_bytes())
    code, out = _run(lone, "--check")
    assert code == 1
    assert "has to stay in the Moonglade folder" in out
    assert "extract the whole zip first" in out                   # run from inside the downloaded zip
    assert "Collecting" not in out


@WINDOWS
def test_check_survives_a_folder_name_with_spaces_parentheses_and_an_ampersand(tmp_path):
    app = tmp_path / "My Apps (x86) & Co ^ 100%"
    app.mkdir()
    (app / SETUP.name).write_bytes(SETUP.read_bytes())
    (app / "requirements.txt").write_text("# none\n", encoding="utf-8")
    (app / "Moonglade Launcher.pyw").write_text("", encoding="utf-8")
    code, out = _run(app / SETUP.name, "--check")
    assert "is not recognized" not in out, out                   # the text after the "&" never runs
    assert code == 0, out
    assert 'Folder: "%s\\"' % app in out, out                    # printed whole, ^ and & included
    if _found_path(out) is not None:
        assert '"%s"' % (app / "Moonglade Launcher.pyw") in out   # the start line carries the full path


@WINDOWS
@pytest.mark.parametrize("codepage", [437, 65001], ids=["console-437", "console-utf8"])
def test_check_accepts_a_python_whose_path_has_an_accented_letter(tmp_path, codepage):
    # Each code page is forced on a console of the run's own (see _run), not read off the console
    # this test run inherited: the probe file is written and read back in whichever page is set.
    try:
        "é".encode("cp%d" % codepage)
    except (LookupError, UnicodeEncodeError):
        pytest.skip("this console's code page has no e-acute")
    venv_dir = tmp_path / "José Python"
    made = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=300)
    py = venv_dir / "Scripts" / "python.exe"
    if made.returncode != 0 or not py.is_file():
        pytest.skip("could not make a venv here")
    app = tmp_path / "app"
    app.mkdir()
    (app / SETUP.name).write_bytes(SETUP.read_bytes())
    (app / "requirements.txt").write_text("# none\n", encoding="utf-8")
    (app / "Moonglade Launcher.pyw").write_text("", encoding="utf-8")
    # python on PATH is the accented one; the py launcher is not on this PATH at all
    env = dict(os.environ, PATH=str(py.parent) + os.pathsep
               + os.path.join(os.environ["SystemRoot"], "System32"))
    code, out = _run(app / SETUP.name, "--check", env=env, codepage=codepage)
    assert code == 0, out
    assert _found_path(out) == str(py), out


@WINDOWS
def test_a_whole_run_installs_the_requirements_and_starts_the_launcher_with_pythonw(tmp_path):
    """The real path, in a scratch folder: an empty requirements.txt (so pip has nothing to fetch)
    and a stub launcher that writes a marker, so nothing real is installed or opened."""
    app = tmp_path / "app"
    app.mkdir()
    (app / SETUP.name).write_bytes(SETUP.read_bytes())
    (app / "requirements.txt").write_text("# nothing to install\n", encoding="utf-8")
    (app / "Moonglade Launcher.pyw").write_text(
        "import os, pathlib, sys\n"
        "here = pathlib.Path(__file__).resolve().parent\n"
        "(here / 'started.txt').write_text(os.path.basename(sys.executable) + '\\n'"
        " + os.getcwd(), encoding='utf-8')\n", encoding="utf-8")
    code, out = _run(app / SETUP.name)
    if _found_path(out) is None:
        pytest.skip("no Python 3.10+ is reachable from cmd.exe on this machine")
    assert code == 0, out
    assert "Step 3 of 4" in out and "The packages are installed." in out
    assert "Moonglade is opening in your browser." in out
    marker = app / "started.txt"
    deadline = time.time() + 30
    while not marker.exists() and time.time() < deadline:
        time.sleep(0.25)
    assert marker.exists(), out
    exe_name = marker.read_text(encoding="utf-8").splitlines()[0].lower()
    assert exe_name in ("pythonw.exe", "python.exe")
    if os.path.isfile(os.path.join(os.path.dirname(_found_path(out)), "pythonw.exe")):
        assert exe_name == "pythonw.exe", "the launcher must start without a console window"


@WINDOWS
def test_a_failed_pip_says_so_shows_the_command_and_stops_before_starting(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / SETUP.name).write_bytes(SETUP.read_bytes())
    (app / "requirements.txt").write_text("this-package-does-not-exist-moonglade-test==99.0\n",
                                          encoding="utf-8")
    (app / "Moonglade Launcher.pyw").write_text(
        "import pathlib\n"
        "(pathlib.Path(__file__).parent / 'started.txt').write_text('x')\n", encoding="utf-8")
    code, out = _run(app / SETUP.name, timeout=600)
    if _found_path(out) is None:
        pytest.skip("no Python 3.10+ is reachable from cmd.exe on this machine")
    assert code == 1, out
    assert "Installing the packages did not work." in out
    assert "-m pip install -r requirements.txt" in out
    assert "Press any key to continue" in out                    # it pauses so the window stays
    assert "Moonglade is opening in your browser." not in out
    time.sleep(1)
    assert not (app / "started.txt").exists()
