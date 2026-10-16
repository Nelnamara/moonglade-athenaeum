"""The packages Moonglade needs, found missing and installed before the app starts (issue #87).

Moonglade Launcher runs this before the server exists, so this module may import ONLY the
standard library -- not requests, not flask, and nothing from the moonglade package that
imports them (a test reads this file's imports and holds it to that).

  * requirements(path)  the names a requirements file asks for
  * missing(path)       the names of those whose package is not installed in THIS Python
  * install_command / manual_command / console_python   the pip command, for the launcher to
                        run and for a person to paste
  * install(path, log_path)   run it, with no window, and report what pip said

It judges presence only, never versions: a package that is installed but too old is the
one-click update's business (moonglade.gallery's _pip_install), not a reason to stop a start.
"""
import importlib
import importlib.metadata
import operator
import os
import re
import subprocess
import sys
from pathlib import Path

# The most pip may take before the launcher gives up on it.
TIMEOUT_S = 900
# How many of pip's last lines come back to be shown in a message.
TAIL_LINES = 15

# Win32 CREATE_NO_WINDOW (what subprocess.CREATE_NO_WINDOW is on Windows only), so pip does not
# flash a console under pythonw.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
# The one marker that is judged: python_version <op> "X.Y" and nothing else.
_PYTHON_VERSION = re.compile(
    r"""python_version\s*(<=|>=|==|!=|~=|<|>)\s*(["'])(\d+(?:\.\d+)*)\2""")
_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
        "==": operator.eq, "!=": operator.ne}


def _marker_holds(marker):
    """Does a line's environment marker hold on this Python? Only `python_version <op> "X.Y"`
    is judged; a marker of any other shape (a platform, a compound) counts as true, so a line
    the app may need is never left off."""
    marker = marker.strip()
    if not marker:
        return True
    m = _PYTHON_VERSION.fullmatch(marker)
    if not m:
        return True
    op, want = m.group(1), tuple(int(p) for p in m.group(3).split("."))
    have = tuple(sys.version_info[:2])
    if op == "~=":                       # compatible release: at least `want`, same leading parts
        return have >= want[:2] and have[:len(want) - 1] == want[:-1]
    return _OPS[op](have, want)


def _norm(name):
    """A package name the way pip compares them: case, "-", "_" and "." all alike."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements(path):
    """The package names a requirements file asks for, in file order, each once.

    Blank lines, comments (a line's own or a `#` after a space), `-r` / `-e` / other option
    lines, bare URLs and paths are skipped; version specifiers, extras and `name @ url` tails
    are stripped. A line whose `python_version` marker is false on this Python is skipped
    (see _marker_holds)."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    names, seen = [], set()
    for line in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if not line or line.startswith("-") or _URL.match(line):
            continue
        spec, _, marker = line.partition(";")
        m = _NAME.match(spec.strip())
        if not m or not _marker_holds(marker):
            continue
        name = m.group(0)
        if _norm(name) not in seen:
            seen.add(_norm(name))
            names.append(name)
    return names


def _installed(name):
    """Is a distribution of this name installed? The name is tried as written, then in the
    spellings pip treats as the same package (lower case, "-" for "_" and back)."""
    spellings = [name, name.lower(), name.lower().replace("_", "-"),
                 name.lower().replace("-", "_")]
    for spelling in dict.fromkeys(spellings):
        try:
            importlib.metadata.distribution(spelling)
            return True
        except importlib.metadata.PackageNotFoundError:
            continue
    return False


def missing(path):
    """The names in a requirements file whose package is not installed in this Python.
    Presence only: no version is compared."""
    return [name for name in requirements(path) if not _installed(name)]


def install_command(path):
    """The pip command the launcher runs: this Python's own pip, never a bare `pip` (which on
    Windows can easily belong to a different Python)."""
    return [sys.executable, "-m", "pip", "install", "-r", str(path)]


def console_python():
    """The Python a person should type: pythonw.exe has no console to show pip's output in, so
    the python.exe beside it is named when that file exists; otherwise sys.executable."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def _quoted(word):
    """A word of a command as typed: in double quotes only when it holds a space."""
    return '"%s"' % word if " " in word else word


def _paste(*words):
    """A command a person can paste. With nothing to quote it is one line, which Command Prompt
    and PowerShell both run. With a quoted word, PowerShell needs a leading "&" and Command
    Prompt must not have one, so each gets its own labelled line."""
    typed = " ".join(_quoted(w) for w in words)
    if not any(" " in w for w in words):
        return typed
    return "In Command Prompt: %s\nIn PowerShell: & %s" % (typed, typed)


def manual_command(path):
    """The command (see _paste) a person can paste to install the packages by hand: this
    Python, and the requirements file by its full path."""
    return _paste(console_python(), "-m", "pip", "install", "-r", os.path.abspath(str(path)))


def ensurepip_command():
    """The command (see _paste) that gives a Python with no pip its pip."""
    return _paste(console_python(), "-m", "ensurepip")


def _tail(text, lines=TAIL_LINES):
    kept = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(kept[-lines:])


def install(path, log_path):
    """Run install_command(path) from the app's folder (the requirements file's), with no
    console window and a 15-minute limit; pip's output is appended to log_path. Returns
    (return code, the last lines pip printed). Never raises: a pip that could not be started
    or did not finish comes back as a nonzero code with the reason."""
    cmd = install_command(path)
    try:
        done = subprocess.run(
            cmd, cwd=os.path.dirname(os.path.abspath(str(path))),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
            creationflags=_NO_WINDOW)
        code, said = done.returncode, done.stdout or ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        code, said = 1, (out or "") + "\npip did not finish in %d minutes and was stopped." % (
            TIMEOUT_S // 60)
    except Exception as e:                                  # noqa: BLE001 -- returned, not raised
        code, said = 1, "%s: %s" % (type(e).__name__, str(e)[:300])
    try:
        with open(str(log_path), "a", encoding="utf-8") as f:
            f.write("[launcher] pip: {}\n{}\n[launcher] pip ended with code {}\n".format(
                " ".join(cmd), said.rstrip(), code))
    except Exception:                                       # noqa: BLE001 -- a log line only
        pass
    importlib.invalidate_caches()           # the packages just landed: let the next check see them
    return code, _tail(said)
