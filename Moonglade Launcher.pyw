#!/usr/bin/env pythonw
"""Moonglade Athenaeum — web launcher + supervisor (no desktop GUI).

Double-click to start the web gallery and open it in your browser, with NO terminal
window (.pyw runs under pythonw.exe). This is the "click to launch straight into the
web interface" entry point.

It runs as a tiny SUPERVISOR: it starts the web server (`python -m moonglade.gallery`, from
this folder) as a child and watches it.
That's what makes the browser Stop / Restart buttons (Control Panel -> Server) work
like Homebridge -- no Task Manager, no terminal:
  * Restart from the web UI  -> the child exits with code 42, and this loop relaunches it.
  * Stop from the web UI      -> the child exits 0, the loop ends, everything closes.
The child is told it's supervised via MOONGLADE_SUPERVISED=1 (so it enables Restart).

Background maintenance (the Control Panel scheduler + job runner) runs inside the server,
so you don't need the desktop app to keep the archive current.

Before anything else it gets the install ready (moonglade.setup.prepare): an update from an
older version brings its settings into local\\settings.json and its files into their homes.
The library, bind host, port, LAN discovery and launch switches are all settings.json's, set
from the Control Panel; the server reads them itself, so nothing is passed on its command
line. The server's console output goes to local\\logs\\serve.log.
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser

# This file's own folder IS the app folder (moonglade.paths.APP_ROOT), spelled by
# os.path.abspath as it always was here -- not resolve(), which would turn a mapped or subst
# drive into its target -- so the working directory stays byte-for-byte what it was. It goes
# on sys.path first so the moonglade package imports however the launcher was started; every
# other path comes from moonglade.paths.
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
from moonglade import paths as _paths    # noqa: E402

os.chdir(here)                     # so config.json / pixai_backup resolve here


def _serve_log_path():
    """local\\logs\\serve.log: the server's console output, and the launcher's own lines."""
    return _paths.logs_dir() / "serve.log"


def _stop(message):
    """Say plainly why Moonglade cannot start, where a person will see it, and stop. Under
    pythonw there is no console, so it is a Windows message box (and a line in serve.log when
    that can be written); elsewhere, stderr."""
    text = "Moonglade couldn't get ready to start.\n\n" + message
    try:
        log = _serve_log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(str(log), "a", encoding="utf-8") as f:
            f.write("[launcher] " + text.replace("\n\n", " ") + "\n")
    except Exception:                                   # noqa: BLE001 -- the box still shows
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Moonglade Athenaeum", 0x10)
        except Exception:                               # noqa: BLE001
            pass
    try:
        sys.stderr.write(text + "\n")                   # None under pythonw
    except Exception:                                   # noqa: BLE001
        pass
    sys.exit(1)


# Get the install ready FIRST (B2), before anything reads a setting: under the install's lock,
# merge the settings into local\settings.json and bring this install's own files into their
# homes, then the library's half under the library's lock (moonglade.setup.prepare). A start
# that cannot get ready never carries on -- it would read settings the move had not brought
# across yet (a lock another start held past its wait, a file in use): MoveStopped's text is
# the sentence to show, and anything else failing in there (an import included) stops it too.
try:
    from moonglade import setup as _setup
    _ready = _setup.prepare("launcher")
except SystemExit as e:
    if e.code in (None, 0):
        raise
    _stop(e.code if isinstance(e.code, str) else "It stopped with code %s." % e.code)
except Exception as e:                                  # noqa: BLE001 -- said, then stopped
    _stop(str(e) or e.__class__.__name__)

# The server is started with no arguments on purpose: it reads the library, host, port and
# launch switches from local\settings.json itself (moonglade.settings), and a flag here would
# beat the stored setting -- which is precisely why the Control Panel's folder field could not
# work while this launcher passed `--out`. A Restart (exit 42) runs the same command, so a
# setting the Control Panel just changed is read fresh by the new server.
RESTART_CODE = 42                           # child exit code that means "relaunch me"

# The port for the single-instance probe and the browser-open: the one the server will bind,
# from the same settings (the Control Panel's Bonjour chip writes it).
from moonglade import settings as _settings    # noqa: E402
PORT = _settings.server()["port"]

# Single instance: if a Moonglade server is ALREADY answering on this port, don't start a second
# one (on Windows SO_REUSEADDR lets two servers bind the same port and fight) -- just focus the
# browser and bow out.
#
# We identify "ours" by the X-Moonglade response header, NOT a 200 status. /api/ping now sits
# behind the login gate, so an unauthenticated probe (this launcher holds no session) gets a
# 401 -- and urllib RAISES urllib.error.HTTPError on 401. The old code checked `status == 200`
# under a bare `except`, so the raised 401 was swallowed as "nothing there" and a SECOND server
# was started every single time one was already running. The header rides every response,
# including that 401, so it still identifies our own server; a response without it is some other
# service on this port, and a connection error is nothing at all.
import urllib.request
import urllib.error


def _moonglade_on_port(port):
    """True iff one of OUR servers is already answering on `port` (any HTTP status)."""
    url = "http://localhost:{}/api/ping".format(port)
    try:
        with urllib.request.urlopen(url, timeout=1.5) as _r:
            return _r.headers.get("X-Moonglade") is not None
    except urllib.error.HTTPError as _e:      # answered with a status (e.g. the 401 gate) -> up
        return _e.headers.get("X-Moonglade") is not None
    except Exception:                          # refused / timeout / DNS -> nothing of ours there
        return False


if _moonglade_on_port(PORT):
    try:
        webbrowser.open("http://localhost:{}/".format(PORT))
    except Exception:
        pass
    sys.exit(0)

# The server runs as the package's module (3.20), from this folder: `-m` finds the moonglade
# package through the working directory, which is why cwd=here below matters.
cmd = [sys.executable, "-m", "moonglade.gallery"]
env = dict(os.environ, MOONGLADE_SUPERVISED="1")


def _open_when_ready():
    """Open the browser ONLY once the server actually answers -- a big backup builds thumbnails
    for several seconds before it binds the port, so a fixed delay opened the browser too early
    ('connection refused'). Poll up to 2 minutes, then open.

    Uses the SAME header check as the single-instance guard above: the gated /api/ping answers
    an unauthenticated probe with 401, which urllib raises. The old `urlopen ... break` treated
    that raise as 'not ready yet' and polled the full two minutes before opening the browser --
    so the window opened ~2 min late against a server that was up in seconds. Keying on the
    header fixes that too."""
    deadline = time.time() + 120
    while time.time() < deadline:
        if _moonglade_on_port(PORT):
            break                   # server is up
        time.sleep(0.5)
    try:
        webbrowser.open("http://localhost:{}/".format(PORT))
    except Exception:
        pass


# Capture the child's stdout/stderr to local\logs\serve.log so a boot failure isn't silent under
# pythonw (no console). stdin=DEVNULL so the headless child never blocks on input.
#
# The log trims itself, once per launcher start (not on a Restart): over 1 MB it becomes
# serve.log.1, the older ones shift to .2 and .3, and the oldest is dropped. After the
# single-instance check above, so a second launcher never touches a running server's log.
# Best effort: nothing here can stop the app starting.
_serve_log = _serve_log_path()
try:
    _serve_log.parent.mkdir(parents=True, exist_ok=True)
    from moonglade import logs as _mlog
    _mlog.rotate_by_size(_serve_log)
except Exception:
    pass
try:
    _log = open(str(_serve_log), "a", buffering=1, encoding="utf-8")
except OSError:
    _log = subprocess.DEVNULL
# What getting ready did, in the one log the launcher has, when it has a line to say.
try:
    _said = _ready.summary() if hasattr(_ready, "summary") else ""
    if _said and _log is not subprocess.DEVNULL:
        _log.write("[launcher] " + str(_said) + "\n")
except Exception:                                       # noqa: BLE001 -- a log line only
    pass


def _repoint_shortcuts():
    """Shortcuts that still point at this install's old launcher (Serve Gallery.pyw, gone
    since 3.20) or take their icon from an old icon cache are re-pointed, without asking:
    the first start after an update from 3.19 or older finds them broken already, so nothing
    could be worse (moonglade.outside.repoint_shortcuts). What it did goes in serve.log."""
    try:
        from moonglade import outside as _outside
        for r in _outside.repoint_shortcuts():
            if _log is not subprocess.DEVNULL:
                _log.write("[launcher] " + r.line() + "\n")
    except Exception:                                   # noqa: BLE001 -- never stops a start
        pass


# Off the start's path: the server starts while the shortcuts are looked at.
if sys.platform == "win32":
    threading.Thread(target=_repoint_shortcuts, daemon=True,
                     name="moonglade-shortcuts").start()

first = True
while True:
    proc = subprocess.Popen(cmd, env=env, cwd=here,
                            stdin=subprocess.DEVNULL, stdout=_log, stderr=_log)
    if first:
        threading.Thread(target=_open_when_ready, daemon=True).start()
        first = False
    rc = proc.wait()                # blocks until the child fully exits (frees the port)
    if rc == RESTART_CODE:
        time.sleep(0.6)             # let the socket release before rebinding
        continue                    # relaunch
    break                           # 0 = stop; anything else = crash/killed -> supervisor exits
