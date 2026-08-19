"""Spoiler-leak guard (CI). The achievement roster is SEALED in moonglade.dat, not in the
public tree (see ACHIEVEMENT_SEALING_SPEC.md). This fails the suite if a sealed roast --
the crown-jewel spoiler -- reappears in any committed public file (a future CHANGELOG line,
a stray comment, a rebuilt bundle). Roasts are the reliable needle: long, distinctive
strings, unlike feat NAMES ("under the hood", "eclipse", "marathon") which are common words
and would false-positive. Skips when the private donor isn't checked out (can't know the
sealed strings without it)."""
import json
from pathlib import Path

import pytest

from tests.conftest import _SEALED_DONOR

_REPO = Path(__file__).resolve().parents[1]

# Public text surfaces a roast could leak into. NOT tests/ (fixtures hold fake data) and NOT
# the private donor itself. dist/ bundles are included -- a rebuilt bundle must not embed one.
_SCAN_GLOBS = [
    "*.md", "docs/**/*.md", "wiki/**/*.md",
    "moonglade_*.py", "tools/*.py",
    "gallery/src/**/*.jsx", "gallery/src/**/*.js", "gallery/dist/*.js",
    "loom/src/**/*.js", "loom/dist/*.js",
]


def _files_to_scan():
    seen = set()
    for pat in _SCAN_GLOBS:
        for p in _REPO.glob(pat):
            if not p.is_file() or p in seen:
                continue
            if "node_modules" in p.parts:
                continue
            seen.add(p)
            yield p


@pytest.mark.skipif(not _SEALED_DONOR.is_file(),
                    reason="sealed-definitions donor (private repo) not present")
def test_no_sealed_roast_leaks_into_public_files():
    defs = json.loads(_SEALED_DONOR.read_text(encoding="utf-8"))
    # A distinctive prefix of every roast (censored + uncensored). 40 chars is unique enough
    # to be a real leak, short enough to survive minor reflow/escaping in a doc.
    needles = []
    for a in defs.get("roster", []):
        for key in ("roast", "roast_nsfw"):
            txt = (a.get(key) or "").strip()
            if len(txt) >= 40:
                needles.append((a["id"], key, txt[:40]))
    assert needles, "no roasts found in the donor -- guard would be a no-op; check the donor"

    leaks = []
    for path in _files_to_scan():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for aid, key, needle in needles:
            if needle in text:
                leaks.append("%s: leaks %s of %s" % (path.relative_to(_REPO), key, aid))

    assert not leaks, (
        "SEALED roast text found in public source -- scrub it (it belongs only in the "
        "container):\n  " + "\n  ".join(sorted(set(leaks))))
