#!/usr/bin/env pythonw
"""Moonglade Athenaeum — web launcher + supervisor (no desktop GUI).

Double-click to start the web gallery and open it in your browser, with NO terminal
window (.pyw runs under pythonw.exe). This is the "click to launch straight into the
web interface" entry point.

It runs as a tiny SUPERVISOR: it starts pixai_gallery.py as a child and watches it.
That's what makes the browser Stop / Restart buttons (Control Panel -> Server) work
like Homebridge -- no Task Manager, no terminal:
  * Restart from the web UI  -> the child exits with code 42, and this loop relaunches it.
  * Stop from the web UI      -> the child exits 0, the loop ends, everything closes.
The child is told it's supervised via MOONGLADE_SUPERVISED=1 (so it enables Restart).

Background maintenance (the Control Panel scheduler + job runner) runs inside the server,
so you don't need the desktop app to keep the archive current.

Tweak SERVE_ARGS / PORT below to change the folder or port, or add "--host", "0.0.0.0" for LAN.
Make a shortcut: right-click -> Send to -> Desktop (create shortcut); set moonglade.ico if you like.
"""
import os
import subprocess
import sys
import threading
import time
import webbrowser

here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)                     # so config.json / pixai_backup resolve here
sys.path.insert(0, here)

SERVE_ARGS = ["--out", "pixai_backup"]     # base args (folder). Extra flags go in serve.txt (below).
RESTART_CODE = 42                           # child exit code that means "relaunch me"

# Machine-local overrides WITHOUT editing this tracked file (so `git pull` never conflicts):
# put extra flags in an untracked "serve.txt" next to this launcher, e.g. one line:
#     --host 0.0.0.0 --port 5757
# (LAN access + a custom port). Whitespace-separated; blank/missing = defaults.
_serve_txt = os.path.join(here, "serve.txt")
if os.path.exists(_serve_txt):
    try:
        SERVE_ARGS += open(_serve_txt, encoding="utf-8").read().split()
    except OSError:
        pass

# Port for the browser-open (parsed from whatever --port ended up in the args; default 5000).
PORT = 5000
if "--port" in SERVE_ARGS:
    try:
        PORT = int(SERVE_ARGS[SERVE_ARGS.index("--port") + 1])
    except (ValueError, IndexError):
        pass

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

cmd = [sys.executable, os.path.join(here, "pixai_gallery.py")] + SERVE_ARGS
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


# Capture the child's stdout/stderr to serve.log so a boot failure isn't silent under pythonw
# (no console). stdin=DEVNULL so the headless child never blocks on input.
try:
    _log = open(os.path.join(here, "serve.log"), "a", buffering=1, encoding="utf-8")
except OSError:
    _log = subprocess.DEVNULL

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
