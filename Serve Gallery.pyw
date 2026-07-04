#!/usr/bin/env pythonw
"""Moonglade Athenaeum — web launcher (no desktop GUI).

Double-click to start the web gallery server and open it in your default browser,
with NO terminal window and NO PySide6 GUI (.pyw runs under pythonw.exe on Windows).
This is the "click to launch straight into the web interface" entry point.

It just runs pixai_gallery.py's main() from this folder (so config.json and
pixai_backup/ resolve normally) with --open-browser. Background maintenance jobs
still run headless: the Control Panel's scheduler thread and its job runner live
inside the server itself, so you don't need the desktop app to keep the archive
current — only for the initial full download and a few power-tool maintenance ops.

Edit the SERVE_ARGS below to change the folder/port, or add --host 0.0.0.0 for LAN.
Make a shortcut: right-click -> Send to -> Desktop (create shortcut); set its icon
to moonglade.ico if you like.
"""
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)                     # so config.json / pixai_backup resolve here
sys.path.insert(0, here)

# What to serve. Tweak freely: point --out elsewhere, change --port, add --host 0.0.0.0.
SERVE_ARGS = ["--out", "pixai_backup", "--open-browser"]

sys.argv = [os.path.join(here, "pixai_gallery.py")] + SERVE_ARGS
runpy.run_path(os.path.join(here, "pixai_gallery.py"), run_name="__main__")
