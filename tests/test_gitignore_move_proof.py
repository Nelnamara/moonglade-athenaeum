""".gitignore is move-proof (Wave 4 groundwork, 3.19.0).

Several ignore lines are unanchored on purpose -- `gallery/`, `images/`, `videos/`,
`imported/`, `_duplicates/`, `private/`, `catalog.db`, `config.json`, `serve.txt`, `serve.log`
-- so a library or a stray runtime file is kept out of git wherever it sits. The same lines
would also hide files of the code folder the modules move into next release (a
`moonglade/gallery/` package, say), so the code under /moonglade/ is never ignored -- while
Python's byte-code caches and every secret or runtime file (config.json, the mirror token, a
token, .env, the launcher's files, a catalog, the art pack, a library, `local/`) stay ignored
there too. The future runtime folders are ignored already: `/local/` (the machine files) at
the app root, and a library's own `_moonglade/` wherever the library is.

Asked of git itself (`git check-ignore --no-index`), on paths that need not exist, so the
answer is the rule's, not the working tree's.
"""
import shutil
import subprocess

import pytest

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _ignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=str(REPO_ROOT),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr        # 128 = git could not answer
    return r.returncode == 0


NEVER_IGNORED = (
    # the brief's samples
    "moonglade/gallery.py", "moonglade/server/x.py", "moonglade/manifest.json",
    # a sub-package named like each unanchored library guard
    "moonglade/gallery/__init__.py", "moonglade/gallery/routes.py",
    "moonglade/images/__init__.py", "moonglade/videos/x.py", "moonglade/imported/x.py",
    "moonglade/_duplicates/x.py", "moonglade/private/x.py", "moonglade/env/x.py",
    "moonglade/_moonglade/x.py",
    # a module merely NAMED like a runtime file is still code (serve.* would hide it)
    "moonglade/serve.py", "moonglade/config.py", "moonglade/local.py",
    # and the repo-root front end stays tracked, as before
    "gallery/src/main.jsx", "gallery/dist/app.js",
)

ALWAYS_IGNORED = (
    # the brief's samples
    "local/serve.log", "pixai_backup/_moonglade/achievements.json", "config.json",
    # the machine files' future folder, whatever is in it
    "local/moonglade.mgpack", "local/branding.json", "local/cache/marks/mark_4.ico",
    # a library anywhere keeps its guards, the new _moonglade/ among them
    "D_library/_moonglade/jobs.jsonl", "D_library/_moonglade/reports/audit_report.csv",
    "D_library/_moonglade/achievements.json", "D_library/_moonglade/runs.db",
    "D_library/_moonglade/account_prefs/a.json",
    "some/where/lib/gallery/thumbs/a.jpg", "some/where/lib/images/a.png",
    "other_out/catalog.db", "other_out/jobs.jsonl",
    # the runtime files at the root, as before, and the old logs the launcher rotates to
    "serve.log", "serve.txt", "mirror_session.json", "moonglade.mgpack",
    "serve.log.1", "serve.log.2", "serve.log.3", "local/serve.log.1",
    "branding.json", "0x676F6F6473/README.txt",
    # secrets and runtime files stay out even inside the code folder: the re-include must
    # never turn a stray config.json, token or log there into something git would commit
    "moonglade/config.json", "moonglade/config.json.tmp-123", "moonglade/sub/config.json",
    "moonglade/mirror_session.json", "moonglade/mirror_session.json.tmp-1-ab",
    "moonglade/token.txt", "moonglade/.env", "moonglade/serve.txt", "moonglade/serve.log",
    "moonglade/serve.log.2", "moonglade/catalog.db", "moonglade/pixai_backup/catalog.db",
    "moonglade/pixai_backup/images/a.png", "moonglade/moonglade.mgpack",
    "moonglade/moonglade.mgpack.version", "moonglade/local/serve.log",
    "moonglade/local/branding.json",
    # Python's caches stay ignored, inside the code folder too
    "moonglade/__pycache__/gallery.cpython-314.pyc", "moonglade/server/__pycache__/x.pyc",
    "moonglade/gallery.pyc",
)


@pytest.mark.parametrize("path", NEVER_IGNORED)
def test_nothing_in_the_code_folder_is_ignored(path):
    assert not _ignored(path), path + " is ignored -- git would never see it"


@pytest.mark.parametrize("path", ALWAYS_IGNORED)
def test_runtime_files_and_libraries_stay_ignored(path):
    assert _ignored(path), path + " is NOT ignored -- it could be committed"


def test_the_code_folder_re_include_comes_last():
    """git takes the LAST pattern that matches, so a library guard added below the re-include
    would quietly start hiding package files again."""
    lines = [ln.strip() for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
             .splitlines() if ln.strip() and not ln.strip().startswith("#")]
    i = lines.index("!/moonglade/**")
    assert all(ln.startswith("/moonglade/") for ln in lines[i + 1:]), lines[i + 1:]
