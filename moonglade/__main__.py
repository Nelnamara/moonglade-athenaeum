"""The command-line tool: backups, generation and the library's upkeep. Two ways to run it:

    python -m moonglade --sync                      from the app's folder (the one holding
                                                    config.json), as every documented command
                                                    line does
    python "C:\\path\\to\\app\\moonglade" --sync     from any folder: a scheduled task, another
                                                    terminal, a script

Either way it runs moonglade/backup.py as the main module, exactly as `python
moonglade_backup.py` did before 3.20 moved the code into this folder: the same arguments, the
same exit code and the same `if __name__ == "__main__":` block.

Run as a folder, Python puts THIS folder first on sys.path and gives this file no package. The
package is then importable only once the app's folder (this folder's parent) is on the path, so
it takes this folder's place there: with this folder itself on the path, every module in it
(paths, logs, assets, ...) would also be importable under its bare name, and would win over any
other module of that name for the whole process (tests/test_code_package.py).
"""
import os
import runpy
import sys

if not __package__:                       # run as a folder: python "<app>\moonglade" ...
    _here = os.path.dirname(os.path.abspath(__file__))
    _app = os.path.dirname(_here)
    if sys.path and os.path.abspath(sys.path[0] or os.curdir) == _here:
        sys.path[0] = _app
    else:
        sys.path.insert(0, _app)

runpy.run_module("moonglade.backup", run_name="__main__", alter_sys=True)
