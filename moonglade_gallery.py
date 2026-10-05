"""moonglade_gallery.py -- a stand-in for the web server. It stays for good.

The server moved to moonglade/gallery.py in 3.20, and the launcher (Serve Gallery.pyw) now
starts it as `python -m moonglade.gallery`. This file is for a launcher from before 3.20 that
is still running when the install updates: it built its command line once, when it started,
as `python <this folder>/moonglade_gallery.py`, and after the update's restart (exit code 42)
it runs that exact path again. Without this file that restart fails and the app stops.

It runs the real server as the main module, with the same arguments and exit code, and sets
MOONGLADE_VIA_STANDIN=1 so the server knows an old launcher is still in charge. The server
then asks, once per start, for Moonglade to be stopped once and started again from its
shortcut (which starts the new launcher, which never comes here), and refuses the next update
until that has happened.

Why it stays for good (DECISIONS 2026-10-05): an update is a pull to the newest release,
whatever it is. An install on 3.17-3.19 can skip 3.20 and go straight to a later release, so
it never meets 3.20's notice or its update gate -- and its old launcher would then relaunch
this path. The other two stand-ins (moonglade_backup.py, moonglade_mcp.py) are not on that
road and do go; this one never can.
"""
if __name__ != "__main__":          # imported by old code: run nothing, say where it went
    raise ImportError("moonglade_gallery moved to moonglade.gallery")

import os
import runpy

os.environ["MOONGLADE_VIA_STANDIN"] = "1"
runpy.run_module("moonglade.gallery", run_name="__main__", alter_sys=True)
