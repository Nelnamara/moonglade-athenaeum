"""After a library's move has finished, the new home always wins (moonglade.migrate._fold_in).

An older install still on the library (another PC on 3.17-3.19, or this one gone back to an
earlier version) writes its OLD homes after the move -- into files the move had emptied, so
what it writes holds only its own few additions. The next start stops once and says so;
started again, it brings that in. Before this fix the bring-in kept whichever copy was newer,
which was always the older install's partial file: the full new home was set aside, then
deleted with the safety copy five clean starts later (the Runs history and its spend
reservations, the integrity marks, a login's stores, the Loom's boards).

Now the new home is never replaced, and what the older copy adds is folded in:

  * runs.db (the Runs, and the reservation rows the spend path relies on): both files pass
    SQLite's integrity check, then every row of the older copy the new home lacks (by primary
    key) goes in, table by table, in one transaction. A run both hold keeps the new home's row.
  * integrity_marks.json: every media id's mark from both; where both marked one, the new
    home's mark stays and the older one is logged.
  * a login's stores and a Loom board: every key from both; on a clash the new home's value
    stays and the older one is logged. A board only the older install made comes across.
  * job lists by unseen lines, JSON records by union with grow-only counters at their max.
  * anything that can't be merged (a report) is set aside and named; the new home stays.

The first move keeps its own rules (dev/tests/test_move_safety.py).
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from moonglade import integrity
from moonglade import migrate
from moonglade import runs
from moonglade import setup as msetup
from tests.move_layouts import KEY_NEL, rig, start, write, write_config


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _moved(r):
    """A library whose move has finished: what the first 3.20 start leaves."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "before-the-move"}\n')
    start(r)
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert journal["finished"]


def _later(path):
    """Stamp `path` as written after the move (the older install's write)."""
    later = path.stat().st_mtime + 120
    os.utime(path, (later, later))
    return path


def _older_install_writes(path, data):
    return _later(write(path, data))


def _bring_in(r):
    """The start after the older install wrote stops once (close it); the next brings it in."""
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "An older Moonglade is still using the library" in str(e.value)
    return start(r)


def _said(done):
    return " ".join(line for _lvl, line in done.report.all_lines())


def _parked(r):
    folder = r.lib / "_moonglade" / ".snapshot" / "parked"
    return sorted(p.name for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


def _hold_open(path):
    """Another process holding `path` open the way 3.19's log handler holds its log while its
    server runs (until it is killed): it writes one line, then sits idle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import logging, sys, time\n"
         "h = logging.FileHandler(sys.argv[1], encoding='utf-8')\n"
         "h.emit(logging.makeLogRecord({'msg': 'serving'}))\n"
         "print('ready', flush=True)\n"
         "time.sleep(60)\n", str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    assert holder.stdout.readline().strip() == "ready"
    return holder


# ---- an older install still serving the library, idle, when its writes are brought in -------

@pytest.mark.skipif(sys.platform != "win32",
                    reason="Windows refuses to rename a file another program holds open")
def test_an_idle_older_install_still_holding_its_log_stops_every_bring_in(r):
    """An older install still serving the library but idle writes nothing between two starts,
    so "nothing more was written" alone never means it was closed: while it holds its old log
    open, every start stops, and its spend guard and runs.db stay where it reads them. Closed,
    the next start brings them in."""
    from moonglade.gallery import TrainGuard
    _moved(r)
    log = r.lib / "logs" / "moonglade.log"
    holder = _hold_open(log)
    try:
        guard = {"basic": {}, "paid": {},
                 "retried": {"T": {"at": time.time(), "state": "done", "new_id": "X"}}}
        _older_install_writes(r.lib / "train_guard.json", guard)
        old = _old_store(r)
        old.reserve("run-C", "Nel", status="planning")
        _later(old.path)
        with pytest.raises(msetup.MoveStopped) as e:
            start(r)
        assert "An older Moonglade is still using the library" in str(e.value)
        for _ in range(2):
            with pytest.raises(msetup.MoveStopped) as e:
                start(r)
            assert str(e.value) == migrate.OLDER_RUNNING_WORDS % (log, r.lib)
            assert json.loads((r.lib / "train_guard.json").read_text()) == guard
            assert (r.lib / "runs.db").is_file()
            assert _old_store(r).get("run-C")["status"] == "planning"
        assert not (r.lib / "_moonglade" / "records" / "train_guard.json").exists()
    finally:
        holder.kill()
        holder.wait()
    start(r)                                    # closed: what it wrote is brought in
    assert not (r.lib / "train_guard.json").exists() and not (r.lib / "runs.db").exists()
    rec = r.lib / "_moonglade" / "records"
    assert TrainGuard(rec / "train_guard.json").retry_state("T") == \
        {"state": "done", "new_id": "X"}
    assert runs.RunsStore(r.lib).get("run-C")["status"] == "planning"


@pytest.mark.skipif(sys.platform != "win32",
                    reason="Windows refuses to rename a file another program holds open")
def test_a_moment_s_hold_on_the_old_log_is_waited_out(r):
    """A program that has the old log open for a moment (a sync tool, a virus scan reading the
    last lines 3.19 wrote) is waited out like any other short hold: the move goes ahead."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    log = write(r.lib / "logs" / "moonglade.log", "3.19's last lines\n")
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\n"
         "f = open(sys.argv[1], 'a')\n"
         "print('ready', flush=True)\n"
         "time.sleep(0.4)\n"
         "f.close()\n"
         "time.sleep(60)\n", str(log)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert holder.stdout.readline().strip() == "ready"
        start(r)
    finally:
        holder.kill()
        holder.wait()
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file()
    assert not (r.lib / "jobs.jsonl").exists()


def test_a_bring_in_cut_short_is_not_taken_for_an_older_install_on_the_next_start(
        r, monkeypatch):
    """A bring-in that stops part-way (here the database merge) has already folded some of
    what the older install wrote. The next start, with nothing more written, carries on: it
    never says an older Moonglade is still using the library when nothing is."""
    _moved(r)
    runs.RunsStore(r.lib).reserve("run-A", "Nel", status="planning")
    _older_install_writes(r.lib / "jobs.jsonl", '{"id": "older-install"}\n')
    old = _old_store(r)
    old.reserve("run-C", "Nel", status="planning")
    _later(old.path)
    with pytest.raises(msetup.MoveStopped):
        start(r)                                  # told to close it
    real, failed = migrate._fold_db, {"n": 0}

    def fold_once(*a, **k):
        if not failed["n"]:
            failed["n"] = 1
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **k)
    monkeypatch.setattr(migrate, "_fold_db", fold_once)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "still using" not in str(e.value)
    assert not (r.lib / "jobs.jsonl").exists(), "the job list was brought in first"
    start(r)
    assert not (r.lib / "runs.db").exists()
    assert runs.RunsStore(r.lib).get("run-C")["status"] == "planning"
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    assert "held_back" not in journal


# ---- the spend guard: whichever entry blocks longer --------------------------------------------

def test_the_spend_guard_keeps_whichever_entry_blocks_longer(r):
    """A retry PixAI took blocks that failed run for good; an unclear one only for a day. The
    older install's guard starts empty after the move, so it offers Retry on a run the new home
    already retried, and its later, unclear attempt must never replace the new home's "done".
    The same for a Basic start: a later "started" (a minute) never replaces an "ambiguous"
    (15 minutes) still standing."""
    from moonglade.gallery import TrainGuard
    _moved(r)
    now = time.time()
    rec = r.lib / "_moonglade" / "records" / "train_guard.json"
    write(rec, {"basic": {"K": {"at": now - 300, "state": "ambiguous"}},
                "retried": {"T": {"at": now - 3 * 86400, "state": "done", "new_id": "X"}},
                "paid": {}})
    _older_install_writes(r.lib / "train_guard.json", {
        "basic": {"K": {"at": now - 120, "state": "started"}},
        "retried": {"T": {"at": now - 2 * 86400, "state": "ambiguous", "new_id": ""}},
        "paid": {}})
    _bring_in(r)
    tg = TrainGuard(rec)
    assert tg.retry_state("T") == {"state": "done", "new_id": "X"}, "the retry stays refused"
    assert tg.basic_blocked("K") is not None, "the unclear start still blocks"


def test_the_guard_merge_by_when_each_block_ends():
    now = 1_000_000.0
    a = {"basic": {"K1": {"at": now, "state": "started"}},
         "retried": {"T1": {"at": now, "state": "ambiguous", "new_id": ""},
                     "T2": {"at": now - 90 * 86400, "state": "done", "new_id": "new-home"}},
         "paid": {"submit:1": {"at": now - 600, "state": "ambiguous", "status": "a"}}}
    b = {"basic": {"K1": {"at": now - 60, "state": "ambiguous"}},
         "retried": {"T1": {"at": now - 30 * 86400, "state": "done", "new_id": "older"},
                     "T2": {"at": now, "state": "done", "new_id": "older"}},
         "paid": {"submit:1": {"at": now - 60, "state": "armed", "status": "b"}}}
    got = migrate._merge_guard(a, b, False)
    assert got["basic"]["K1"]["state"] == "ambiguous", "15 minutes beats a minute"
    assert got["retried"]["T1"]["state"] == "done", "a done retry always wins"
    assert got["retried"]["T2"]["new_id"] == "new-home", "both done: the new home's"
    assert got["paid"]["submit:1"]["status"] == "b", "the confirm whose block ends later"
    assert migrate._merge_guard(b, a, False)["retried"]["T2"]["new_id"] == "older"


# ---- runs.db: the Runs and their spend reservations ---------------------------------------------

def _old_store(r):
    """3.19's RunsStore: the same schema, at the library's top (state_path(out_dir, name))."""
    st = runs.RunsStore(r.lib)
    st.path = r.lib / "runs.db"
    return st


def _rows(path, sql):
    con = sqlite3.connect(str(path))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_runs_db_keeps_every_new_home_row_and_gains_the_older_install_s(r):
    _moved(r)
    new = runs.RunsStore(r.lib)                      # the new home, records\runs.db
    new.reserve("run-A", "Nel", mode="loop", status="planning")      # a live reservation
    new.put_jobs("run-A", [{"cell": 0, "prompt": "a0"}, {"cell": 1, "prompt": "a1"}])
    new.reserve("run-B", "Nel", status="sent", covered=4)
    new.put_jobs("run-B", [{"cell": 0, "prompt": "b0", "paid": 1}])
    new.reserve("run-S", "Nel", status="sent", reason="the new home's")
    new.put_jobs("run-S", [{"cell": 0, "prompt": "s0", "state": "paid"}])
    before = _rows(new.path, "SELECT * FROM runs ORDER BY run_id")
    jobs_before = _rows(new.path, "SELECT * FROM run_jobs ORDER BY run_id, cell")

    # 3.19's RunsStore makes a fresh runs.db at the library's top, the old home.
    old = _old_store(r)
    old.reserve("run-C", "Nel", status="planning")                   # its own reservation
    old.put_jobs("run-C", [{"cell": 0, "prompt": "c0"}])
    old.reserve("run-S", "Nel", status="refused", reason="the older copy's")
    old.put_jobs("run-S", [{"cell": 0, "prompt": "s0, older"}, {"cell": 1, "prompt": "s1"}])
    _later(old.path)

    done = _bring_in(r)
    db = new.path
    got = {row[0]: row for row in _rows(db, "SELECT * FROM runs")}
    for row in before:                               # every new-home row, unchanged
        assert got[row[0]] == row
    assert set(got) == {"run-A", "run-B", "run-S", "run-C"}
    assert new.get("run-C")["status"] == "planning", "the older install's reservation arrived"
    assert new.get("run-S")["reason"] == "the new home's", "a run both hold keeps the new row"
    jobs = _rows(db, "SELECT * FROM run_jobs ORDER BY run_id, cell")
    for row in jobs_before:
        assert row in jobs
    keys = [(j[0], j[1]) for j in jobs]
    assert ("run-C", 0) in keys and ("run-S", 1) in keys
    assert [j[3] for j in jobs if (j[0], j[1]) == ("run-S", 0)] == ["s0"]
    assert _rows(db, "PRAGMA integrity_check") == [("ok",)]
    assert not (r.lib / "runs.db").exists()
    assert "runs.db" not in " ".join(_parked(r))
    assert "Merged runs.db into _moonglade/records/runs.db" in _said(done)


def test_a_runs_db_that_fails_its_check_is_set_aside_and_the_new_home_stays(r):
    _moved(r)
    new = runs.RunsStore(r.lib)
    new.reserve("run-A", "Nel", status="planning")
    whole = new.path.read_bytes()
    _older_install_writes(r.lib / "runs.db", b"not a database at all")
    done = _bring_in(r)
    assert new.path.read_bytes() == whole
    assert _parked(r) == ["runs.db"]
    assert "set aside" in _said(done) and "integrity check" in _said(done)


# ---- the owner's integrity marks ----------------------------------------------------------------

def test_integrity_marks_keep_the_new_home_s_and_gain_the_older_install_s(r):
    _moved(r)
    new_marks = {"format": 1, "marks": {
        "m1": {"mark": "lost", "at": "2026-10-07T10:00:00Z"},
        "m2": {"mark": "kept", "at": "2026-10-07T10:01:00Z"}}}
    write(r.lib / "_moonglade" / "decisions" / "integrity_marks.json", new_marks)
    # 3.19's set_mark on a missing file writes one holding only the mark it just set.
    _older_install_writes(r.lib / "integrity_marks.json", {"format": 1, "marks": {
        "m1": {"mark": "kept", "at": "2026-10-08T09:00:00Z"},
        "m3": {"mark": "lost", "at": "2026-10-08T09:05:00Z"}}})
    done = _bring_in(r)
    marks = integrity.read_marks(r.lib)
    assert marks["m1"] == new_marks["marks"]["m1"], "a clash keeps the new home's mark"
    assert marks["m2"] == new_marks["marks"]["m2"]
    assert marks["m3"] == {"mark": "lost", "at": "2026-10-08T09:05:00Z"}
    assert not (r.lib / "integrity_marks.json").exists()
    said = _said(done)
    assert "m1=" in said and "kept" in said, "the older copy's clashing mark is logged"


# ---- a login's own stores -----------------------------------------------------------------------

def test_a_login_s_stores_keep_the_new_home_s_values_and_gain_the_older_install_s(r):
    _moved(r)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    write(acc / "prefs.json", {"guide.gallery": "done", "theme": "dusk"})
    write(acc / "snippets.json", ["golden hour", "rim light"])
    _older_install_writes(r.lib / "account_prefs" / (KEY_NEL + ".json"),
                          {"theme": "classic", "grid.size": "large"})
    _older_install_writes(r.lib / "prompt_snippets" / (KEY_NEL + ".json"),
                          ["rim light", "film grain"])
    done = _bring_in(r)
    assert json.loads((acc / "prefs.json").read_text()) == \
        {"guide.gallery": "done", "theme": "dusk", "grid.size": "large"}
    assert json.loads((acc / "snippets.json").read_text()) == \
        ["golden hour", "rim light", "film grain"]
    assert not (r.lib / "account_prefs").exists() and not (r.lib / "prompt_snippets").exists()
    assert 'theme="classic"' in _said(done), "the older copy's clashing value is logged"


# ---- the Loom's boards --------------------------------------------------------------------------

def test_a_loom_board_keeps_the_new_home_s_and_the_older_install_s_new_board_arrives(r):
    _moved(r)
    kv_new = r.lib / "_moonglade" / "loom" / "kv" / KEY_NEL
    kv_old = r.lib / "loom" / "kv" / KEY_NEL
    board = "storyboard%3Av2%3Aproj%3Ab1.json"
    mine = {"title": "Act one (final cut)", "shots": [{"id": 1}, {"id": 2}, {"id": 3}]}
    write(kv_new / board, mine)
    write(r.lib / "_moonglade" / "loom" / "_submits" / (KEY_NEL + ".jsonl"), '{"s": 1}\n')
    _older_install_writes(kv_old / board, {"title": "Act one", "shots": [{"id": 1}],
                                           "note": "written by the older install"})
    _older_install_writes(kv_old / "storyboard%3Av2%3Aproj%3Ab2.json", {"title": "Act two"})
    _older_install_writes(r.lib / "loom" / "_submits" / (KEY_NEL + ".jsonl"), '{"s": 2}\n')
    done = _bring_in(r)
    got = json.loads((kv_new / board).read_text())
    assert got["title"] == mine["title"] and got["shots"] == mine["shots"]
    assert got["note"] == "written by the older install"
    assert json.loads((kv_new / "storyboard%3Av2%3Aproj%3Ab2.json").read_text()) == \
        {"title": "Act two"}
    assert (r.lib / "_moonglade" / "loom" / "_submits" / (KEY_NEL + ".jsonl")).read_text() \
        .splitlines() == ['{"s": 1}', '{"s": 2}']
    assert not (r.lib / "loom").exists()
    from moonglade import gallery as g
    assert {p.name for p in g._loom_board_files(r.lib)} == \
        {board, "storyboard%3Av2%3Aproj%3Ab2.json"}
    assert '"Act one"' in _said(done)


# ---- the rest -----------------------------------------------------------------------------------

def test_a_newer_old_copy_never_replaces_the_new_home(r):
    """The first move keeps the newer of two copies; after it, the new home wins whatever the
    times say, and what only the older copy holds is added."""
    _moved(r)
    write(r.lib / "_moonglade" / "records" / "schedule.json",
          {"enabled": True, "interval_hours": 6})
    _older_install_writes(r.lib / "schedule.json", {"enabled": False, "action": "sync"})
    _bring_in(r)
    assert json.loads((r.lib / "_moonglade" / "records" / "schedule.json").read_text()) == \
        {"enabled": True, "interval_hours": 6, "action": "sync"}
    assert _parked(r) == []


def test_records_merge_with_counters_at_their_max_and_jobs_by_unseen_lines(r):
    _moved(r)
    write(r.lib / "_moonglade" / "records" / "telemetry.json",
          {"counters": {"gens": 40, "loom": 3}, "sets": {"m": ["x"]}})
    _older_install_writes(r.lib / "telemetry.json",
                          {"counters": {"gens": 2, "mirror": 1}, "sets": {"m": ["y"]}})
    _older_install_writes(r.lib / "jobs.jsonl", '{"id": "older-install"}\n')
    _bring_in(r)
    tel = json.loads((r.lib / "_moonglade" / "records" / "telemetry.json").read_text())
    assert tel["counters"] == {"gens": 40, "loom": 3, "mirror": 1}
    assert sorted(tel["sets"]["m"]) == ["x", "y"]
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").read_text().splitlines() == \
        ['{"id": "before-the-move"}', '{"id": "older-install"}']


def test_what_can_t_be_merged_is_set_aside_and_named_and_the_new_home_stays(r):
    _moved(r)
    write(r.lib / "_moonglade" / "records" / "verify_report.csv", "status\nnew home\n")
    _older_install_writes(r.lib / "verify_report.csv", "status\nolder install\n")
    done = _bring_in(r)
    assert (r.lib / "_moonglade" / "records" / "verify_report.csv").read_text() == \
        "status\nnew home\n"
    assert _parked(r) == ["verify_report.csv"]
    said = _said(done)
    assert "Kept _moonglade/records/verify_report.csv, the new home" in said
    assert "verify_report.csv" in said and "set aside" in said
