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

SERVE_ARGS = ["--out", "pixai_backup"]     # add "--host", "0.0.0.0" for LAN, "--port", "5001", etc.
PORT = 5000                                 # keep in sync with any --port above (for the browser open)
RESTART_CODE = 42                           # child exit code that means "relaunch me"

cmd = [sys.executable, os.path.join(here, "pixai_gallery.py")] + SERVE_ARGS
env = dict(os.environ, MOONGLADE_SUPERVISED="1")


def _open_browser_once():
    time.sleep(2.0)                 # give the first server a moment to bind
    try:
        webbrowser.open("http://localhost:{}/".format(PORT))
    except Exception:
        pass


first = True
while True:
    proc = subprocess.Popen(cmd, env=env, cwd=here)
    if first:
        threading.Thread(target=_open_browser_once, daemon=True).start()
        first = False
    rc = proc.wait()                # blocks until the child fully exits (frees the port)
    if rc == RESTART_CODE:
        time.sleep(0.6)             # let the socket release before rebinding
        continue                    # relaunch
    break                           # 0 = stop; anything else = crash/killed -> supervisor exits
