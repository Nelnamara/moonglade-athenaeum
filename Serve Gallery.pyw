#!/usr/bin/env pythonw
"""Moonglade Athenaeum — web launcher + supervisor (no desktop GUI).

Double-click to start the web gallery and open it in your browser, with NO terminal
window and NO PySide6 GUI (.pyw runs under pythonw.exe). This is the "click to launch
straight into the web interface" entry point.

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
# browser and bow out. A 200 from /api/ping means it's ours; anything else -> start fresh.
import urllib.request
try:
    with urllib.request.urlopen("http://localhost:{}/api/ping".format(PORT), timeout=1.5) as _r:
        if _r.status == 200:
            try:
                webbrowser.open("http://localhost:{}/".format(PORT))
            except Exception:
                pass
            sys.exit(0)
except Exception:
    pass                            # nothing (of ours) there -> start it below

cmd = [sys.executable, os.path.join(here, "pixai_gallery.py")] + SERVE_ARGS
env = dict(os.environ, MOONGLADE_SUPERVISED="1")


def _open_when_ready():
    """Open the browser ONLY once the server actually answers -- a big backup builds thumbnails
    for several seconds before it binds the port, so a fixed delay opened the browser too early
    ('connection refused'). Poll /api/ping up to 2 minutes, then open."""
    import urllib.request
    ping = "http://localhost:{}/api/ping".format(PORT)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            urllib.request.urlopen(ping, timeout=1)
            break                   # server is up
        except Exception:
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
