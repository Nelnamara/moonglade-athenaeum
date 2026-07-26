"""The in-app version must match the newest dated CHANGELOG block.

v2.3.0 shipped with `__version__ = "2.2.0"` still in the module, so the header badge and the
Control Panel's "This build" line both announced the PREVIOUS release to anyone running it --
including the owner, who noticed and remembered it two releases later. Nothing caught it,
because nothing compared the two places a version is written down.

Deliberately compared against the CHANGELOG rather than against git tags: at release time the
bump lands BEFORE the tag exists, so a tag comparison would either fail on every release
commit or have to be skipped exactly when it matters. The changelog block is written in the
same commit as the bump, so requiring them to agree is a check that can actually hold.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pixai_gallery_backup as core  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _newest_released_version():
    """The first dated `## [x.y.z] - ...` heading, skipping [Unreleased]."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+)\] - ", text, re.M)
    assert m, "no dated version heading found in CHANGELOG.md"
    return m.group(1)


def test_in_app_version_matches_the_newest_changelog_entry():
    """A release whose app reports the previous version is a release nobody can identify
    from inside the app -- which is exactly what v2.3.0 did."""
    changelog = _newest_released_version()
    assert core.__version__ == changelog, (
        "__version__ is {!r} but the newest CHANGELOG entry is {!r}. If you are cutting a "
        "release, bump both in the same commit; if you are mid-development, the changelog's "
        "top block should still be [Unreleased] above the last dated one."
        .format(core.__version__, changelog))


def test_the_version_is_a_plain_three_part_number():
    """`v{}`.format(__version__) is rendered straight into the header badge, so a stray
    suffix or a 'v' prefix here shows up in the UI."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", core.__version__), core.__version__


def test_unreleased_section_still_exists_for_the_next_change():
    """Cutting a release must leave an [Unreleased] heading behind, or the next change has
    nowhere to be written and the habit quietly lapses."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text
    assert text.index("## [Unreleased]") < text.index("## [{}]".format(core.__version__)), (
        "[Unreleased] must sit above the newest dated block")
