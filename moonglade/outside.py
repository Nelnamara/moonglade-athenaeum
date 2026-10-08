"""moonglade/outside.py -- things outside the app that still name this install's old files,
found and fixed (DECISIONS 2026-10-07, pick 5).

3.20 took every .py file off the install root and renamed the launcher. Three kinds of thing
outside the app can still name the old files, and each stops working, silently, once they go:

  * a Windows Task Scheduler task running this install's moonglade_backup.py,
    moonglade_gallery.py or Serve Gallery.pyw (read with `schtasks /query /xml ONE`);
  * a Claude MCP registration running this install's moonglade_mcp.py: Claude Desktop's
    claude_desktop_config.json, and Claude Code's ~/.claude.json (its user scope, and each
    project's);
  * a .lnk shortcut on the Desktop, in the Start menu or pinned to the taskbar (this user's,
    and the ones shared by all users) whose target or arguments name this install's old
    launcher or files, or whose icon sits in one of this install's icon caches.

find() lists them; fix() rewrites each to the new names:

  Serve Gallery.pyw      -> Moonglade Launcher.pyw, in the same folder
  moonglade_backup.py    -> the code folder: python "<install>\\moonglade" <same args>
  moonglade_gallery.py   -> python -m moonglade.gallery <same args>, started in the install
  moonglade_mcp.py       -> <its Python> -m moonglade.mcp_server (-P added only when that
                            Python is 3.11 or later), with PYTHONPATH=<install> added to the
                            registration's own env (the rest kept)
  an icon in an old icon cache (_container_cache\\, local\\cache\\) -> the same .ico in
                            local\\icons\\ (moonglade.paths.icons_dir()), which is no cache

The rules:
  * Only THIS install's files are matched (moonglade.paths.APP_ROOT, or `install`); a
    reference to another install's files is left alone. A bare or .\\ file name counts only
    where the thing starts in this install's folder; a Claude registration that names the old
    file that way without saying it starts here is reported, never rewritten on a guess.
  * A Claude registration is rewritten only when it runs Python itself (or the old file by
    its type). Its own Python is asked first (its version, and whether it has fastmcp): -P is
    written only for 3.11 or later, and one that cannot run the tools is reported with the
    command line to use, never written. "Fixed" means the file was re-read and holds the new
    command; Claude then needs a restart to use it.
  * A Claude config can hold keys and tokens, so it never goes into the install's snapshot:
    a copy is kept beside it (as private as the file itself) and removed once the rewrite is
    read back. The file is re-read just before it is replaced, so a change Claude made
    meanwhile is never lost: the rewrite starts again from it.
  * A task's XML and a shortcut are copied into local\\.snapshot\\outside\\ before they change
    (and the safety snapshot's clean-start count starts again, so the copy is kept five clean
    starts on). Every file is rewritten whole: a temp file beside it, then one os.replace.
  * Every item comes back as fixed or failed, with a plain reason. Nothing here raises.
  * Off Windows, only the Claude configs are looked at.
  * repoint_shortcuts() is the launcher's own pass, at every start and without asking: it
    fixes only shortcuts that start this install's old launcher, now gone, so nothing it does
    can make a shortcut worse. One Windows won't let this user change is left for the notice
    (and its Fix button's plain reason), not tried again at every start. A shortcut whose only
    fault is its icon is offered in the notice. A temp a killed save left beside a shortcut is
    swept.

Everything that touches the machine goes through a Machine (where the folders are, how a
command runs, how a .lnk is saved), so the tests hand in one built on temp folders and fake
commands; machine() builds the real one, and dev/tests/conftest.py refuses it in every test.
"""
import codecs
import json
import logging
import ntpath
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from moonglade import paths as _paths

# A child of the app's own logger, which moonglade.logs lets through to the file at every
# level: what was fixed, and what could not be, with why.
LOGGER_NAME = "moonglade.outside"

OLD_LAUNCHER = "Serve Gallery.pyw"
OLD_SERVER = "moonglade_gallery.py"
OLD_CLI = "moonglade_backup.py"
OLD_MCP = "moonglade_mcp.py"
NEW_LAUNCHER = _paths.LAUNCHER_NAME
CODE_FOLDER = "moonglade"
SERVER_MODULE = "-m moonglade.gallery"

# The old names a command line (a task, a shortcut) can carry, and the one a Claude
# registration can.
COMMAND_NAMES = (OLD_LAUNCHER, OLD_SERVER, OLD_CLI)
MCP_NAMES = (OLD_MCP,)

# This install's old icon caches, under its root: a shortcut's icon in one of them is moved to
# icons_dir() (the 3.19 cache, and 3.20's first local\cache\ -- both rebuilt or deleted).
OLD_ICON_FOLDERS = ("_container_cache", "local\\cache")

SNAPSHOT_DIRNAME = ".snapshot"
SNAPSHOT_SUBDIR = "outside"

TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_NS = {"t": TASK_NS}
# A task registered to run with a saved Windows password cannot be registered again without
# it, and only the owner has it.
_PASSWORD_LOGONS = ("Password", "InteractiveTokenOrPassword")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_PY = re.compile(r"^(?:py|pyw|python(?:\d+(?:\.\d+)*)?w?)(?:\.exe)?$", re.I)


# ---- the machine ----------------------------------------------------------------------------

class Machine:
    """Where this machine keeps the things outside the app, and how to talk to Windows.

    platform          sys.platform's answer ("win32" turns on tasks and shortcuts)
    shortcut_folders  [(folder, where, recursive)]: where .lnk files are looked for, and the
                      words that say where ("on your Desktop")
    claude_configs    [(path, who)]: the Claude config files, and whose ("Claude Desktop")
    run(argv)         -> (returncode, stdout bytes, stderr text); runs schtasks
    save_lnk(path, target, args, workdir, icon)
                      rewrites the .lnk at `path` in place; a field given as None is left as
                      it is (icon: "path,index")
    python            the interpreter a rewritten command names when the old one ran a .py by
                      its file type (python.exe beside the one running the app)
    probe(argv)       -> {"version": (major, minor), "fastmcp": bool}, or None when `argv`
                      (a Python and its own options) cannot be started: asked of a Claude
                      registration's Python before it is rewritten
    """

    def __init__(self, platform=None, shortcut_folders=(), claude_configs=(), run=None,
                 save_lnk=None, python=None, probe=None):
        self.platform = platform or sys.platform
        self.shortcut_folders = list(shortcut_folders)
        self.claude_configs = list(claude_configs)
        self.run = run or _run
        self.save_lnk = save_lnk or _save_lnk_with_powershell
        self.python = python or _console_python()
        self.probe = probe or _probe_python

    @property
    def windows(self):
        return self.platform == "win32"


def machine():
    """This machine, for real: its known folders, its Claude configs, schtasks and
    PowerShell. dev/tests/conftest.py replaces this with a refusal for every test."""
    platform = sys.platform
    home = Path.home()
    folders, configs = [], []
    if platform == "win32":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        pinned = _known_folder("user_pinned") or (
            Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned")
        folders = [
            (desktop_dir(), "on your Desktop", False),
            (_known_folder("public_desktop"), "on the Desktop for all users", False),
            (_known_folder("programs") or Path(appdata) / "Microsoft" / "Windows" / "Start Menu"
             / "Programs", "in your Start menu", True),
            (_known_folder("common_programs"), "in the Start menu for all users", True),
            (pinned / "TaskBar", "pinned to your taskbar", False),
        ]
        configs.append((Path(appdata) / "Claude" / "claude_desktop_config.json",
                        "Claude Desktop"))
    elif platform == "darwin":
        configs.append((home / "Library" / "Application Support" / "Claude"
                        / "claude_desktop_config.json", "Claude Desktop"))
    else:
        configs.append((home / ".config" / "Claude" / "claude_desktop_config.json",
                        "Claude Desktop"))
    configs.append((home / ".claude.json", "Claude Code"))
    return Machine(platform=platform, shortcut_folders=[f for f in folders if f[0]],
                   claude_configs=configs)


def _console_python():
    """python.exe beside the interpreter running the app (pythonw.exe when the launcher runs
    it): a rewritten scheduled command keeps the console the old .py file type gave it."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


_PROBE_CODE = ("import sys, importlib.util as u; "
               "print('%d.%d %d' % (sys.version_info[0], sys.version_info[1], "
               "u.find_spec('fastmcp') is not None))")


def _probe_python(argv):
    """Ask the Python `argv` names (with its own options, e.g. ["py", "-3.12"]) its version and
    whether it has fastmcp, without importing anything else. None when it cannot be started
    or says something else."""
    rc, out, _err = _run(list(argv) + ["-c", _PROBE_CODE], timeout=30)
    if rc != 0:
        return None
    m = re.match(r"^\s*(\d+)\.(\d+) ([01])\s*$", _decode(out))
    if not m:
        return None
    return {"version": (int(m.group(1)), int(m.group(2))), "fastmcp": m.group(3) == "1"}


def _run(argv, timeout=60):
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, b"", str(e)
    return r.returncode, r.stdout or b"", _decode(r.stderr or b"").strip()


# The shell's known folders (Windows), so a Desktop moved into OneDrive is still found.
_KNOWN_FOLDERS = {
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "public_desktop": "C4AA340D-F20F-4863-AFEF-F87EF2E6BA25",
    "programs": "A77F5D77-2E2B-44C3-A6A2-ABA601054A51",
    "common_programs": "0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8",
    "user_pinned": "9E3995AB-1F9C-4F13-B827-48B24B6C7174",
}


def _known_folder(name):
    """A shell known folder's path, or None (not Windows, or the shell said no)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID(_KNOWN_FOLDERS[name])
        guid = GUID(u.time_low, u.time_mid, u.time_hi_version,
                    (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        shell32, ole32 = ctypes.WinDLL("shell32"), ctypes.WinDLL("ole32")
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                                 wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.c_wchar_p)]
        out = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) != 0:
            return None
        try:
            return Path(out.value) if out.value else None
        finally:
            ole32.CoTaskMemFree(out)
    except Exception:                                   # noqa: BLE001 -- a folder not found
        return None


def desktop_dir():
    """This user's Desktop, where the shell really keeps it (a Desktop moved into OneDrive
    included); %USERPROFILE%\\Desktop when the shell cannot say."""
    return _known_folder("desktop") or Path.home() / "Desktop"


# ---- what was found, what was done ---------------------------------------------------------

class Item:
    """One thing outside the app that names this install's old files."""

    def __init__(self, kind, key, label, data, auto=False):
        self.kind = kind          # "task" | "claude" | "shortcut"
        self.key = key            # the task's name, the config's path, the shortcut's path
        self.label = label        # plain words: the scheduled task “Moonglade sync”
        self.data = data          # what fix() needs
        self.auto = auto          # a shortcut the launcher may fix without asking

    def as_dict(self):
        return {"kind": self.kind, "key": self.key, "label": self.label}


class Result:
    def __init__(self, label, fixed, reason="", note=""):
        self.label = label
        self.fixed = bool(fixed)
        self.reason = reason
        self.note = note          # what the person does next ("Restart Claude to use it.")

    def as_dict(self):
        return {"label": self.label, "fixed": self.fixed, "reason": self.reason,
                "note": self.note}

    def line(self):
        if self.fixed:
            return "Fixed %s.%s" % (self.label, (" " + self.note) if self.note else "")
        return "Couldn't fix %s: %s." % (self.label, self.reason)


def _and(words):
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _cap(text):
    return text[:1].upper() + text[1:]


def fix_label(items):
    """The notice's button: "Fix it" for one thing, "Fix them" for several."""
    return "Fix it" if len(list(items)) == 1 else "Fix them"


def notice_words(items):
    """(title, message) for the app's one notice about `items`, worded for one or several."""
    items = list(items)
    labels = [i.label for i in items]
    if len(labels) == 1:
        return (_cap(labels[0]) + " still uses Moonglade's old file names.",
                "Press Fix it to point it at the new names.")
    return ("Some things outside Moonglade still use its old file names.",
            "They are " + _and(labels) + ". Press Fix them to point them at the new names.")


def result_words(results):
    """(kind, title, message) for what fix() did: kind "ok" when every item was fixed."""
    fixed = [r for r in results if r.fixed]
    failed = [r for r in results if not r.fixed]
    notes = []
    for r in results:
        if r.note and r.note not in notes:
            notes.append(r.note)
    tail = (" " + " ".join(notes)) if notes else ""
    if not results:
        return ("ok", "Nothing to fix.",
                "Nothing outside Moonglade names its old files any more.")
    if not failed:
        head = _cap(_and(r.label for r in fixed))
        return ("ok", "Fixed.", (head + " now use the new names."
                                 if len(fixed) > 1 else head + " now uses the new names.") + tail)
    parts = []
    if fixed:
        parts.append("Fixed " + _and(r.label for r in fixed) + ".")
    parts += ["Couldn't fix %s: %s." % (r.label, r.reason) for r in failed]
    return ("err", "Some couldn't be fixed." if fixed else "Couldn't fix them.",
            " ".join(parts) + tail)


# ---- paths, Windows style ------------------------------------------------------------------

def _clean(p):
    return str(p or "").strip().strip('"')


def _nt(p):
    """A path compared the way Windows compares it: separators and case folded."""
    return ntpath.normcase(ntpath.normpath(_clean(p))) if _clean(p) else ""


def _same(a, b):
    return bool(_nt(a)) and _nt(a) == _nt(b)


def _inside(path, folder):
    p, f = _nt(path), _nt(folder)
    return bool(p and f) and p.startswith(f.rstrip("\\") + "\\")


def _path_pattern(folder):
    """A regex for `folder` written with either separator, any case."""
    s = str(folder).rstrip("\\/")
    lead = ""
    if s.startswith(("\\\\", "//")):
        lead = r"[\\/]{2}"
    elif s[:1] in ("\\", "/"):
        lead = r"[\\/]"
    parts = [p for p in re.split(r"[\\/]+", s) if p]
    return lead + r"[\\/]+".join(re.escape(p) for p in parts)


def _ref_pattern(install, names):
    """Where a command line names one of `names`: this install's path, or no path (a bare
    name), then the name. It must start a word (the line's start, a space, a quote, `=`) and
    end one, so another folder's file of the same name never matches."""
    alts = "|".join(re.escape(n) for n in names)
    return re.compile(
        r'(?<![^\s"\'=,(])(?P<q>")?'
        r'(?P<prefix>' + _path_pattern(install) + r'[\\/]+|\.[\\/]+)?'
        r'(?P<name>' + alts + r')(?P<q2>")?(?=$|[\s"\'),;&|<>])', re.I)


def _canonical(name, names):
    return next(n for n in names if n.lower() == name.lower())


def _quote(s):
    s = str(s)
    return '"%s"' % s if (" " in s or not s) and not s.startswith('"') else s


def _interpreter_before(line, pos, command):
    """True when the word before `pos` (options skipped) is a Python interpreter, or there is
    none and the command itself is one: the old file was run by Python, not by its type."""
    for tok in reversed(re.findall(r'"[^"]*"|\S+', line[:pos])):
        if tok.startswith("-"):
            continue
        return bool(_PY.match(ntpath.basename(_clean(tok))))
    return bool(_PY.match(ntpath.basename(_clean(command))))


class _Rewrite:
    """A command (an executable, its arguments, the folder it starts in) with this install's
    old names rewritten. `refs` names the old files it named; `problem` is set when it names
    one in a shape the app will not rewrite on a guess."""

    def __init__(self, command, arguments, workdir):
        self.command, self.arguments, self.workdir = command, arguments, workdir
        self.refs = []
        self.problem = ""

    @property
    def changed(self):
        return bool(self.refs) and not self.problem


def rewrite_command(command, arguments, workdir, install, python):
    """Rewrite one command for this install's new names. Never raises."""
    command, arguments, workdir = command or "", arguments or "", workdir or ""
    out = _Rewrite(command, arguments, workdir)
    in_install = _same(workdir, install)
    needs_install_dir = False
    # 1. The command IS an old file, started by its file type.
    exe = _clean(command)
    exe_path = exe if (ntpath.isabs(exe) or not workdir) else ntpath.join(_clean(workdir), exe)
    base = ntpath.basename(exe).lower()
    if exe and base in (n.lower() for n in COMMAND_NAMES) and (
            _same(ntpath.dirname(exe_path), install)):
        name = _canonical(ntpath.basename(exe), COMMAND_NAMES)
        out.refs.append(name)
        folder = ntpath.dirname(exe)
        if name == OLD_LAUNCHER:
            out.command = ntpath.join(folder, NEW_LAUNCHER) if folder else NEW_LAUNCHER
        elif name == OLD_CLI:
            out.command = python
            code = ntpath.join(folder, CODE_FOLDER) if folder else CODE_FOLDER
            out.arguments = (_quote(code) + " " + arguments).strip()
        else:
            out.command = python
            out.arguments = (SERVER_MODULE + " " + arguments).strip()
            needs_install_dir = True
    # 2. The arguments name an old file.
    else:
        pat = _ref_pattern(install, COMMAND_NAMES)

        def repl(m):
            nonlocal needs_install_dir
            prefix = m.group("prefix") or ""
            if (not prefix or prefix.startswith(".")) and not in_install:
                return m.group(0)                        # a bare name in another folder
            name = _canonical(m.group("name"), COMMAND_NAMES)
            q, q2 = m.group("q") or "", m.group("q2") or ""
            out.refs.append(name)
            if name == OLD_LAUNCHER:
                return q + prefix + NEW_LAUNCHER + q2
            by_python = _interpreter_before(arguments, m.start(), command)
            # Started by its file type here (cmd /c ...\moonglade_backup.py): the folder has
            # none, so Python is named in front of it -- but never inside an outer string's
            # lone quote, where the nesting would be a guess.
            if not by_python and bool(q) != bool(q2):
                out.problem = ("its command line is quoted in a way the app won't rewrite "
                               "on a guess")
                return m.group(0)
            lead = "" if by_python else _quote(python) + " "
            if name == OLD_CLI:
                return lead + q + prefix + CODE_FOLDER + q2
            needs_install_dir = True
            if q and q2:
                return lead + SERVER_MODULE
            return lead + q + SERVER_MODULE + q2         # a lone quote belongs to an outer string

        out.arguments = pat.sub(repl, arguments)
    if needs_install_dir and not out.problem:
        if not _clean(workdir):
            out.workdir = str(install)
        elif not in_install:
            out.problem = ("it starts in another folder, and the server only starts from the "
                           "app's own folder")
    return out


# ---- Task Scheduler ------------------------------------------------------------------------

def _decode(raw):
    """Text from a Windows tool's bytes: UTF-16 when it says so (or looks like it), else
    UTF-8, else the console's code page."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16", "replace")
    if len(raw) > 1 and raw[1:2] == b"\x00":
        return raw.decode("utf-16-le", "replace")
    for enc in ("utf-8", "oem", "mbcs"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("latin-1")


def parse_tasks(text):
    """[(name, task XML)] from `schtasks /query /xml ONE`: each <Task> follows a comment
    holding its name."""
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"<!--\s*(.*?)\s*-->\s*(<Task\b.*?</Task>)", text, re.S)]


def _task_xml(text):
    m = re.search(r"<Task\b.*?</Task>", text, re.S)
    return m.group(0) if m else ""


def _parse_task(xml):
    """A task's XML as Windows wrote it, parsed; None for anything else. A task never carries
    a DOCTYPE, so one that does is refused before the parser sees it (no entity expansion)."""
    if not xml or "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        return None
    try:
        return ET.fromstring(xml)
    except ET.ParseError:
        return None


def _execs(root):
    return root.findall(".//t:Actions/t:Exec", _NS)


def _exec_fields(ex):
    def get(tag):
        el = ex.find("t:" + tag, _NS)
        return (el.text or "") if el is not None else ""
    return get("Command"), get("Arguments"), get("WorkingDirectory")


def _set_field(ex, tag, value):
    el = ex.find("t:" + tag, _NS)
    if not value:
        if el is not None and tag != "Command":
            ex.remove(el)
        return
    if el is None:
        el = ET.SubElement(ex, "{%s}%s" % (TASK_NS, tag))
    el.text = value


def _rewrite_task(root, install, python):
    """Rewrite every Exec action of a parsed task. Returns (refs, problem)."""
    refs, problem = [], ""
    for ex in _execs(root):
        command, arguments, workdir = _exec_fields(ex)
        rw = rewrite_command(command, arguments, workdir, install, python)
        refs += rw.refs
        if rw.problem:
            problem = problem or rw.problem
            continue
        if rw.changed:
            _set_field(ex, "Command", rw.command)
            _set_field(ex, "Arguments", rw.arguments)
            _set_field(ex, "WorkingDirectory", rw.workdir)
    return refs, problem


def _task_label(name):
    return "the scheduled task “%s”" % name.lstrip("\\")


def find_tasks(install, m):
    if not m.windows:
        return []
    rc, out, _err = m.run(["schtasks", "/query", "/xml", "ONE"])
    if rc != 0:
        return []
    found = []
    for name, xml in parse_tasks(_decode(out)):
        root = _parse_task(xml)
        if root is None:
            continue
        refs, _problem = _rewrite_task(root, install, m.python)
        if refs:
            found.append(Item("task", name, _task_label(name), {"name": name}))
    return found


def _why_windows_refused(text):
    low = (text or "").lower()
    if "denied" in low:
        return "Windows refused: changing it needs administrator rights"
    return "Windows said: " + (text.strip().splitlines() or ["no reason given"])[0][:160]


def fix_task(item, install, m, snapshot):
    name = item.data["name"]
    rc, out, err = m.run(["schtasks", "/query", "/tn", name, "/xml"])
    if rc != 0:
        return Result(item.label, False, "Windows couldn't read it (" + (err or "no reason") + ")")
    xml = _task_xml(_decode(out))
    root = _parse_task(xml)
    if root is None:
        return Result(item.label, False, "Windows gave back something that isn't a task")
    logon = root.find(".//t:Principals/t:Principal/t:LogonType", _NS)
    if logon is not None and (logon.text or "").strip() in _PASSWORD_LOGONS:
        return Result(item.label, False,
                      "it runs with a saved Windows password, which only you can give "
                      "Task Scheduler again")
    refs, problem = _rewrite_task(root, install, m.python)
    if problem:
        return Result(item.label, False, problem)
    if not refs:
        return Result(item.label, True)                  # already right
    _snapshot_bytes(snapshot, "task-" + name.strip("\\").replace("\\", "-") + ".xml",
                    xml.encode("utf-8"))
    # The task namespace written as the default one, the way Windows writes it (the task's
    # own attributes are unqualified, which tostring's default_namespace refuses).
    ET.register_namespace("", TASK_NS)
    body = ET.tostring(root, encoding="unicode")
    fd, tmp = tempfile.mkstemp(prefix="moonglade-task-", suffix=".xml")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(('<?xml version="1.0" encoding="UTF-16"?>\r\n' + body).encode("utf-16"))
        rc, _out, err = m.run(["schtasks", "/create", "/tn", name, "/xml", tmp, "/f"])
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if rc != 0:
        return Result(item.label, False, _why_windows_refused(err))
    return Result(item.label, True)


# ---- Claude's MCP registrations ------------------------------------------------------------

RESTART_CLAUDE = "Restart Claude to use it."
_MODULE_ARGS = ["-m", "moonglade.mcp_server"]


def _mcp_args(version=None):
    """The rewritten registration's arguments. -P (Python 3.11+) keeps the client's working
    folder off sys.path, and is written only for a Python known to be 3.11 or later: an older
    one refuses it and the tools would not start. PYTHONPATH names the app either way."""
    return (["-P"] if version is not None and tuple(version) >= (3, 11) else []) + _MODULE_ARGS


def _with_install(pythonpath, install, platform):
    sep = ";" if platform == "win32" else ":"
    parts = [p for p in (pythonpath or "").split(sep) if p]
    if any(_same(p, install) for p in parts):
        return pythonpath
    return sep.join([str(install)] + parts)


def _how_to_run(install):
    return ("set it to run your Python with -m moonglade.mcp_server, and PYTHONPATH set to %s"
            % install)


class _McpPlan:
    """What one mcpServers entry needs. `new` is the rewritten entry (None: nothing to write);
    `problem` says why an entry naming this install's old file is left as it is."""

    def __init__(self, new=None, problem=""):
        self.new, self.problem = new, problem


def _old_script_arg(args, install, cwd):
    """(index, "this" | "unsure") of the argument naming moonglade_mcp.py, or None. A full
    path counts only inside this install; a bare or .\\ name only when the registration says it
    starts in this install (its cwd), and is otherwise "unsure": it would match every install."""
    target = ntpath.join(str(install), OLD_MCP)
    for i, a in enumerate(args):
        if not isinstance(a, str):
            continue
        if _same(a, target):
            return i, "this"
        name = _clean(a)
        base = ntpath.basename(name.replace("/", "\\"))
        if base.lower() != OLD_MCP.lower():
            continue
        if ntpath.isabs(name) or name.startswith(("\\\\", "//")):
            continue                                     # another folder's file
        if not cwd:
            return i, "unsure"
        whole = ntpath.normpath(ntpath.join(_clean(cwd), name))
        return (i, "this") if _same(whole, target) else None
    return None


def rewrite_mcp_server(spec, install, python, platform, probe=None):
    """What to do with one mcpServers entry: an _McpPlan, or None when it does not name this
    install's moonglade_mcp.py. With `probe` (fix time) the registration's own Python is asked
    its version and whether it has fastmcp; without it (find time) only the shape is judged.
    Never raises."""
    if not isinstance(spec, dict):
        return None
    command = spec.get("command") if isinstance(spec.get("command"), str) else ""
    args = spec.get("args") if isinstance(spec.get("args"), list) else []
    cwd = spec.get("cwd") if isinstance(spec.get("cwd"), str) else ""
    target = ntpath.join(str(install), OLD_MCP)
    if command and _same(command, target):
        interpreter, before, after = [python], [], list(args)
    else:
        found = _old_script_arg(args, install, cwd)
        if found is None:
            return None
        i, whose = found
        if whose == "unsure":
            return _McpPlan(problem=(
                "it names moonglade_mcp.py without saying which folder it starts in, so the "
                "app can't tell it is this install's; " + _how_to_run(install)))
        if not command or not _PY.match(ntpath.basename(_clean(command))):
            return _McpPlan(problem=(
                "it starts through %s, which the app won't rewrite on a guess; %s" % (
                    ntpath.basename(_clean(command)) or "another program", _how_to_run(install))))
        interpreter, before, after = [command], list(args[:i]), list(args[i + 1:])
    version = None
    if probe is not None:
        info = probe(interpreter + before)
        who = " ".join(interpreter + before)
        if info is None:
            return _McpPlan(problem="its Python (%s) couldn't be started; %s" % (
                who, _how_to_run(install)))
        if not info.get("fastmcp"):
            return _McpPlan(problem=(
                "its Python (%s) doesn't have fastmcp, which the tools need; install it there "
                "(pip install fastmcp), then press Fix again" % who))
        version = info.get("version")
    new = dict(spec)
    new["command"] = interpreter[0]
    new["args"] = before + _mcp_args(version) + after
    env = dict(spec.get("env") or {}) if isinstance(spec.get("env") or {}, dict) else {}
    env["PYTHONPATH"] = _with_install(env.get("PYTHONPATH"), install, platform)
    new["env"] = env
    return _McpPlan(new=new)


def _mcp_tables(doc):
    """Every mcpServers table in a Claude config: the top level (Claude Desktop, and Claude
    Code's user scope) and each of Claude Code's projects."""
    tables = []
    if isinstance(doc, dict):
        if isinstance(doc.get("mcpServers"), dict):
            tables.append(doc["mcpServers"])
        projects = doc.get("projects")
        if isinstance(projects, dict):
            for proj in projects.values():
                if isinstance(proj, dict) and isinstance(proj.get("mcpServers"), dict):
                    tables.append(proj["mcpServers"])
    return tables


def _rewrite_claude_doc(doc, install, python, platform, probe=None):
    """Rewrite `doc`'s registrations of this install's old file in place. Returns
    (rewritten, problems): how many entries were rewritten, and why the others were not."""
    n, problems = 0, []
    for table in _mcp_tables(doc):
        for name, spec in list(table.items()):
            plan = rewrite_mcp_server(spec, install, python, platform, probe)
            if plan is None:
                continue
            if plan.new is not None:
                table[name] = plan.new
                n += 1
            elif plan.problem not in problems:
                problems.append(plan.problem)
    return n, problems


def _read_json(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    return text, json.loads(text)


def find_claude(install, m):
    found = []
    for path, who in m.claude_configs:
        try:
            if not Path(path).is_file():
                continue
            _text, doc = _read_json(path)
        except (OSError, ValueError):
            continue
        n, problems = _rewrite_claude_doc(doc, install, m.python, m.platform)
        if n or problems:
            found.append(Item("claude", str(path), "%s's Moonglade tools" % who,
                              {"path": str(path)}))
    return found


def _indent_of(text):
    m = re.search(r"\n([ \t]+)\S", text)
    if not m:
        return 2
    return m.group(1) if "\t" in m.group(1) else len(m.group(1))


def _backup_beside(path, data):
    """A copy of a Claude config as it was, beside it (never in the install: it can hold keys
    and tokens), made private to this user where the system allows (on Windows it takes the
    folder's own access list, the user's profile). Returns its path."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name("%s.moonglade-backup-%s-%s" % (path.name, stamp,
                                                           uuid.uuid4().hex[:6]))
    fd = os.open(str(backup), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        _drop(backup)
        raise
    return backup


_CLAIM_TRIES = 3


def fix_claude(item, install, m, snapshot=None):
    """Rewrite one Claude config's registrations of this install's old file. The file is
    re-read just before it is replaced: if Claude changed it meanwhile, the rewrite starts
    again from the new content, so neither write is lost. "Fixed" only once the file is read
    back holding the new command."""
    path = Path(item.data["path"])
    _sweep_own_temps(path.parent, path.name)
    for _attempt in range(_CLAIM_TRIES):
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            doc = json.loads(text)
        except (OSError, ValueError) as e:
            return Result(item.label, False, "its config couldn't be read (%s)" % _reason(e))
        n, problems = _rewrite_claude_doc(doc, install, m.python, m.platform, m.probe)
        if not n:
            if problems:
                return Result(item.label, False, "; ".join(problems))
            return Result(item.label, True)              # already right
        out = json.dumps(doc, indent=_indent_of(text), ensure_ascii=False)
        if text.endswith("\n"):
            out += "\n"
        try:
            backup = _backup_beside(path, raw)
        except OSError as e:
            return Result(item.label, False, "a copy couldn't be kept first (%s)" % _reason(e))
        try:
            if path.read_bytes() != raw:
                _drop(backup)                            # Claude wrote it meanwhile: again
                continue
            _write_atomically(path, out.encode("utf-8"))
        except OSError as e:
            _drop(backup)
            return Result(item.label, False, "its config couldn't be written (%s)" % _reason(e))
        try:
            _t, check = _read_json(path)
            left, _p = _rewrite_claude_doc(check, install, m.python, m.platform)
        except (OSError, ValueError):
            left = None
        if left == 0:
            _drop(backup)
            if problems:
                return Result(item.label, False, "; ".join(problems), note=RESTART_CLAUDE)
            return Result(item.label, True, note=RESTART_CLAUDE)
        return Result(item.label, False,
                      "Claude changed the file at the same moment; close Claude, then press "
                      "Fix again (the file as it was is kept beside it, as %s)" % backup.name)
    return Result(item.label, False,
                  "Claude kept changing the file; close Claude, then press Fix again")


# ---- shortcuts (.lnk) ------------------------------------------------------------------------

_LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")


def _ansi():
    try:
        codecs.lookup("mbcs")
        return "mbcs"
    except LookupError:
        return "latin-1"


def _cstr(data, at):
    end = data.find(b"\x00", at)
    return data[at:end if end >= 0 else len(data)].decode(_ansi(), "replace")


def _wstr(data, at):
    end = at
    while end + 1 < len(data) and data[end:end + 2] != b"\x00\x00":
        end += 2
    return data[at:end].decode("utf-16-le", "replace")


class Lnk:
    """What a .lnk says: its target, arguments, start-in folder and icon."""

    def __init__(self, target="", args="", workdir="", icon="", icon_index=0, relative=""):
        self.target, self.args, self.workdir = target, args, workdir
        self.icon, self.icon_index, self.relative = icon, icon_index, relative


def parse_lnk(data):
    """A Shell Link (.lnk, MS-SHLLINK) read without the shell: the target from its LinkInfo
    (or its environment-variable block, or its relative path), and its string fields. None
    for anything that is not one."""
    try:
        if len(data) < 76 or struct.unpack_from("<I", data, 0)[0] != 0x4C \
                or data[4:20] != _LNK_CLSID:
            return None
        u16 = lambda at: struct.unpack_from("<H", data, at)[0]          # noqa: E731
        u32 = lambda at: struct.unpack_from("<I", data, at)[0]          # noqa: E731
        flags = u32(20)
        icon_index = struct.unpack_from("<i", data, 56)[0]
        pos = 76
        if flags & 0x1:                                       # HasLinkTargetIDList
            pos += 2 + u16(pos)
        target = ""
        if flags & 0x2:                                       # HasLinkInfo
            size, head, li_flags = u32(pos), u32(pos + 4), u32(pos + 8)
            if li_flags & 0x1:                                # VolumeIDAndLocalBasePath
                base_at, suffix_at = u32(pos + 16), u32(pos + 24)
                base = _cstr(data, pos + base_at)
                suffix = _cstr(data, pos + suffix_at) if suffix_at else ""
                if head >= 0x24:
                    ubase, usuffix = u32(pos + 28), u32(pos + 32)
                    if ubase:
                        base = _wstr(data, pos + ubase)
                    if usuffix:
                        suffix = _wstr(data, pos + usuffix)
                target = base + suffix
            pos += size
        unicode = bool(flags & 0x80)
        fields = {}
        for bit, key in ((0x4, "name"), (0x8, "relative"), (0x10, "workdir"),
                         (0x20, "args"), (0x40, "icon")):
            if flags & bit:
                n = u16(pos)
                pos += 2
                if unicode:
                    fields[key] = data[pos:pos + 2 * n].decode("utf-16-le", "replace")
                    pos += 2 * n
                else:
                    fields[key] = data[pos:pos + n].decode(_ansi(), "replace")
                    pos += n
        env_target = env_icon = ""
        while pos + 8 <= len(data):
            size, sig = u32(pos), u32(pos + 4)
            if size < 8:
                break
            if sig in (0xA0000001, 0xA0000007) and size >= 0x314:
                wide = _wstr(data, pos + 8 + 260)
                value = wide or _cstr(data, pos + 8)
                if sig == 0xA0000001:
                    env_target = value
                else:
                    env_icon = value
            pos += size
        if not target and env_target:
            target = ntpath.expandvars(env_target)
        # Windows' own writer keeps the icon as %USERPROFILE%\...: read as the real path.
        icon = ntpath.expandvars(env_icon) if env_icon else fields.get("icon", "")
        return Lnk(target=target, args=fields.get("args", ""), workdir=fields.get("workdir", ""),
                   icon=icon, icon_index=icon_index, relative=fields.get("relative", ""))
    except (struct.error, IndexError, ValueError):
        return None


def read_lnk(path):
    try:
        p = Path(path)
        if p.stat().st_size > (1 << 20):
            return None
        lnk = parse_lnk(p.read_bytes())
    except OSError:
        return None
    if lnk is not None and not lnk.target and lnk.relative:
        lnk.target = ntpath.normpath(ntpath.join(str(p.parent), lnk.relative))
    return lnk


def _lnk_files(m):
    for folder, where, recursive in m.shortcut_folders:
        try:
            folder = Path(folder)
            if not folder.is_dir():
                continue
            found = folder.rglob("*.lnk") if recursive else folder.glob("*.lnk")
            for p in sorted(found):
                if p.is_file() and not p.name.startswith("."):
                    yield p, where
        except OSError:
            continue


def _old_icon(icon, install):
    icon = ntpath.expandvars(_clean(icon))
    return bool(icon) and any(_inside(icon, ntpath.join(str(install), sub))
                              for sub in OLD_ICON_FOLDERS)


def _shortcut_plan(lnk, install, python):
    """(rewrite, icon_moves) for one shortcut: icon_moves is True when its icon sits in an
    old icon cache."""
    rw = rewrite_command(lnk.target, lnk.args, lnk.workdir, install, python)
    return rw, _old_icon(lnk.icon, install)


def _gone(rw, install):
    """True when every old file the shortcut names is already gone from this install."""
    return all(not (Path(install) / n).exists() for n in set(rw.refs))


def _shortcut_label(p, where):
    return "the shortcut “%s” %s" % (p.stem, where)


def _icon_moved(old_icon, icons):
    """True when the .ico an old-cache icon names is already in `icons` (local\\icons\\): the
    move brings the old cache's .ico files there before it deletes the cache, so a shortcut
    whose only fault is that icon can still be pointed at its copy."""
    name = ntpath.basename(ntpath.expandvars(_clean(old_icon)))
    return bool(name) and (Path(icons) / name).is_file()


def find_shortcuts(install, m, icons=None):
    if not m.windows:
        return []
    icons = Path(icons) if icons is not None else _paths.icons_dir()
    found = []
    for p, where in _lnk_files(m):
        lnk = read_lnk(p)
        if lnk is None:
            continue
        rw, icon_moves = _shortcut_plan(lnk, install, m.python)
        if not rw.refs and not icon_moves:
            continue
        if rw.refs:
            # The launcher's own pass takes only a shortcut that starts this install's old
            # launcher, which is gone: nothing it does can make that one worse.
            auto = not rw.problem and OLD_LAUNCHER in rw.refs and _gone(rw, install)
        elif Path(ntpath.expandvars(_clean(lnk.icon))).is_file() or _icon_moved(lnk.icon, icons):
            auto = False            # its icon only: offered in the notice
        else:
            continue                # its icon is gone already: nothing there to move
        found.append(Item("shortcut", str(p), _shortcut_label(p, where),
                          {"path": str(p), "where": where}, auto=auto))
    return found


def _place_icon(old_icon, icons, provide_icon):
    """The shortcut's .ico in `icons` (copied from the old cache while it is still there, or
    asked of `provide_icon(stem)`), or None when it cannot be had: the icon is then left as
    it was rather than pointed at nothing."""
    name = ntpath.basename(ntpath.expandvars(_clean(old_icon)))
    if not name.lower().endswith(".ico") or not re.match(r"^[\w .()-]+$", name):
        return None
    dest = Path(icons) / name
    if dest.is_file():
        return dest
    data = None
    src = Path(ntpath.expandvars(_clean(old_icon)))
    try:
        if src.is_file():
            data = src.read_bytes()
    except OSError:
        data = None
    if data is None and provide_icon is not None:
        try:
            data = provide_icon(Path(name).stem)
        except Exception:                               # noqa: BLE001 -- no icon, no harm
            data = None
    if not data:
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(dest, data)
    except OSError:
        return None
    return dest


def fix_shortcut(item, install, m, snapshot, icons, provide_icon=None):
    """Re-point one shortcut. Only what changes is written: a shortcut whose only fault is its
    icon gets its icon and nothing else (its target, as this module reads it, may be less
    than Windows knows: a network share, a relative link). The new .lnk is made as a temp
    beside it first; a copy goes into the snapshot only once that worked, and is taken back
    if the save fails, so a refusal leaves nothing behind."""
    p = Path(item.data["path"])
    lnk = read_lnk(p)
    if lnk is None:
        return Result(item.label, False, "it couldn't be read")
    rw, icon_moves = _shortcut_plan(lnk, install, m.python)
    if rw.problem:
        return Result(item.label, False, rw.problem)
    icon = None
    if icon_moves:
        placed = _place_icon(lnk.icon, icons, provide_icon)
        if placed is not None:
            icon = "%s,%d" % (placed, lnk.icon_index)
    if not rw.changed and icon is None:
        if not rw.refs and not icon_moves:
            return Result(item.label, True)              # already right
        return Result(item.label, False, "its old icon is gone, so there is none to move")
    target = rw.command if rw.changed and rw.command != lnk.target else None
    args = rw.arguments if rw.changed and rw.arguments != lnk.args else None
    workdir = rw.workdir if rw.changed and rw.workdir != lnk.workdir else None
    tmp = p.with_name(".%s%s%s.lnk" % (p.stem, _TEMP_TAG, uuid.uuid4().hex[:8]))
    kept = None
    try:
        shutil.copy2(p, tmp)
        kept = _snapshot_file(snapshot, p)
        m.save_lnk(tmp, target, args, workdir, icon)
        os.replace(tmp, p)
    except PermissionError:
        _drop(tmp)
        _drop(kept)
        return Result(item.label, False, "Windows refused: changing it needs administrator rights")
    except Exception as e:                              # noqa: BLE001 -- reported, never raised
        _drop(tmp)
        _drop(kept)
        return Result(item.label, False, _reason(e))
    return Result(item.label, True)


def _save_lnk_with_powershell(path, target, args, workdir, icon):
    """Rewrite the .lnk at `path` through the shell's own WScript.Shell, the way the app's
    shortcut button writes one (moonglade.gallery.make_launcher_shortcut). A field given as
    None is left as the shortcut has it."""
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    ps = "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s); " % q(path)
    for field, value in (("TargetPath", target), ("Arguments", args),
                         ("WorkingDirectory", workdir), ("IconLocation", icon)):
        if value is not None:
            ps += "$s.%s = %s; " % (field, q(value))
    ps += "$s.Save()"
    rc, _out, err = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    if rc != 0:
        raise RuntimeError("Windows couldn't save it (%s)" % ((err or "PowerShell failed")[:160]))


# The tag this module's own temp files carry: .<name>.moonglade-<hex>.lnk beside a shortcut,
# .<name>.moonglade-<hex>.tmp beside a config. One a killed save left is swept.
_TEMP_TAG = ".moonglade-"
TEMP_SWEEP_AGE_S = 60.0


def _sweep_own_temps(folder, name=None):
    """Remove this module's own temp files a killed save left in `folder` (older than a
    minute, so a save in progress is never touched). Never raises."""
    try:
        now = time.time()
        for f in Path(folder).iterdir():
            n = f.name
            if not n.startswith(".") or _TEMP_TAG not in n:
                continue
            if name is not None and not n.startswith("." + name + _TEMP_TAG):
                continue
            if not re.search(re.escape(_TEMP_TAG) + r"[0-9a-f]{8}\.(lnk|tmp)$", n):
                continue
            try:
                if now - f.stat().st_mtime > TEMP_SWEEP_AGE_S:
                    os.remove(f)
            except OSError:
                continue
    except OSError:
        pass


# ---- files: the snapshot and whole rewrites --------------------------------------------------

def snapshot_dir():
    """local\\.snapshot\\outside\\: where a task's XML or a shortcut is copied before the app
    changes it (never a Claude config: fix_claude keeps that copy beside the file). It goes
    with the move's own snapshot."""
    return _paths.local_dir() / SNAPSHOT_DIRNAME / SNAPSHOT_SUBDIR


def _kept_for_a_while(snapshot):
    """A copy just went into `snapshot`: the folder holding .snapshot\\ counts its clean
    starts again from here (moonglade.migrate.reset_clean_starts), so the copy is not deleted
    at the very next one. Only where the move keeps a journal. Never raises."""
    try:
        holder = Path(snapshot).parent.parent
        if (holder / _paths.JOURNAL_NAME).is_file():
            from moonglade import migrate as _migrate
            _migrate.reset_clean_starts(holder)
    except Exception:                                   # noqa: BLE001 -- bookkeeping only
        pass


def _safe_name(name):
    return re.sub(r"[^\w.()-]+", "_", name).strip("._") or "file"


def _snapshot_target(snapshot, name):
    snapshot.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return snapshot / ("%s-%s-%s" % (stamp, uuid.uuid4().hex[:6], _safe_name(name)))


def _snapshot_file(snapshot, path):
    target = _snapshot_target(snapshot, Path(path).name)
    shutil.copy2(path, target)
    _kept_for_a_while(snapshot)
    return target


def _snapshot_bytes(snapshot, name, data):
    _snapshot_target(snapshot, name).write_bytes(data)
    _kept_for_a_while(snapshot)


def _write_atomically(path, data):
    path = Path(path)
    tmp = path.with_name(".%s%s%s.tmp" % (path.name, _TEMP_TAG, uuid.uuid4().hex[:8]))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        _drop(tmp)
        raise


def _drop(p):
    if p is None:
        return
    try:
        os.remove(p)
    except OSError:
        pass


def _reason(e):
    if isinstance(e, PermissionError):
        return "in use or not allowed"
    return str(getattr(e, "strerror", None) or e) or e.__class__.__name__


# ---- the three calls -------------------------------------------------------------------------

_FINDERS = {"task": find_tasks, "claude": find_claude, "shortcut": find_shortcuts}


def find(install=None, m=None, kinds=("task", "claude", "shortcut"), icons=None):
    """Everything outside the app that names this install's old files. Never raises. `icons`:
    the shortcut-icon folder (icons_dir() by default), where an old-cache icon may already be."""
    install = Path(install or _paths.APP_ROOT)
    m = m or machine()
    found = []
    for kind in kinds:
        try:
            if kind == "shortcut":
                found += find_shortcuts(install, m, icons)
            else:
                found += _FINDERS[kind](install, m)
        except Exception:                               # noqa: BLE001 -- the others still count
            continue
    return found


def fix(items=None, install=None, m=None, snapshot=None, icons=None, provide_icon=None):
    """Fix `items` (by default everything find() finds now). One Result per item, in order.
    Never raises."""
    install = Path(install or _paths.APP_ROOT)
    m = m or machine()
    snapshot = Path(snapshot) if snapshot is not None else snapshot_dir()
    icons = Path(icons) if icons is not None else _paths.icons_dir()
    items = find(install, m, icons=icons) if items is None else items
    results = []
    for item in items:
        try:
            if item.kind == "task":
                r = fix_task(item, install, m, snapshot)
            elif item.kind == "claude":
                r = fix_claude(item, install, m, snapshot)
            else:
                r = fix_shortcut(item, install, m, snapshot, icons, provide_icon)
        except Exception as e:                          # noqa: BLE001 -- reported, never raised
            r = Result(item.label, False, _reason(e))
        logging.getLogger(LOGGER_NAME).log(logging.INFO if r.fixed else logging.WARNING,
                                           "outside the app: %s", r.line())
        results.append(r)
    return results


def repoint_shortcuts(install=None, m=None, snapshot=None, icons=None, provide_icon=None):
    """The launcher's pass, at every start, without asking: re-point the shortcuts whose old
    target is already gone (the first start after an update from 3.19 or older, when the old
    launcher's name has just disappeared) and move icons out of the old caches. Shortcuts
    only, Windows only. Never raises."""
    m = m or machine()
    if not m.windows:
        return []
    for folder, _where, _recursive in m.shortcut_folders:
        _sweep_own_temps(folder)
    items = [i for i in find(install, m, kinds=("shortcut",), icons=icons)
             if i.auto and _may_change(i.data["path"])]
    return fix(items, install, m, snapshot, icons, provide_icon) if items else []


def _may_change(path):
    """Can this user change the shortcut at `path` (and make its temp beside it)? Asked
    before the launcher's pass tries, so one Windows refuses (a Desktop shared by all users,
    without administrator rights) is never tried again at every start, nor copied into the
    snapshot each time: the notice still offers it, with the reason."""
    p = Path(path)
    try:
        with open(p, "r+b"):
            pass
    except OSError:
        return False
    try:
        fd, probe = tempfile.mkstemp(prefix="." + p.stem + _TEMP_TAG, suffix=".probe",
                                     dir=str(p.parent))
    except OSError:
        return False
    os.close(fd)
    _drop(probe)
    return True
