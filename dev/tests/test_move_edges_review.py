"""Adversarial-review additions for the issue #79 lane (dev/tests/test_move_edges.py): the
cases the first set let through. Each fails without its fix."""
import json
import os
import zipfile
from pathlib import Path

import pytest

from moonglade import integrity
from moonglade import migrate
from moonglade import paths
from moonglade import setup as msetup
from tests.move_layouts import rig, start, write, write_config


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _parked(root):
    folder = Path(root) / ".snapshot" / "parked"
    return sorted(p.name for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


def test_a_plain_name_file_that_scans_before_the_live_one_still_never_wins(r):
    """The plain-name file goes last of the files, so the hashed one takes the home first. A
    login "B" has the plain file B.json, which sorts before its hashed key's file (df7e...) on
    a case-insensitive disk: without the ordering it would take the home, and the live file,
    older by its time, would be the one set aside."""
    key = paths.account_key("B")
    assert key.lower() > "b."            # B.json is scanned first
    write_config(r, AUTH_USERS=[{"username": "B", "password_hash": "x"}])
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    live = write(r.lib / "account_prefs" / (key + ".json"), {"theme": "live"})
    dead = write(r.lib / "account_prefs" / "B.json", {"theme": "dead"})
    os.utime(live, (1_700_000_000, 1_700_000_000))
    os.utime(dead, (1_750_000_000, 1_750_000_000))
    start(r)
    home = r.lib / "_moonglade" / "accounts" / key / "prefs.json"
    assert json.loads(home.read_text()) == {"theme": "live"}
    assert _parked(r.lib / "_moonglade") == ["B.json"]


def _moved(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "before-the-move"}\n')
    start(r)
    assert json.loads((r.lib / "_moonglade" / ".journal.json").read_text())["finished"]


def _bring_in(r):
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "An older Moonglade is still using the library" in str(e.value)
    return start(r)


def test_the_new_home_s_marks_are_in_the_safety_copy_before_an_older_install_s_later_mark_replaces_one(r):
    """The marks fold now lets the LATER choice win a clash, so it overwrites a value the new
    home holds: the new home's own integrity_marks.json goes into this run's safety copy first
    (as telemetry.json's does), or the replaced choice is gone for good."""
    _moved(r)
    marks = r.lib / "_moonglade" / "decisions" / "integrity_marks.json"
    write(marks, {"format": "moonglade-integrity-marks", "marks": {
        "m1": {"mark": "lost", "at": "2026-10-07T10:00:00Z"}}})
    old = write(r.lib / "integrity_marks.json", {"format": "moonglade-integrity-marks", "marks": {
        "m1": {"mark": "kept", "at": "2026-10-08T09:00:00Z"}}})
    later = old.stat().st_mtime + 120
    os.utime(old, (later, later))
    _bring_in(r)
    assert integrity.read_marks(r.lib)["m1"]["mark"] == "kept"      # the later choice won
    zips = sorted((r.lib / "_moonglade" / ".snapshot").glob("*.zip"),
                  key=lambda p: p.stat().st_mtime_ns)
    with zipfile.ZipFile(zips[-1]) as zf:
        kept = json.loads(zf.read("_moonglade/decisions/integrity_marks.json"))
    assert kept["marks"]["m1"]["mark"] == "lost", "the choice that was replaced is kept"





def test_at_the_first_move_an_empty_copy_never_beats_a_real_one_on_its_time(r):
    """"Keep the newer, park the other" parked a login's real snippets (deleted after five clean
    starts) for a 0-byte snippets.json written later. An empty copy holds nothing: the other
    stays, whichever is newer -- the old place's or the new home's."""
    key = paths.account_key("Nel")
    write_config(r)
    acc = r.lib / "_moonglade" / "accounts" / key
    old = write(r.lib / "prompt_snippets" / (key + ".json"), ["golden hour"])
    os.utime(old, (1_700_000_000, 1_700_000_000))
    write(acc / "snippets.json", b"")                       # newer, and empty
    older_empty = write(r.lib / "account_prefs" / (key + ".json"), b"")      # newer, and empty
    write(acc / "prefs.json", {"theme": "dusk"})
    os.utime(acc / "prefs.json", (1_700_000_000, 1_700_000_000))
    start(r)
    assert json.loads((acc / "snippets.json").read_text()) == ["golden hour"]
    assert json.loads((acc / "prefs.json").read_text()) == {"theme": "dusk"}
    assert not older_empty.exists()


def test_an_empty_new_home_with_an_unreadable_older_copy_blames_the_older_copy_not_the_new_home(r):
    """The empty new home takes the older copy as its content only when that reads. When the
    older copy does not, the start must not stop naming the (empty, harmless) new home at every
    start: the older copy is the damaged one and is set aside."""
    from tests.move_layouts import KEY_NEL
    _moved(r)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    write(acc / "snippets.json", b"")
    old = write(r.lib / "prompt_snippets" / (KEY_NEL + ".json"), '["torn')
    later = old.stat().st_mtime + 120
    os.utime(old, (later, later))
    _bring_in(r)
    assert (acc / "snippets.json").read_bytes() == b""
    assert not old.exists()
    assert _parked(r.lib / "_moonglade") == [KEY_NEL + ".json"]
