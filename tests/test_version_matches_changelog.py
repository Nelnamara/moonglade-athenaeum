"""__version__ must match the newest cut release in CHANGELOG.md.

v2.3.0 was tagged and cut into the CHANGELOG on 2026-07-23 while
pixai_gallery_backup.__version__ still said "2.2.0" -- the Panel footer and the
gallery banner (both render core.__version__) kept reporting the OLD release for a
full day after the owner pulled the new one, and only a human noticed. The version
constant and the CHANGELOG cut are two hand-edited copies of the same fact; this
pins them together so tagging a release without bumping the constant fails the
suite instead of shipping a lying banner.

Deliberately compares against the CHANGELOG (in-repo, always present) rather than
git tags: a fresh clone's test run has tags, but a source tarball or shallow CI
checkout may not, and CLAUDE.md already names the CHANGELOG as the in-repo source
of truth for release history.
"""
import re
from pathlib import Path

import pixai_gallery_backup as core

ROOT = Path(__file__).resolve().parent.parent


def test_version_constant_matches_newest_changelog_cut():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
    assert m, "CHANGELOG.md has no cut release heading (## [x.y.z])"
    newest_cut = m.group(1)
    assert core.__version__ == newest_cut, (
        "pixai_gallery_backup.__version__ is {!r} but CHANGELOG.md's newest cut "
        "release is [{}] -- the banner and Panel footer render __version__, so "
        "bump the constant in the same commit that cuts the release.".format(
            core.__version__, newest_cut))
