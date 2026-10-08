"""The move's safety rules (SPEC_3.20_REBUILD.md "Rules every lane follows"; B4, S9, pick 4):

  * THE SAFE MOVE: copy into a temp beside the destination, flush, verify (sha256; a database
    by integrity_check and row counts), journal, swap within one folder, journal, delete the
    source. A copy that does not verify is never swapped in, and the source stays.
  * RESUME: a start that dies at any step is finished by the next one, from the journal.
  * NEVER ACROSS VOLUMES: nothing is renamed from one folder to another -- the only os.replace
    is a temp into its own folder -- so a library on another drive moves the same way.
  * CONFLICTS (B4): a new copy wins only when the journal says the move made it. A fresh file
    that appeared in the new home first never wins over the real data: JSONL is merged,
    telemetry/achievements/the spend guard merged where the format allows, anything else keeps
    the newer and parks the other. Nothing is deleted on a guess.
  * THE SNAPSHOT (pick 4): made before the first move, deleted after 5 clean server starts.
  * THE LOCKS: a lock held past its wait stops the start with a plain sentence; a dead
    holder's lock is taken over.
"""
import errno
import json
import os
import zipfile
from pathlib import Path

import pytest

from moonglade import migrate
from moonglade import setup as msetup
from tests.move_layouts import (KEY_NEL, db_rows, layout_317, make_db, rig, write,
                                write_config)


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


class _Crash(BaseException):
    """A process dying mid-move: nothing catches it, the lock is left behind."""


def _prepare(r, kind="cli"):
    return msetup.prepare(kind, explicit_out=str(r.lib))


def _no_moving_temps(*roots):
    for root in roots:
        left = [p for p in Path(root).rglob("*" + migrate.MOVING_SUFFIX)]
        assert not left, left


def _crash_on(monkeypatch, target, attr, nth, when=lambda *a, **k: True):
    """Make target.attr raise _Crash on its nth matching call."""
    real = getattr(target, attr)
    calls = {"n": 0}

    def wrapper(*a, **k):
        if when(*a, **k):
            calls["n"] += 1
            if calls["n"] == nth:
                raise _Crash()
        return real(*a, **k)
    monkeypatch.setattr(target, attr, wrapper)
    return calls


def _guard_src(r):
    return r.lib / "train_guard.json"


def _guard_dest(r):
    return r.lib / "_moonglade" / "records" / "train_guard.json"


GUARD = {"basic": {"k1": {"state": "ambiguous", "at": 100.0}}, "retried": {}, "paid": {}}


@pytest.mark.parametrize("step", ["copied", "verified", "swapped", "made"])
def test_a_crash_at_each_step_is_finished_by_the_next_start(r, monkeypatch, step):
    """The spend guard is the example: the item a lost copy would hurt most."""
    write_config(r)
    write(_guard_src(r), GUARD)
    is_guard = lambda *a, **k: "train_guard" in str(a[0])        # noqa: E731
    with monkeypatch.context() as m:
        if step == "copied":          # the temp is written, the process dies before verifying
            _crash_on(m, migrate, "_verified", 1, is_guard)
        elif step == "verified":      # journalled as verified, dies before the swap
            _crash_on(m, migrate.os, "replace", 1,
                      lambda a, b, *x, **k: str(b).endswith("train_guard.json"))
        elif step == "swapped":       # swapped in, dies before the journal says made
            calls = {"n": 0}
            real_save = migrate.Journal.save

            def save(self):
                if "train_guard" in json.dumps(self.doc) and \
                        _guard_dest(r).is_file() and calls["n"] == 0:
                    calls["n"] += 1
                    raise _Crash()
                return real_save(self)
            m.setattr(migrate.Journal, "save", save)
        else:                         # journalled as made, dies before deleting the source
            _crash_on(m, migrate, "_remove", 1, is_guard)
        with pytest.raises(_Crash):
            _prepare(r)
    # A process that really dies leaves its locks behind (here the exception unwound them):
    # put back what it would have left, holding a pid that is no longer running.
    for folder in (r.local, r.lib / "_moonglade"):
        (folder / ".lock").write_text("999999999", encoding="ascii")
    _prepare(r)                                       # the next start
    assert json.loads(_guard_dest(r).read_text()) == GUARD
    assert not _guard_src(r).exists()
    _no_moving_temps(r.lib, r.local)
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert journal["items"]["_moonglade/records/train_guard.json"]["state"] == "made"
    assert journal["finished"]
    assert not (r.lib / "_moonglade" / ".lock").exists()
    assert not (r.local / ".lock").exists()


def test_a_copy_that_does_not_verify_is_never_swapped_in(r, monkeypatch):
    write_config(r)
    write(_guard_src(r), GUARD)
    monkeypatch.setattr(migrate, "_verified", lambda *a: False)
    with pytest.raises(migrate.MoveStopped) as e:
        _prepare(r)
    assert "did not match" in str(e.value)
    assert json.loads(_guard_src(r).read_text()) == GUARD, "the source stays"
    assert not _guard_dest(r).exists()
    _no_moving_temps(r.lib)


def test_a_database_comes_across_through_sqlite_and_is_checked(r):
    write_config(r)
    make_db(r.lib / "runs.db", rows=40)
    _prepare(r)
    assert db_rows(r.lib / "_moonglade" / "records" / "runs.db") == ["r%d" % i for i in range(40)]


def test_nothing_is_renamed_across_folders(r, monkeypatch):
    """Force the copy path everywhere: os.replace between two folders fails as it would
    between two volumes, and the folder renames are refused outright. The move still
    completes, because it only ever swaps a temp into its own folder."""
    layout_317(r)
    real_replace = os.replace

    def replace(a, b, *x, **k):
        if os.path.dirname(os.path.abspath(a)) != os.path.dirname(os.path.abspath(b)):
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(a, b, *x, **k)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "rename", lambda *a, **k: (_ for _ in ()).throw(
        OSError(errno.EXDEV, "cross-device link")))
    import shutil
    monkeypatch.setattr(shutil, "move", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the move never uses shutil.move")))
    _prepare(r)
    assert (r.local / "moonglade.mgpack").read_bytes() == b"PACK-317" * 64
    assert (r.lib / "_moonglade" / "records" / "train_guard.json").is_file()
    assert (r.local / "logs" / "moonglade.log").is_file()
    assert (r.lib / "_moonglade" / "loom" / "_submits" / (KEY_NEL + ".jsonl")).is_file()


# ---- conflicts ----------------------------------------------------------------------------------

def _two(r, name, old, new):
    """`name` in the old place and, already, in the new one (not made by the move)."""
    write(r.lib / name, old)
    write(r.lib / "_moonglade" / "records" / name, new)


def test_a_fresh_file_in_the_new_home_never_wins_over_the_real_data(r):
    """B4: a start that wrote before the move (or a second install) left a fresh, empty
    achievements file in the new home. The real one is merged in, never deleted."""
    write_config(r)
    _two(r, "achievements.json",
         {"seen": ["a1", "a2"], "skin": "dusk", "earned_at": {"a1": "2026-08-01"}},
         {"seen": [], "skin": "moonglade", "earned_at": {}})
    _prepare(r)
    got = json.loads((r.lib / "_moonglade" / "records" / "achievements.json").read_text())
    assert got["seen"] == ["a1", "a2"] and got["earned_at"] == {"a1": "2026-08-01"}
    assert not (r.lib / "achievements.json").exists()


def test_achievements_keep_each_feat_s_earliest_date(r):
    write_config(r)
    _two(r, "achievements.json",
         {"seen": ["a1"], "skin": "dusk", "earned_at": {"a1": "2026-08-01", "a3": "2026-09-09"}},
         {"seen": ["a2"], "skin": "moonglade", "earned_at": {"a1": "2026-10-05"}})
    _prepare(r)
    got = json.loads((r.lib / "_moonglade" / "records" / "achievements.json").read_text())
    assert got["earned_at"] == {"a1": "2026-08-01", "a3": "2026-09-09"}
    assert set(got["seen"]) == {"a1", "a2"}


def test_telemetry_counters_and_sets_are_merged(r):
    write_config(r)
    _two(r, "telemetry.json",
         {"counters": {"gens": 9, "old": 1}, "sets": {"m": ["x", "y"]}, "days": ["d1"],
          "flags": {"f": 1}},
         {"counters": {"gens": 4, "new": 2}, "sets": {"m": ["z"]}, "days": ["d2"],
          "flags": {"g": 1}})
    _prepare(r)
    got = json.loads((r.lib / "_moonglade" / "records" / "telemetry.json").read_text())
    assert got["counters"] == {"gens": 9, "new": 2, "old": 1}
    assert sorted(got["sets"]["m"]) == ["x", "y", "z"]
    assert sorted(got["days"]) == ["d1", "d2"]
    assert got["flags"] == {"g": 1, "f": 1}


def test_the_spend_guard_keeps_every_guard_from_both_copies(r):
    """More guarding, never less: a guard armed in either copy still blocks."""
    write_config(r)
    _two(r, "train_guard.json",
         {"basic": {"k1": {"state": "ambiguous", "at": 200.0}}, "retried": {"t9": {"at": 5}},
          "paid": {}},
         {"basic": {"k1": {"state": "armed", "at": 100.0}, "k2": {"state": "armed", "at": 1}},
          "retried": {}, "paid": {"p1": {"at": 3}}})
    _prepare(r)
    got = json.loads((r.lib / "_moonglade" / "records" / "train_guard.json").read_text())
    assert got["basic"]["k1"] == {"state": "ambiguous", "at": 200.0}, "the later one"
    assert set(got["basic"]) == {"k1", "k2"}
    assert set(got["retried"]) == {"t9"} and set(got["paid"]) == {"p1"}


def test_jsonl_is_merged_line_by_line(r):
    write_config(r)
    _two(r, "jobs.jsonl", '{"id": 1}\n{"id": 2}\n', '{"id": 2}\n{"id": 3}\n')
    _prepare(r)
    got = (r.lib / "_moonglade" / "records" / "jobs.jsonl").read_text().splitlines()
    assert got == ['{"id": 2}', '{"id": 3}', '{"id": 1}']


def test_anything_else_keeps_the_newer_and_parks_the_other(r):
    write_config(r)
    _two(r, "schedule.json", {"which": "old place, newer"}, {"which": "new place, older"})
    os.utime(r.lib / "_moonglade" / "records" / "schedule.json", (1, 1))
    _prepare(r)
    got = json.loads((r.lib / "_moonglade" / "records" / "schedule.json").read_text())
    assert got == {"which": "old place, newer"}
    parked = list((r.lib / "_moonglade" / ".snapshot" / "parked").rglob("schedule.json*"))
    assert len(parked) == 1
    assert json.loads(parked[0].read_text()) == {"which": "new place, older"}


def test_the_same_bytes_in_both_places_are_one_copy(r):
    write_config(r)
    _two(r, "reconcile_stamp.json", {"at": "x"}, {"at": "x"})
    done = _prepare(r)
    assert not (r.lib / "reconcile_stamp.json").exists()
    assert done.report.parked == 0


def test_an_old_copy_written_back_after_the_move_is_merged_at_the_next_start(r):
    """An older install still on the library writes its old place again: the next start
    re-checks the old homes and merges, rather than deleting what it wrote."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _prepare(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n{"id": "written-back"}\n')
    _prepare(r)
    got = (r.lib / "_moonglade" / "records" / "jobs.jsonl").read_text().splitlines()
    assert got == ['{"id": 1}', '{"id": "written-back"}']


def test_the_move_s_own_leftover_source_is_simply_removed(r):
    """The journal says the move made the new copy from these very bytes: the old one is the
    move's own source, not a conflict."""
    write_config(r)
    write(r.lib / "schedule.json", {"s": 1})
    _prepare(r)
    write(r.lib / "schedule.json", {"s": 1})                 # the same bytes, back again
    done = _prepare(r)
    assert not (r.lib / "schedule.json").exists() and done.report.parked == 0


# ---- the snapshot (pick 4) ----------------------------------------------------------------------

def _zip(folder):
    zips = list((folder / ".snapshot").glob("*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        return set(zf.namelist())


def test_the_snapshot_holds_the_small_records_and_never_the_library_itself(r):
    layout_317(r)
    write(r.lib / "loom" / "_beds" / KEY_NEL / "song.mp3", b"MUSIC")
    _prepare(r)
    names = _zip(r.lib / "_moonglade")
    for want in ("achievements.json", "telemetry.json", "train_guard.json", "runs.db",
                 "jobs.jsonl", "organize_manifest.csv", "toolbox_presets.json",
                 "account_prefs/%s.json" % KEY_NEL, "branding.json",
                 "loom/_submits/%s.jsonl" % KEY_NEL):
        assert want in names, want
    for never in ("catalog.db", "images/a_m1.png", "gallery/thumbs/m1.jpg",
                  "logs/moonglade.log", "loom/_beds/%s/song.mp3" % KEY_NEL,
                  "gallery/cache/_badges/a1.png"):
        assert never not in names, never


def test_the_snapshot_goes_after_five_clean_server_starts(r):
    layout_317(r)
    _prepare(r, "server")                    # the move itself: not a clean start
    snaps = (r.local / ".snapshot", r.lib / "_moonglade" / ".snapshot")
    for _ in range(4):
        _prepare(r, "server")
        assert all(s.exists() for s in snaps)
    for _ in range(3):
        _prepare(r, "cli")                   # the command line never counts
        _prepare(r, "mcp")
    assert all(s.exists() for s in snaps)
    done = _prepare(r, "server")             # the fifth clean server start
    assert not any(s.exists() for s in snaps)
    assert any("after 5 clean starts" in line for _lvl, line in done.report.lines)
    assert not any(s.exists() for s in snaps)


def test_a_start_that_moves_or_parks_starts_the_count_again(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _prepare(r, "server")
    for _ in range(3):
        _prepare(r, "server")
    write(r.lib / "schedule.json", {"written": "back"})     # an older install wrote again
    _prepare(r, "server")
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert journal["clean_starts"] == 0
    for _ in range(4):
        _prepare(r, "server")
    assert (r.lib / "_moonglade" / ".snapshot").exists()
    _prepare(r, "server")
    assert not (r.lib / "_moonglade" / ".snapshot").exists()


# ---- the locks ----------------------------------------------------------------------------------

def test_a_lock_held_by_a_live_start_stops_this_one_with_a_plain_sentence(r, monkeypatch):
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.3)
    r.local.mkdir(parents=True)
    (r.local / ".lock").write_text(str(os.getppid()), encoding="ascii")   # alive: our parent
    with pytest.raises(migrate.MoveStopped) as e:
        msetup.prepare("server")
    assert "Another Moonglade start is still tidying" in str(e.value)
    assert (r.local / ".lock").exists(), "a live start's lock is never broken"


def test_the_library_lock_is_honoured_too(r, monkeypatch):
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.3)
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    (r.lib / "_moonglade").mkdir()
    (r.lib / "_moonglade" / ".lock").write_text(str(os.getppid()), encoding="ascii")
    with pytest.raises(migrate.MoveStopped) as e:
        _prepare(r)
    assert str(r.lib) in str(e.value)
    assert (r.lib / "jobs.jsonl").is_file(), "nothing moved without the lock"
    assert not (r.local / ".lock").exists(), "the install lock is released on the way out"


def test_a_dead_start_s_lock_is_taken_over(r):
    r.local.mkdir(parents=True)
    (r.local / ".lock").write_text("999999999", encoding="ascii")          # no such process
    msetup.prepare("cli")
    assert not (r.local / ".lock").exists()


def test_a_lock_untouched_for_too_long_is_taken_over(r):
    r.local.mkdir(parents=True)
    lock = r.local / ".lock"
    lock.write_text(str(os.getppid()), encoding="ascii")
    old = lock.stat().st_mtime - migrate.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    msetup.prepare("cli")
    assert not lock.exists()


def test_the_lock_check_never_signals_a_process():
    """On Windows os.kill(pid, 0) would TERMINATE the process: the liveness check must only
    ever query it."""
    import inspect
    src = inspect.getsource(migrate._pid_alive)
    win = src[src.index('if sys.platform == "win32":'):src.index("    try:\n        os.kill")]
    assert "os.kill" not in win
    assert migrate._pid_alive(os.getppid()) is True
    assert migrate._pid_alive(999999999) is False
