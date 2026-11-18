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
other module of that name for the whole process (dev/tests/test_code_package.py).

ONE ENGINE. The engine runs as `__main__` the way runpy.run_module(run_name="__main__",
alter_sys=True) ran it (the same globals, and sys.modules["__main__"] and sys.argv[0] set for
the run), and it is ALSO registered as moonglade.backup before its first line runs. The modules
the 3.21.0 split moved out of it (pixai_client, mirror, media_tools, organize, jobs, ...) reach
it with a call-time `from moonglade.backup import ...`. With the engine unregistered, the first
of those loaded a second copy of backup.py, whose PixAIError slipped past every
`except PixAIError` in the engine and whose _VERBOSE and USER_ID were never the ones main() set
(dev/tests/test_cli_one_engine.py).
"""
import importlib.util
import os
import sys
import types

if not __package__:                       # run as a folder: python "<app>\moonglade" ...
    _here = os.path.dirname(os.path.abspath(__file__))
    _app = os.path.dirname(_here)
    if sys.path and os.path.abspath(sys.path[0] or os.curdir) == _here:
        sys.path[0] = _app
    else:
        sys.path.insert(0, _app)

import moonglade                          # noqa: E402 -- the package, once it is importable

_spec = importlib.util.find_spec("moonglade.backup")
_code = _spec.loader.get_code(_spec.name)
_engine = types.ModuleType("__main__")
_engine.__dict__.update(__name__="__main__", __file__=_spec.origin, __cached__=_spec.cached,
                        __doc__=None, __loader__=_spec.loader, __package__=_spec.parent,
                        __spec__=_spec)
_saved_main, _saved_argv0 = sys.modules["__main__"], sys.argv[0]
sys.modules["__main__"] = _engine
sys.modules["moonglade.backup"] = _engine
moonglade.backup = _engine
sys.argv[0] = _spec.origin
try:
    exec(_code, _engine.__dict__)
finally:
    sys.modules["__main__"] = _saved_main
    sys.argv[0] = _saved_argv0
