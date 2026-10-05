"""`python -m moonglade` -- the command-line tool: backups, generation and the library's upkeep.

It runs moonglade/backup.py as the main module, exactly as `python moonglade_backup.py` did
before 3.20 moved the code into this folder: the same arguments, the same exit code and the
same `if __name__ == "__main__":` block. Run it from the app's folder (the one holding
config.json), as every documented command line does.
"""
import runpy

runpy.run_module("moonglade.backup", run_name="__main__", alter_sys=True)
