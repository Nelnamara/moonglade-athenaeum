"""moonglade_gallery.py -- a stand-in for the web server, kept for one release (3.20).

The server moved to moonglade/gallery.py in 3.20, and the launcher (Serve Gallery.pyw) now
starts it as `python -m moonglade.gallery`. This file is for the launcher that was ALREADY
RUNNING when the install updated across the move: it built its command line once, when it
started, as `python <this folder>/moonglade_gallery.py`, and after the update's restart (exit
code 42) it runs that exact path again. Without this file that restart fails and the app
stops.

It runs the real server as the main module, with the same arguments and exit code, and sets
MOONGLADE_VIA_STANDIN=1 so the server knows an old launcher is still in charge. The server
then asks, once per start, for Moonglade to be stopped once and started again from its
shortcut (which starts the new launcher, which never comes here), and refuses the next update until that has happened.

Goes in 3.21, with the other stand-ins. This release's update refuses while an old launcher
is in charge, so the update that deletes this file only ever lands on a server the new
launcher started, and no old launcher is left to come looking for it.
"""
if __name__ != "__main__":          # imported by old code: run nothing, say where it went
    raise ImportError("moonglade_gallery moved to moonglade.gallery")

import os
import runpy

os.environ["MOONGLADE_VIA_STANDIN"] = "1"
runpy.run_module("moonglade.gallery", run_name="__main__", alter_sys=True)
