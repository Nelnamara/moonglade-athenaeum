"""The move's safety rules (SPEC_3.20_REBUILD.md "Rules every lane follows"; B4, S9, pick 4):

  * THE SAFE MOVE: on one volume, one rename (journalled first); across volumes (or for a
    database) copy into a temp beside the destination, flush, verify (sha256; a database by
    integrity_check and row counts), journal, swap within one folder, journal, delete the
    source. A copy that does not verify is never swapped in, and the source stays. A copy
    keeps its source's modified time, so "keep the newer" compares real times.
  * RESUME: a start that dies at any step is finished by the next one, from the journal.
  * NEVER RENAMED ACROSS VOLUMES: where a rename between folders fails (another drive), the
    move copies instead, so a library on another drive moves the same way.
  * CONFLICTS (B4): a new copy wins only when the journal says the move made it. A fresh file
    that appeared in the new home first never wins over the real data: JSONL is merged,
    telemetry/achievements/the spend guard merged where the format allows, anything else keeps
    the newer and parks the other. Nothing is deleted on a guess.
  * THE SNAPSHOT (pick 4): a zip before each run that moves anything, deleted after 5 clean
    server starts -- counted by the server once it has served a while or stopped cleanly,
    never at prepare(), and never the start that moved (S1).
  * THE LOCKS: a lock held past its wait stops the start with a plain sentence; a lock is
    taken over only from a holder that is gone; a lock is only ever released by its holder.
  * A READ-ONLY OR BUSY FILE (S2): a verified source is made writable before it is deleted,
    and a refusal is tried again; what stops a start says why and what to do.
"""
import errno
import json
import os
import zipfile
from pathlib import Path

import pytest

from moonglade import migrate
from moonglade import setup as msetup
from tests.move_layouts import (KEY_NEL, db_rows, layout_317, make_db, rig, start,
                                write, write_config)


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


class _Crash(BaseException):
    """A process dying mid-move: nothing catches it, the lock is left behind."""


def _prepare(r, kind="launcher"):
    """A start that may move the library (X1): the launcher's, or the server's."""
    return start(r, kind)


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


@pytest.mark.parametrize("step", ["copied", "verified", "swapped", "made", "renamed"])
def test_a_crash_at_each_step_is_finished_by_the_next_start(r, monkeypatch, step):
    """The spend guard is the example: the item a lost copy would hurt most. The copy's steps
    are crashed with the library treated as another volume; "renamed" is the one-volume move
    cut short between the rename and the journal saying so."""
    write_config(r)
    write(_guard_src(r), GUARD)
    is_guard = lambda *a, **k: "train_guard" in str(a[0])        # noqa: E731
    with monkeypatch.context() as m:
        if step != "renamed":
            m.setattr(migrate, "_same_volume", lambda *a: False)
        if step == "renamed":
            real_save = migrate.Journal.save

            def save(self):
                item = self.doc.get("items", {}).get("_moonglade/records/train_guard.json")
                if item and item.get("state") == "made" and item.get("how") == "renamed":
                    raise _Crash()
                return real_save(self)
            m.setattr(migrate.Journal, "save", save)
        elif step == "copied":          # the temp is written, the process dies before verifying
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
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
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


def test_where_a_rename_between_folders_fails_the_move_copies(r, monkeypatch):
    """Force the copy path everywhere: os.replace between two folders fails as it would
    between two volumes, and the renames are refused outright. The move still completes,
    because it then only ever swaps a temp into its own folder."""
    layout_317(r)
    real_replace = os.replace

    def replace(a, b, *x, **k):
        if os.path.dirname(os.path.abspath(a)) != os.path.dirname(os.path.abspath(b)):
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(a, b, *x, **k)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "rename", lambda *a, **k: (_ for _ in ()).throw(
        OSError(errno.EXDEV, "cross-device link")))
    monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(
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


def _served(r):
    """One server start that went on to serve for a while (or was stopped cleanly): what
    moonglade.gallery.main counts, after the bind."""
    done = _prepare(r, "server")
    done.count_clean_start()
    return done


def test_the_snapshot_goes_after_five_clean_server_starts(r):
    layout_317(r)
    _prepare(r, "launcher")                  # the move itself
    snaps = (r.local / ".snapshot", r.lib / "_moonglade" / ".snapshot")
    _served(r)                               # the launcher's own server: the start that moved
    for _ in range(4):
        _served(r)
        assert all(s.exists() for s in snaps)
    for _ in range(3):
        _prepare(r, "cli")                   # the command line never counts
        _prepare(r, "mcp")
        _prepare(r, "server")                # a server that never served counts nothing
    assert all(s.exists() for s in snaps)
    done = _prepare(r, "server")
    said = done.count_clean_start()          # the fifth clean server start
    assert not any(s.exists() for s in snaps)
    assert any("after 5 clean starts" in line for _lvl, line in said.lines)
    assert done.count_clean_start().lines == [], "a start is counted once, never twice"


def test_prepare_never_counts_a_start(r):
    """S1: a server that refuses its port or falls over as it starts has run prepare() too;
    only serving (or a clean stop) counts."""
    layout_317(r)
    _prepare(r, "launcher")
    for _ in range(8):
        _prepare(r, "server")
    assert (r.lib / "_moonglade" / ".snapshot").exists()
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert not journal.get("clean_starts") and journal["skip_next"] is True


def _fixer_copy(r, name):
    """What moonglade.outside saves before it changes a file outside the app: a copy in
    local\\.snapshot\\outside\\, here read-only, as shutil.copy2 keeps a shortcut's attribute."""
    import stat
    from moonglade import outside
    copy = outside.snapshot_dir() / name
    write(copy, b"the shortcut as it was")
    os.chmod(copy, stat.S_IREAD)
    assert outside.snapshot_dir() == r.local / ".snapshot" / "outside"
    return copy


def test_the_whole_install_snapshot_goes_with_the_fixers_copies_and_again_if_remade(r):
    """Pick 4 covers the fixer's copies too: at the fifth clean server start the WHOLE
    local\\.snapshot\\ goes, outside\\ and its read-only copies included. A fix made later
    makes the folder again, and five clean starts on, it goes again."""
    layout_317(r)
    _served(r)                               # the move itself: not counted
    _fixer_copy(r, "Moonglade Athenaeum.lnk")
    for _ in range(4):
        _served(r)
    assert (r.local / ".snapshot" / "outside").is_dir()
    _served(r)
    assert not (r.local / ".snapshot").exists()

    _fixer_copy(r, "task-Moonglade sync.xml")         # a later fix, after the snapshot went
    for _ in range(4):
        _served(r)
    assert (r.local / ".snapshot").exists()
    _served(r)
    assert not (r.local / ".snapshot").exists()


def test_a_fixer_copy_starts_the_count_again(r):
    """N8: a copy the fixer keeps is not deleted at the very next clean start."""
    from moonglade import outside
    layout_317(r)
    _served(r)
    for _ in range(4):
        _served(r)
    outside._snapshot_bytes(outside.snapshot_dir(), "task-x.xml", b"<Task/>")
    _served(r)
    assert (outside.snapshot_dir()).is_dir(), "kept five clean starts on, not one"


def test_a_start_that_moves_or_parks_starts_the_count_again(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    _served(r)
    for _ in range(3):
        _served(r)
    write(r.lib / "schedule.json", {"written": "back"})     # restored from an old backup
    _served(r)                                              # it moved: not counted
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert journal["clean_starts"] == 0
    assert len(list((r.lib / "_moonglade" / ".snapshot").glob("*.zip"))) == 2, \
        "a zip for every run that moves anything (X3)"
    for _ in range(4):
        _served(r)
    assert (r.lib / "_moonglade" / ".snapshot").exists()
    _served(r)
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


def test_a_live_holder_s_lock_is_never_taken_however_old(r, monkeypatch):
    """S3: on this PC a lock is taken over only from a holder that is gone. A slow move (a
    first move of GBs, a network drive) touches its lock, but a live holder is never broken
    even when it has not."""
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.3)
    r.local.mkdir(parents=True)
    lock = r.local / ".lock"
    import time
    lock.write_text("%d %s %.3f" % (os.getppid(), migrate._host(), time.time()),
                    encoding="ascii")
    old = lock.stat().st_mtime - migrate.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    with pytest.raises(migrate.MoveStopped):
        msetup.prepare("cli")
    assert lock.exists()


def test_a_lock_whose_number_was_reused_is_taken_over(r):
    """The holder died and its process number now belongs to a process started later: that
    process is not the holder."""
    r.local.mkdir(parents=True)
    lock = r.local / ".lock"
    started = migrate._process_started(os.getppid())
    if started is None:
        pytest.skip("this system cannot say when a process started")
    lock.write_text("%d %s %.3f" % (os.getppid(), migrate._host(), started - 3600),
                    encoding="ascii")
    msetup.prepare("cli")
    assert not lock.exists()


def test_another_pc_s_lock_counts_until_it_goes_untouched(r, monkeypatch):
    """A library on a network drive: another PC's process number means nothing here, so its
    lock counts as alive until it has gone LOCK_STALE_S untouched."""
    monkeypatch.setattr(migrate, "LOCK_WAIT_S", 0.3)
    r.local.mkdir(parents=True)
    lock = r.local / ".lock"
    lock.write_text("999999999 another-pc 1.000", encoding="ascii")
    with pytest.raises(migrate.MoveStopped):
        msetup.prepare("cli")
    old = lock.stat().st_mtime - migrate.LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    msetup.prepare("cli")
    assert not lock.exists()


def test_a_lock_is_released_only_by_its_holder(tmp_path):
    lock = migrate.FolderLock(tmp_path, "a folder").acquire()
    (tmp_path / ".lock").write_text("12345 another-pc 1.000", encoding="ascii")  # taken over
    lock.release()
    assert (tmp_path / ".lock").read_text(encoding="ascii") == "12345 another-pc 1.000"


def test_a_long_step_keeps_every_held_lock_fresh(tmp_path, monkeypatch):
    """S3: the install lock is touched from inside the library half's long copies too."""
    monkeypatch.setattr(migrate, "HEARTBEAT_S", 0.0)
    (tmp_path / "a").mkdir()
    a = migrate.FolderLock(tmp_path / "a", "a").acquire()
    old = a.path.stat().st_mtime - 100
    os.utime(a.path, (old, old))
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (3 << 20))
    migrate._sha256(big)
    assert a.path.stat().st_mtime > old + 50
    a.release()


def test_a_folder_this_user_cannot_write_in_says_so(tmp_path, monkeypatch):
    """S2: a lock that cannot be made because the folder refuses this user is not "another
    start is still tidying": it says the folder is read-only for you, at once."""
    real = os.open

    def refuse(path, *a, **k):
        if str(path).endswith(".lock"):
            raise PermissionError(13, "Access is denied")
        return real(path, *a, **k)
    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr(migrate, "_folder_writable", lambda folder: False)
    with pytest.raises(migrate.MoveStopped) as e:
        migrate.FolderLock(tmp_path, "the app folder").acquire(wait=30)
    assert "writable for you" in str(e.value)


def test_a_dead_start_s_lock_that_can_t_be_removed_waits_then_says_so(tmp_path, monkeypatch):
    """#20: a dead start's lock this user can't delete (another account's file, a share
    without delete rights) used to spin forever at full CPU with nothing on screen. It now
    waits like any other holder, pausing between tries, then stops with a plain sentence."""
    import time
    lock = migrate.FolderLock(tmp_path, "the app folder")
    lock.path.write_text("999999999 %s 1.000" % migrate._host(), encoding="ascii")
    real, tries = os.remove, {"n": 0}

    def remove(p, *a, **k):
        if str(p) == str(lock.path):
            tries["n"] += 1
            e = PermissionError(13, "Access is denied")
            e.winerror = 5
            raise e
        return real(p, *a, **k)
    monkeypatch.setattr(os, "remove", remove)
    began = time.monotonic()
    with pytest.raises(migrate.MoveStopped) as e:
        lock.acquire(wait=0.5)
    assert time.monotonic() - began < 5
    assert 2 <= tries["n"] <= 20, "it pauses between tries rather than spin"
    text = str(e.value)
    assert "can't remove the old lock" in text and str(lock.path) in text


# ---- every swap waits out a moment's hold (#14) ---------------------------------------------------

def _refusing_replace(monkeypatch, refuse):
    """os.replace refusing (PermissionError, winerror 32) where refuse(dest name) says so."""
    real = os.replace

    def replace(a, b, *x, **k):
        if refuse(os.path.basename(str(b))):
            e = PermissionError(13, "The process cannot access the file")
            e.winerror = 32
            raise e
        return real(a, b, *x, **k)
    monkeypatch.setattr(os, "replace", replace)


def test_a_swap_windows_refuses_for_a_moment_is_tried_again(r, monkeypatch):
    """A scanner, the search indexer or OneDrive opening a file just written makes os.replace
    fail for a moment. Every swap the move makes -- the journal, a moved file, the safety
    zip -- goes through one helper that tries again, so the start carries on."""
    monkeypatch.setattr(migrate, "REMOVE_BACKOFF_S", 0.0)
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)     # copy, then swap
    write_config(r)
    write(_guard_src(r), GUARD)
    held = {}

    def refuse(name):
        key = "zip" if name.endswith(".zip") else name
        if key in (".journal.json", "train_guard.json", "zip") and held.get(key, 0) < 2:
            held[key] = held.get(key, 0) + 1
            return True
        return False
    _refusing_replace(monkeypatch, refuse)
    _prepare(r)
    assert held == {".journal.json": 2, "train_guard.json": 2, "zip": 2}
    assert json.loads(_guard_dest(r).read_text()) == GUARD
    assert not _guard_src(r).exists()


def test_a_swap_refused_for_good_stops_with_what_to_do(r, monkeypatch):
    monkeypatch.setattr(migrate, "REMOVE_BACKOFF_S", 0.0)
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
    write_config(r)
    write(_guard_src(r), GUARD)
    _refusing_replace(monkeypatch, lambda name: name == "train_guard.json")
    with pytest.raises(migrate.MoveStopped) as e:
        _prepare(r)
    assert "another program has it open" in str(e.value)
    assert json.loads(_guard_src(r).read_text()) == GUARD, "the source stays"


def test_every_swap_in_the_move_goes_through_the_retry_helper():
    import inspect
    src = inspect.getsource(migrate)
    body = src[:src.index("def _replace(")] + src[src.index("def _write_bytes("):]
    assert "os.replace(" not in body.replace('"""os.replace(', "")


def test_the_lock_check_never_signals_a_process():
    """On Windows os.kill(pid, 0) would TERMINATE the process: the liveness check must only
    ever query it."""
    import inspect
    src = inspect.getsource(migrate._pid_alive)
    win = src[src.index('if sys.platform == "win32":'):src.index("    try:\n        os.kill")]
    assert "os.kill" not in win
    assert migrate._pid_alive(os.getppid()) is True
    assert migrate._pid_alive(999999999) is False



# ---- "keep the newer" means the newer (rehearsal 1) ---------------------------------------------

@pytest.mark.parametrize("volumes", ["one", "two"])
def test_a_genuinely_newer_old_copy_wins(r, monkeypatch, volumes):
    """The copy-first 3.20 left a live schedule.json in _moonglade\\; an older install then
    wrote the library-top one, later. The move brings the first across, then meets the second:
    the second is newer and must win -- the move's own copy of the first is as old as the first,
    not as new as the moment it was made -- and the older one is set aside, never lost."""
    if volumes == "two":
        monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
    write_config(r)
    write(r.lib / "_moonglade" / "schedule.json", {"which": "older, _moonglade"})
    os.utime(r.lib / "_moonglade" / "schedule.json", (1_600_000_000, 1_600_000_000))
    write(r.lib / "schedule.json", {"which": "newer, library top"})
    os.utime(r.lib / "schedule.json", (1_700_000_000, 1_700_000_000))
    done = _prepare(r)
    got = json.loads((r.lib / "_moonglade" / "records" / "schedule.json").read_text())
    assert got == {"which": "newer, library top"}
    parked = list((r.lib / "_moonglade" / ".snapshot" / "parked").rglob("schedule.json*"))
    assert [json.loads(x.read_text()) for x in parked] == [{"which": "older, _moonglade"}]
    assert done.report.parked == 1


def test_two_logs_are_merged_not_parked(r):
    """Rehearsal 4: two copies of one log keep both, the older one's lines first."""
    write_config(r)
    write(r.lib / "_moonglade" / "logs" / "moonglade.log", "older line\n")
    os.utime(r.lib / "_moonglade" / "logs" / "moonglade.log", (1_600_000_000, 1_600_000_000))
    write(r.lib / "logs" / "moonglade.log", "newer line\n")
    _prepare(r)
    assert (r.local / "logs" / "moonglade.log").read_text() == "older line\nnewer line\n"
    assert not (r.lib / "_moonglade" / ".snapshot" / "parked").exists()


# ---- a read-only file, a moment's hold (S2) ------------------------------------------------------

def test_a_read_only_source_is_removed_once_its_copy_is_verified(r, monkeypatch):
    import stat
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
    write_config(r)
    write(_guard_src(r), GUARD)
    os.chmod(_guard_src(r), stat.S_IREAD)
    _prepare(r)
    assert json.loads(_guard_dest(r).read_text()) == GUARD
    assert not _guard_src(r).exists()


def test_a_moment_s_hold_is_tried_again(r, monkeypatch):
    monkeypatch.setattr(migrate, "REMOVE_BACKOFF_S", 0.0)
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
    write_config(r)
    write(_guard_src(r), GUARD)
    real, held = os.remove, {"n": 0}

    def remove(p, *a, **k):
        if "train_guard" in str(p) and held["n"] < 3:
            held["n"] += 1
            raise PermissionError(13, "The process cannot access the file")
        return real(p, *a, **k)
    monkeypatch.setattr(os, "remove", remove)
    _prepare(r)
    assert held["n"] == 3 and not _guard_src(r).exists()


def test_a_hold_that_lasts_stops_with_what_to_do(r, monkeypatch):
    monkeypatch.setattr(migrate, "REMOVE_BACKOFF_S", 0.0)
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)
    write_config(r)
    write(_guard_src(r), GUARD)
    real = os.remove

    def remove(p, *a, **k):
        if "train_guard" in str(p):
            e = PermissionError(13, "The process cannot access the file")
            e.winerror = 32
            raise e
        return real(p, *a, **k)
    monkeypatch.setattr(os, "remove", remove)
    with pytest.raises(migrate.MoveStopped) as e:
        _prepare(r)
    text = str(e.value)
    assert "another program has it open" in text
    assert "Close the program that has it open" in text
    assert "Nothing was lost" in text
    assert json.loads(_guard_dest(r).read_text()) == GUARD and _guard_src(r).exists()


def test_a_full_disk_says_so():
    e = OSError(28, "No space left on device")
    assert migrate._reason(e) == "the disk is full"
    assert "Free some space" in migrate._advice(e)
