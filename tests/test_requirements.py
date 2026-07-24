"""One check, deliberately narrow (same spirit as test_docs_dont_hardcode_counts.py): every
top-level dependency a shipped module imports unconditionally must be declared in
requirements.txt, or a clean install on a machine that doesn't already have it transitively
via some other package can break. AUDIT_2026-07-21.md `state-owner-defects`: numpy is
imported at module scope by pixai_similar.py (`import numpy as np`, used unconditionally,
not lazily like torch/transformers/pixeltable) but was never listed. This does not check
every import in the repo -- only the one the audit named -- to avoid growing into a linter."""
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _declared_packages():
    """Package names declared in requirements.txt, stripped of version pins / environment
    markers / inline comments -- matches the file's own unpinned, bare-name convention."""
    text = (_REPO / "requirements.txt").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[;<>=\[\s]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower())
    return names


def test_numpy_is_a_declared_dependency():
    """pixai_similar.py imports numpy unconditionally at module scope -- it must be
    declared in requirements.txt, not left to arrive as some other package's transitive
    pull (which a clean install cannot rely on)."""
    assert "numpy" in _declared_packages(), (
        "pixai_similar.py does `import numpy as np` at module scope, but 'numpy' is "
        "missing from requirements.txt -- add it so a clean install doesn't silently "
        "depend on another package pulling it in transitively.")
