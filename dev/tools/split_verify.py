"""Prove a split_move.py cut is verbatim, before it is committed.

    py dev/tools/split_verify.py OLDREL NEWREL ALIAS START END [EXTRA_LINE ...]

OLDREL/NEWREL are repo-relative (moonglade/gallery.py, moonglade/health.py); START..END and the
EXTRA_LINEs are the lines the move cut, numbered as in OLDREL at HEAD (the commit before the
move). Two checks, against `git show HEAD:OLDREL`, LF-normalised:

  1. NEWREL holds the original block (and each extra line) byte for byte, once the lazy
     `from moonglade.backup|gallery import ...` lines inside functions are set aside on both
     sides (they are the wiring split_move.py's `lazy` adds).
  2. OLDREL is the original minus the cut, once its `ALIAS.` prefixes on the moved names and
     the one added `from moonglade import <new> as ALIAS` line are undone (runs of blank lines
     at the seam are tolerated). Any other difference is printed and exits 1.

The moved names come from <WORK>/<new>.names.json, which split_move.py's `move` wrote (<WORK> is
%TEMP%/moonglade_split unless MOONGLADE_SPLIT_WORK names another folder).
"""
import ast
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("MOONGLADE_SPLIT_WORK")
            or Path(tempfile.gettempdir()) / "moonglade_split")


def _lines(text):
    """Lines as ast and grep -n number them: split at "\n" only (str.splitlines also splits
    at U+2028 and the other Unicode line breaks a string or comment may carry)."""
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def strip_lazy(src):
    """Drop indented `from moonglade.backup|gallery import ...` statements (the lazy wiring)."""
    drop = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.ImportFrom) and node.col_offset > 0
                and node.module in ("moonglade.backup", "moonglade.gallery")):
            drop.update(range(node.lineno, node.end_lineno + 1))
    ls = _lines(src)
    return "".join(l for i, l in enumerate(ls, 1) if i not in drop), len(drop)


def main(argv):
    old_rel, new_rel, alias, start, end = argv[0], argv[1], argv[2], int(argv[3]), int(argv[4])
    extra = [int(x) for x in argv[5:]]
    orig = subprocess.run(["git", "show", "HEAD:%s" % old_rel], cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8").stdout.replace("\r\n", "\n")
    lines = _lines(orig)
    block = "".join(lines[start - 1:end])
    new = (REPO / new_rel).read_text(encoding="utf-8").replace("\r\n", "\n")

    new_s, n_new = strip_lazy(new)
    block_s, n_old = strip_lazy(block)
    assert block_s in new_s, "block not verbatim in new module"
    print("   (lazy import lines: %d in the original block, %d in the new module)" % (n_old, n_new))
    for e in extra:
        assert lines[e - 1] in new, "extra line %d missing" % e
    print("1. block (%d lines) + %d extra line(s) verbatim in %s"
          % (end - start + 1, len(extra), new_rel))

    names = json.loads((WORK / (Path(new_rel).stem + ".names.json")).read_text())
    cur = (REPO / old_rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    pat = re.compile(r"\b%s\.(%s)\b" % (re.escape(alias), "|".join(map(re.escape, names))))
    undone = pat.sub(lambda m: m.group(1), cur)
    imp = "from moonglade import %s as %s\n" % (Path(new_rel).stem, alias)
    undone = undone.replace(imp, "", 1)
    keep = "".join(l for i, l in enumerate(lines, 1) if not (start <= i <= end) and i not in extra)

    def squash(s):
        return re.sub(r"\n{3,}", "\n\n", s)
    if squash(undone) == squash(keep):
        print("2. %s: only the cut, %d `%s.` prefixes and the import line differ"
              % (old_rel, len(pat.findall(cur)), alias))
        return 0
    d = list(difflib.unified_diff(squash(keep).splitlines(), squash(undone).splitlines(),
                                  lineterm="", n=1))
    print("2. DIFFERS:\n" + "\n".join(d[:80]))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
