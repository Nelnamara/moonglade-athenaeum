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

First it looks whether a Moonglade server already answers on the port this start will use
(read without changing anything: moonglade.setup.peek_server) and, if one does, only opens the
browser -- so a second double-click never moves files under a running server. Then it gets the
install ready (moonglade.setup.prepare): an update from an older version brings its settings
into local\\settings.json and its files into their homes, and what that did is written to
local\\logs\\moonglade.log, one line per file. The library, bind host, port, LAN discovery and
launch switches are all settings.json's, set from the Control Panel; the server reads them
itself, so nothing is passed on its command line. The server's console output goes to
local\\logs\\serve.log. A server that stops as it starts (a move it could not finish, a port
taken, a crash) is said in a message box, with the reason from serve.log.
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


def _bow_out_if_running(port):
    """One of our servers already answers on `port`: open the browser on it and stop."""
    if _moonglade_on_port(port):
        try:
            webbrowser.open("http://localhost:{}/".format(port))
        except Exception:
            pass
        sys.exit(0)


def _getting_ready(step):
    """Run one step of getting ready; a start that cannot get ready says why and stops.
    MoveStopped's text is the sentence to show, and anything else failing in there (an import
    included) stops it too."""
    try:
        return step()
    except SystemExit as e:
        if e.code in (None, 0):
            raise
        _stop(e.code if isinstance(e.code, str) else "It stopped with code %s." % e.code)
    except Exception as e:                              # noqa: BLE001 -- said, then stopped
        _stop(str(e) or e.__class__.__name__)


def _import_setup():
    from moonglade import setup
    return setup


# S1: the single-instance check comes BEFORE the move, so a second double-click never moves
# files under a running server. The port is read without changing anything: settings.json's,
# or the one an older version's settings are about to bring across (moonglade.setup.peek_server
# reads them the way the merge will).
_setup = _getting_ready(_import_setup)
_early_port = _getting_ready(lambda: _setup.peek_server()["port"])
_bow_out_if_running(_early_port)

# Get the install ready (B2), before anything reads a setting: under the install's lock, merge
# the settings into local\settings.json and bring this install's own files into their homes,
# then the library's half under the library's lock (moonglade.setup.prepare). A start that
# cannot get ready never carries on -- it would read settings the move had not brought across
# yet (a lock another start held past its wait, a file in use).
_ready = _getting_ready(lambda: _setup.prepare("launcher"))

# The server is started with no arguments on purpose: it reads the library, host, port and
# launch switches from local\settings.json itself (moonglade.settings), and a flag here would
# beat the stored setting -- which is precisely why the Control Panel's folder field could not
# work while this launcher passed `--out`. A Restart (exit 42) runs the same command, so a
# setting the Control Panel just changed is read fresh by the new server.
RESTART_CODE = 42                           # child exit code that means "relaunch me"
# A server that ends with anything but 0 or 42 this soon after it started never got going: the
# launcher says why in a message box (S10) instead of leaving a browser on a dead port.
BOOT_S = 30.0

# The port for the browser-open: the one the server will bind, from the same settings (the
# Control Panel's Bonjour chip writes it). The move can only have changed it on a first start
# after an update, and then the probe runs again.
from moonglade import settings as _settings    # noqa: E402
PORT = _settings.server()["port"]
if PORT != _early_port:
    _bow_out_if_running(PORT)

# The server runs as the package's module (3.20), from this folder: `-m` finds the moonglade
# package through the working directory, which is why cwd=here below matters.
cmd = [sys.executable, "-m", "moonglade.gallery"]
env = dict(os.environ, MOONGLADE_SUPERVISED="1")
# Set once the server has ended for good: the browser is then never opened on a dead port.
_server_gone = threading.Event()


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
        if _server_gone.is_set():
            return                  # it stopped as it started: the launcher says why
        if _moonglade_on_port(PORT):
            break                   # server is up
        time.sleep(0.5)
    if _server_gone.is_set():
        return
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
# What getting ready did: every line (one per file it moved, merged, set aside or removed)
# in local\logs\moonglade.log, where the docs say to look, and the overview in serve.log.
try:
    if hasattr(_ready, "write_log"):
        _ready.write_log()
    _said = _ready.summary() if hasattr(_ready, "summary") else ""
    if _said and _log is not subprocess.DEVNULL:
        _log.write("[launcher] " + str(_said) + "\n")
except Exception:                                       # noqa: BLE001 -- a log line only
    pass


def _why_it_stopped(rc):
    """The sentence for a server that stopped as it started: a move it could not finish says
    so on its own line in serve.log (moonglade.gallery.PREPARE_MARK); anything else is told by
    the log's last lines."""
    try:
        with open(str(_serve_log), encoding="utf-8", errors="replace") as f:
            tail = [ln.rstrip("\n") for ln in f.readlines()[-200:]]
    except OSError:
        tail = []
    marked = [ln.split("[prepare] ", 1)[1] for ln in tail if "[prepare] " in ln]
    if marked:
        return marked[-1]
    last = [ln.strip() for ln in tail if ln.strip()][-3:]
    text = "The server stopped as it started (code %s)." % rc
    if last:
        text += " The end of local\\logs\\serve.log says:\n\n" + "\n".join(last)
    return text


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
    _began = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, cwd=here,
                            stdin=subprocess.DEVNULL, stdout=_log, stderr=_log)
    if first:
        threading.Thread(target=_open_when_ready, daemon=True).start()
        first = False
    rc = proc.wait()                # blocks until the child fully exits (frees the port)
    if rc == RESTART_CODE:
        time.sleep(0.6)             # let the socket release before rebinding
        continue                    # relaunch
    _server_gone.set()
    if rc not in (0, None) and time.monotonic() - _began < BOOT_S:
        try:
            if _log is not subprocess.DEVNULL:
                _log.flush()
        except Exception:                               # noqa: BLE001
            pass
        _stop(_why_it_stopped(rc))
    break                           # 0 = stop; a crash after it ran -> supervisor exits
