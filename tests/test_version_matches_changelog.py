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
of truth for release history. The same reasoning covers the release commit itself,
where the bump lands BEFORE the tag exists -- comparing against a tag would fail on
every release commit, or have to be skipped exactly when it matters most.

Two further guards were added while cutting 2.5.0, when the owner remembered the
skip unprompted two releases later and it checked out against the tags: the version
must be a plain three-part number (it is interpolated straight into the header
badge, so a stray suffix reaches the UI), and a cut must leave [Unreleased] behind
(a cut that consumes it gives the next change nowhere to be recorded, and the habit
lapses quietly).
"""
import re
from pathlib import Path

import pixai_gallery_backup as core

ROOT = Path(__file__).resolve().parent.parent


def _newest_cut():
    """(version, changelog text) for the newest `## [x.y.z]` heading.

    [Unreleased] carries no version number, so the pattern skips it by SHAPE rather than by
    position -- reordering the file cannot fool this into reading the wrong block.
    """
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.M)
    assert m, "CHANGELOG.md has no cut release heading (## [x.y.z])"
    return m.group(1), text


def test_version_constant_matches_newest_changelog_cut():
    newest_cut, _ = _newest_cut()
    assert core.__version__ == newest_cut, (
        "pixai_gallery_backup.__version__ is {!r} but CHANGELOG.md's newest cut "
        "release is [{}] -- the banner and Panel footer render __version__, so "
        "bump the constant in the same commit that cuts the release.".format(
            core.__version__, newest_cut))


def test_version_is_a_plain_three_part_number():
    """`"v{}".format(__version__)` goes straight into the header badge via _build_stamp(),
    so a stray suffix or a leading 'v' here is rendered into the UI verbatim."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", core.__version__), (
        "__version__ is {!r}; the header badge renders it verbatim after a 'v'"
        .format(core.__version__))


def test_unreleased_section_survives_a_cut():
    """Cutting a release must leave an [Unreleased] heading above the newest dated block.

    Without one, the next change has nowhere to go and CLAUDE.md's standing instruction to
    update [Unreleased] with every notable change becomes impossible to follow."""
    newest_cut, text = _newest_cut()
    assert "## [Unreleased]" in text, "the cut consumed [Unreleased] without replacing it"
    assert text.index("## [Unreleased]") < text.index("## [{}]".format(newest_cut)), (
        "[Unreleased] must sit ABOVE the newest dated block")
