"""The install root after the 3.20 rebuild (DECISIONS 2026-10-05 and 2026-10-07, pick 2).

  * No .py file at the root: the stand-ins are gone, and the launcher, renamed
    `Moonglade Launcher.pyw`, is the one Python-family file left there.
  * The old launcher's name survives only where it must: the release history, and the
    fixer that finds things outside the app still naming it (moonglade/outside.py and its
    tests). Every live reference -- code, front end, built bundles, wiki, README, CLAUDE.md --
    says the new name.
  * Nothing reads the old stand-in's flag any more.

Read from what git tracks, so a stray file on a developer's machine never decides it.
"""
import shutil
import subprocess

import pytest

from tests.conftest import REPO_ROOT, first_party_sources

OLD_LAUNCHER = "Serve Gallery.pyw"
NEW_LAUNCHER = "Moonglade Launcher.pyw"

# Where the old launcher's name may still be written, and why.
_OLD_NAME_ALLOWED = {
    "CHANGELOG.md": "release history keeps the names things had then",
    "moonglade/outside.py": "it finds things outside the app that still name the old file",
    "Moonglade Launcher.pyw": "it re-points shortcuts that still name its old name",
    "moonglade/gallery.py": "the notice about things outside the app naming the old files",
    "moonglade/paths.py": "launcher_path() says what the launcher was called through 3.19",
    "tests/test_outside.py": "the fixer's own tests",
    "tests/test_install_root.py": "this file",
}


def _tracked():
    if not shutil.which("git"):
        pytest.skip("git is not on this machine")
    r = subprocess.run(["git", "ls-files", "-z"], cwd=str(REPO_ROOT), capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    return [p for p in r.stdout.decode("utf-8").split("\0") if p]


def test_no_python_file_at_the_install_root():
    root = [p for p in _tracked() if "/" not in p]
    assert [p for p in root if p.endswith(".py")] == []
    assert [p for p in root if p.endswith((".py", ".pyw"))] == [NEW_LAUNCHER]
    assert (REPO_ROOT / NEW_LAUNCHER).is_file()
    assert not (REPO_ROOT / OLD_LAUNCHER).exists()


def test_the_old_launcher_name_lives_only_where_it_must():
    stray = []
    for rel in _tracked():
        if rel in _OLD_NAME_ALLOWED:
            continue
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                                     # binary files: icons, video, the pack
        if OLD_LAUNCHER in text or "Serve Gallery" in text:
            stray.append(rel)
    assert stray == [], "still names the old launcher: %s" % stray


def test_the_live_references_say_the_new_name():
    for rel in ("README.md", "CLAUDE.md", "wiki/Gallery.md", "wiki/Glossary.md",
                "moonglade/paths.py"):
        assert "Moonglade Launcher" in (REPO_ROOT / rel).read_text(encoding="utf-8"), rel


def test_nothing_reads_the_old_stand_ins_flag():
    names = [p for p in first_party_sources()
             if "MOONGLADE_VIA_STANDIN" in p.read_text(encoding="utf-8")]
    assert names == []
