"""One-click Update against a REAL git checkout (app security review 2026-11-19, finding 10).

test_updater.py drives the apply with a stubbed `_git`; this file proves the git commands
themselves do what the stubs assume, on throwaway repositories in tmp_path: a "GitHub" bare
repository with three commits on master -- v1.0.0, v1.1.0 (the announced release) and one
merged after it -- and an install cloned from it. Local paths only: nothing leaves the machine.
"""
import shutil
import subprocess

import pytest

from moonglade import paths as moonglade_paths
from moonglade import updater as updater_mod

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

_ID = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def _run(cwd, *args):
    p = subprocess.run(["git"] + _ID + list(args), cwd=str(cwd), capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout.strip()


def _commit(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    _run(repo, "add", name)
    _run(repo, "commit", "-q", "-m", name)
    return _run(repo, "rev-parse", "HEAD")


@pytest.fixture
def install(tmp_path, monkeypatch):
    origin, work, inst = tmp_path / "origin.git", tmp_path / "work", tmp_path / "install"
    _run(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    _run(tmp_path, "clone", "-q", str(origin), str(work))
    _run(work, "checkout", "-q", "-b", "master")
    c1 = _commit(work, "a.txt", "one")
    _run(work, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    c2 = _commit(work, "b.txt", "two")
    _run(work, "tag", "-a", "v1.1.0", "-m", "v1.1.0")
    c3 = _commit(work, "c.txt", "merged after the release")
    _run(work, "push", "-q", "origin", "master", "--tags")
    _run(tmp_path, "clone", "-q", "--no-tags", str(origin), str(inst))
    _run(inst, "reset", "-q", "--hard", c1)                     # an install still on v1.0.0
    _run(inst, "tag", "-d", "v1.0.0") if "v1.0.0" in _run(inst, "tag") else None
    monkeypatch.setattr(moonglade_paths, "APP_ROOT", inst)
    monkeypatch.setattr(updater_mod, "_update_state", {"phase": "idle", "error": "", "at": 0.0})
    monkeypatch.setattr(updater_mod, "UPDATE_RESTART_DELAY", 0)
    return {"dir": inst, "c1": c1, "c2": c2, "c3": c3}


def test_master_behind_the_tag_moves_to_exactly_the_tag(install):
    restarted = []
    ok = updater_mod.run_update(lambda: restarted.append(1), "v1.1.0", pip_fn=lambda: (0, ""))
    assert ok is True, updater_mod.update_state()
    d = install["dir"]
    assert _run(d, "rev-parse", "HEAD") == install["c2"], "it moved past the announced tag"
    assert _run(d, "rev-parse", "--abbrev-ref", "HEAD") == "master"
    assert (d / "b.txt").exists() and not (d / "c.txt").exists()
    assert restarted == [1]
    # and the next release still fast-forwards from here (nothing is stranded)
    assert updater_mod.incoming_paths("v1.1.0") == (set(), "")


def test_a_checkout_whose_history_does_not_lead_to_the_tag_is_left_alone(install):
    d = install["dir"]
    local = _commit(d, "mine.txt", "a local commit")
    assert updater_mod.run_update(lambda: None, "v1.1.0", pip_fn=lambda: (0, "")) is False
    st = updater_mod.update_state()
    assert st["phase"] == "failed" and "v1.1.0" in st["error"]
    assert _run(d, "rev-parse", "HEAD") == local


def test_the_untracked_check_sees_what_the_tag_brings(install):
    incoming, why = updater_mod.incoming_paths("v1.1.0")
    assert why == "" and incoming == {"b.txt"}, "c.txt is past the tag and must not count"
