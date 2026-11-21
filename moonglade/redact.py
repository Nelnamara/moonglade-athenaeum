"""
moonglade/redact.py
===================
The host-path redactor: `_redact_host_paths_cli`, the one copy every error message that can reach
a page or a log line passes through (the gallery's routes, jobs.jsonl, the living library, the
contest sweep), and `_USER_HOME_RE`, its any-username pass. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""
import os
import re
import sys
from pathlib import Path

from moonglade import paths as _paths


# Any-OS user-home prefixes: X:\Users\<name>, /home/<name>, /Users/<name>.
# The candidate loop below only knows THIS machine's directories, so an error
# text carrying a path under any OTHER username (a library echoing a foreign
# path, a message minted on another machine, a mapped drive) sailed through to
# the browser untouched -- issue #14, caught by a cross-machine test run. Only
# the home prefix + username is replaced; the tail of the path stays readable.
#
# Two corrections from issue #17 (the earlier version half-leaked and over-matched):
#  - The username segment allows SPACES (a Windows account name commonly has one, e.g.
#    "John Smith"); it stops at a separator / quote / newline / invalid-filename char, so
#    the WHOLE name is redacted rather than just its first word.
#  - The leading (?<![A-Za-z0-9.]) lookbehind stops the POSIX /home|/Users branch from
#    firing INSIDE an ordinary URL path (api.pixai.art/v1/users/me, example.com/home/docs) --
#    it only matches a home at a real path boundary (start / whitespace / quote / paren).
_USER_HOME_RE = re.compile(
    r'(?<![A-Za-z0-9.])'
    r'(?:[A-Za-z]:[\\/]+Users[\\/]+|/(?:home|Users)/+)'
    r'[^\\/:"*?<>|\r\n\']+',
    re.IGNORECASE)


def _redact_host_paths_cli(out_dir, msg):
    """THE redactor -- the one copy. create_app()'s nested `_redact_host_paths`
    delegates here (it existed as a closure twin and the two were documented as
    a drift risk; collapsed 2026-08-14 while fixing issue #14). Also called
    directly by moonglade/jobs.py's `_cli_job_finish`, which logs a
    bare-terminal CLI run's failure straight to jobs.jsonl (served to any
    LOGIN-tier caller via /api/jobs). Design choices (resolve()'d out_dir,
    longest-first, case-insensitive separator-agnostic regex, the length
    floor) are documented inline below and were carried verbatim from the
    original closure."""
    if not msg:
        return msg
    import tempfile
    # str(out_dir) resolved -- --out defaults to a relative "pixai_backup";
    # unresolved, `--out .` would make this candidate a bare "." that matches
    # (and redacts) every period in every message app-wide. The length floor
    # in the loop is the second, independent guard for candidates this
    # function doesn't construct.
    candidates = [str(Path(out_dir).resolve()), os.path.expanduser("~"),
                 tempfile.gettempdir(), sys.prefix, str(_paths.run_dir())]
    seen, out = set(), str(msg)
    for path in sorted(set(candidates), key=len, reverse=True):
        if not path or len(path) < 4 or path in seen:
            continue
        seen.add(path)
        # Split the RAW path on separators FIRST, then escape each segment,
        # then rejoin with a separator class: case-insensitive and
        # separator-agnostic (a library can hand back the same directory in a
        # different case or with forward slashes), while every segment stays
        # re.escape'd so the pattern can only ever match this exact path.
        segments = re.split(r'[\\/]+', path)
        pattern = r'[\\/]+'.join(re.escape(s) for s in segments)
        out = re.sub(pattern, "<host-path>", out, flags=re.IGNORECASE)
    # The generic pass runs AFTER the candidates: anything under a user home
    # the candidates didn't already cover -- any username, any drive letter --
    # loses its home prefix the same way (issue #14).
    out = _USER_HOME_RE.sub("<host-path>", out)
    return out
