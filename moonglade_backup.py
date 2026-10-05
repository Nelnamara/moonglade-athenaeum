"""moonglade_backup.py -- a stand-in for the command-line tool, kept for one release (3.20).

The command-line tool moved to moonglade/backup.py in 3.20 and runs as `python -m moonglade`.
This file keeps the old command working for one more release -- for old habits, a Windows
Task Scheduler entry and old copies of the docs -- and says once, on stderr, what to type
instead. The same arguments, the same exit code.

Goes in 3.21, with the other stand-ins.
"""
import runpy
import sys

sys.stderr.write("moonglade_backup.py moved: run `python -m moonglade ...` instead; "
                 "this stand-in goes in the next release\n")
runpy.run_module("moonglade.backup", run_name="__main__", alter_sys=True)
