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
    SQLite's integrity check, then every run only the older copy holds goes in whole, inside
    the new home itself, in one BEGIN IMMEDIATE transaction. A run both hold keeps the new
    home's rows whole (nothing of the older copy's is grafted onto it), and the older copy's
    run is named in the log. A busy older copy stops the start; a new home that fails its own
    check stops it too, and the older copy stays where it is.
  * integrity_marks.json: every media id's mark from both; where both marked one, the new
    home's mark stays and the older one is logged.
  * a login's stores: every key from both; on a clash the new home's value stays and the
    older one is logged.
  * the Loom's boards and cast library: merged inside the JSON text the Loom keeps in each
    file (the cast library member by member, a board key by key). A board only the older
    install made comes across; a value that can't be merged is kept beside the new home
    under a key of its own, outside the safety snapshot.
  * the spend guard entry by entry, whichever blocks longer; telemetry's counters added up,
    less what the move itself took (a copy put back, or saved across the move, is never
    counted twice), with the new home's copy in that run's safety zip first.
  * job lists by unseen lines, other JSON records by union.
  * anything that can't be merged (a report) is set aside and named; the new home stays.
  * an older install still holding its old log open stops every bring-in, idle or not.

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
    old.put_jobs("run-S", [{"cell": 0, "prompt": "s0, older", "task_id": "T-PAID-0"},
                           {"cell": 1, "prompt": "s1", "task_id": "T-PAID-1"}])
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
    assert sorted(jobs) == sorted(jobs_before + _rows(
        db, "SELECT * FROM run_jobs WHERE run_id = 'run-C'")), "only run-C's job came across"
    keys = [(j[0], j[1]) for j in jobs]
    assert ("run-C", 0) in keys
    assert ("run-S", 1) not in keys, "nothing of the older run-S is grafted onto the new one"
    assert [j[3] for j in jobs if (j[0], j[1]) == ("run-S", 0)] == ["s0"]
    assert _rows(db, "PRAGMA integrity_check") == [("ok",)]
    assert not (r.lib / "runs.db").exists()
    assert "runs.db" not in " ".join(_parked(r))
    said = _said(done)
    assert "Merged runs.db into _moonglade/records/runs.db" in said
    assert "run-S (status refused; task ids: T-PAID-0, T-PAID-1)" in said, \
        "the run the new home kept whole is named, with what the older copy said"


def test_the_runs_fold_writes_the_new_home_in_place(r):
    """runs.db is folded inside the new home itself, under SQLite's own write lock -- never a
    copy swapped over it -- so a server holding it open (another install serving the library)
    reads what was brought in and loses nothing it writes."""
    _moved(r)
    new = runs.RunsStore(r.lib)
    new.reserve("run-A", "Nel", status="planning")
    server = sqlite3.connect(str(new.path))
    try:
        assert server.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
        old = _old_store(r)
        old.reserve("run-C", "Nel", status="planning")
        _later(old.path)
        _bring_in(r)
        assert server.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall() == \
            [("run-A",), ("run-C",)], "the open connection sees the fold"
    finally:
        server.close()


def test_a_busy_older_runs_db_stops_the_start_and_is_never_set_aside(r):
    """An older runs.db another program holds locked is busy, not damaged: the start stops
    and says so, and it is neither parked nor read half-written."""
    _moved(r)
    runs.RunsStore(r.lib).reserve("run-A", "Nel", status="planning")
    old = _old_store(r)
    old.reserve("run-C", "Nel", status="planning")
    _later(old.path)
    with pytest.raises(msetup.MoveStopped):
        start(r)                                  # told to close it
    holder = sqlite3.connect(str(old.path), isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        with pytest.raises(msetup.MoveStopped) as e:
            start(r)
        assert "another program has it open" in str(e.value)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert (r.lib / "runs.db").is_file() and _parked(r) == []
    start(r)
    assert runs.RunsStore(r.lib).get("run-C")["status"] == "planning"


def test_a_new_home_that_fails_its_check_stops_and_the_older_copy_stays(r):
    """When the NEW home is the broken side -- its runs.db fails its integrity check, or a
    store won't parse -- the healthy older copy is never set aside for the damaged one to
    stay: the start stops and names the file."""
    _moved(r)
    rec = r.lib / "_moonglade" / "records" / "runs.db"
    write(rec, b"not a database at all")
    old = _old_store(r)
    old.reserve("run-C", "Nel", status="planning")
    _later(old.path)
    with pytest.raises(msetup.MoveStopped):
        start(r)                                  # told to close it
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert str(rec) in str(e.value) and "fails its own check" in str(e.value)
    assert (r.lib / "runs.db").is_file() and _parked(r) == []
    assert _old_store(r).get("run-C")["status"] == "planning"


def test_a_new_home_store_that_won_t_parse_stops_and_the_older_copy_stays(r):
    _moved(r)
    prefs = r.lib / "_moonglade" / "accounts" / KEY_NEL / "prefs.json"
    write(prefs, '{"theme": "dusk", "grid')
    older = _older_install_writes(r.lib / "account_prefs" / (KEY_NEL + ".json"),
                                  {"theme": "classic"})
    with pytest.raises(msetup.MoveStopped):
        start(r)
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert str(prefs) in str(e.value)
    assert json.loads(older.read_text()) == {"theme": "classic"} and _parked(r) == []


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


# ---- the Loom's boards and cast library ---------------------------------------------------------
# The Loom keeps every board and its cast library as JSON text -- window.storage.set(k,
# JSON.stringify(...)) (loom/master-storyboard.jsx's writeBoard, and the cast library's
# JSON.stringify(next)) -- and /api/loom/set stores that text as a JSON string
# (moonglade.gallery's _loom_kv_write: json.dumps(value)). So every kv file is JSON text inside
# a JSON string. The new home's values below go through the real route; the older install's
# are written the way the same route writes them, which the test checks first.

CASTLIB = "storyboard:v2:castlib"
ACTIVE = "storyboard:v2:active"
PROJ = "storyboard:v2:proj:"


def _loom_text(doc):
    """What the Loom hands /api/loom/set as a value: JSON.stringify(doc)."""
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False)


def _loom_file(doc):
    """A kv file as _loom_kv_write leaves it for that value."""
    return json.dumps(_loom_text(doc))


def _kv_name(key):
    from urllib.parse import quote
    return quote(key, safe="") + ".json"


def _member(lib_id, name):
    """A cast library member (loom/src/loom-cast-library.js memberFromAsset): the asset's
    fields and a stable libId."""
    return {"name": name, "kind": "image", "tag": "@image1", "mediaId": "m-" + lib_id,
            "thumbId": "", "source": "gallery", "lock": False, "libId": lib_id}


def _board(name, cards, **more):
    return dict({"name": name, "acts": [{"id": "act1", "name": "Act 1",
                                         "cards": [{"id": c} for c in cards]}],
                 "assets": []}, **more)


def _loom(r):
    """A logged-in client on the library, and the login's kv folders: new home, old home."""
    from moonglade.gallery import _account_key
    from tests.conftest import _TEST_USERNAME, login_client
    cli = login_client(r.lib)
    key = _account_key(_TEST_USERNAME)
    return cli, r.lib / "_moonglade" / "loom" / "kv" / key, r.lib / "loom" / "kv" / key


def _loom_get(cli, key):
    from urllib.parse import quote
    return cli.get("/api/loom/get?key=" + quote(key, safe="")).get_json()["value"]


def test_the_loom_s_cast_library_and_boards_merge_inside_their_json_text(r):
    """No real Loom file ever merged before: each parsed to a string, so it was set aside and
    deleted with the safety copy five clean starts later -- cast members and board edits the
    older install made after the move with it. Now the JSON text inside is merged: the cast
    library member by member (by libId, the new home's member on a clash), a board key by
    key (the new home's value on a clash), and the open-board pointer keeps the new home's."""
    _moved(r)
    cli, kv_new, kv_old = _loom(r)
    new_lib = {"v": 1, "members": [_member("L1", "Aria"), _member("L2", "Bram")]}
    b1 = _board("Act one (final cut)", ["c1", "c2", "c3"])
    for key, value in ((CASTLIB, _loom_text(new_lib)), (PROJ + "b1", _loom_text(b1)),
                       (ACTIVE, "b1")):
        assert cli.post("/api/loom/set", json={"key": key, "value": value}).get_json()["ok"]
    assert (kv_new / _kv_name(CASTLIB)).read_text() == _loom_file(new_lib), "the real shape"
    write(r.lib / "_moonglade" / "loom" / "_submits" / (KEY_NEL + ".jsonl"), '{"s": 1}\n')

    _older_install_writes(kv_old / _kv_name(CASTLIB), _loom_file(
        {"v": 1, "members": [_member("L9", "Cato"), _member("L1", "Aria, renamed there")]}))
    _older_install_writes(kv_old / _kv_name(PROJ + "b1"), _loom_file(
        _board("Act one", ["c1"], note="written by the older install")))
    _older_install_writes(kv_old / _kv_name(PROJ + "b2"), _loom_file(_board("Act two", [])))
    _older_install_writes(kv_old / _kv_name(ACTIVE), json.dumps("b2"))
    _older_install_writes(r.lib / "loom" / "_submits" / (KEY_NEL + ".jsonl"), '{"s": 2}\n')
    done = _bring_in(r)

    lib = json.loads(_loom_get(cli, CASTLIB))
    assert [m["libId"] for m in lib["members"]] == ["L1", "L2", "L9"]
    assert lib["members"][0]["name"] == "Aria", "a member both hold keeps the new home's"
    assert lib["v"] == 1
    got = json.loads(_loom_get(cli, PROJ + "b1"))
    assert got["name"] == b1["name"] and got["acts"] == b1["acts"]
    assert got["note"] == "written by the older install"
    assert json.loads(_loom_get(cli, PROJ + "b2")) == _board("Act two", [])
    assert _loom_get(cli, ACTIVE) == "b1"
    assert set(cli.get("/api/loom/list?prefix=" + PROJ).get_json()["keys"]) == \
        {PROJ + "b1", PROJ + "b2"}
    assert (r.lib / "_moonglade" / "loom" / "_submits" / (KEY_NEL + ".jsonl")).read_text() \
        .splitlines() == ['{"s": 1}', '{"s": 2}']
    assert not (r.lib / "loom").exists()
    assert _parked(r) == [], "nothing set aside for the sweep to delete"
    said = _said(done)
    assert "member L1=" in said and "Aria, renamed there" in said, "the clash is logged"
    assert "the open board=" in said


def test_a_loom_value_that_can_t_merge_is_kept_beside_under_its_own_key_for_good(r):
    """A Loom value whose two copies hold different kinds of things (here the older copy's
    text is a list, not a board) is kept beside the new home under a key of its own --
    outside the safety snapshot, so the five-start sweep never deletes it -- and the Loom
    lists it as a board of its own."""
    _moved(r)
    cli, kv_new, kv_old = _loom(r)
    b3 = _board("Act three", ["c1"])
    assert cli.post("/api/loom/set", json={"key": PROJ + "b3",
                                           "value": _loom_text(b3)}).get_json()["ok"]
    older = _loom_file(["not", "a", "board"])
    _older_install_writes(kv_old / _kv_name(PROJ + "b3"), older)
    done = _bring_in(r)
    assert json.loads(_loom_get(cli, PROJ + "b3")) == b3, "the new home stays"
    aside = [p for p in kv_new.iterdir() if p.name.startswith("storyboard%3Av2%3Aproj%3Ab3-older-")]
    assert len(aside) == 1 and aside[0].read_text() == older
    keys = cli.get("/api/loom/list?prefix=" + PROJ).get_json()["keys"]
    assert len(keys) == 2 and PROJ + "b3" in keys
    assert _parked(r) == []
    assert "both are kept" in _said(done)
    for _ in range(migrate.CLEAN_STARTS + 1):
        done.counted = False
        done.count_clean_start()
    assert not (r.lib / "_moonglade" / ".snapshot").exists(), "the sweep ran"
    assert aside[0].read_text() == older, "and kept it"


def test_a_loom_aside_cut_short_before_the_old_file_went_is_not_made_twice(r, monkeypatch):
    """The start dies after the older value is kept beside the new home and before the old
    file goes: the next start finds the value already kept (the same bytes, under a key of
    its own) and only removes the old file -- the Loom never lists two identical boards."""
    _moved(r)
    cli, kv_new, kv_old = _loom(r)
    b3 = _board("Act three", ["c1"])
    assert cli.post("/api/loom/set", json={"key": PROJ + "b3",
                                           "value": _loom_text(b3)}).get_json()["ok"]
    older = _loom_file(["not", "a", "board"])
    old_file = _older_install_writes(kv_old / _kv_name(PROJ + "b3"), older)
    with pytest.raises(msetup.MoveStopped):
        start(r)                                   # told to close it
    monkeypatch.setattr(migrate, "_same_volume", lambda *a: False)   # copied, then removed
    real = migrate._remove

    def die_removing_it(p):
        if os.path.normcase(str(p)) == os.path.normcase(str(old_file)):
            raise migrate._Failed("cut short")
        return real(p)
    monkeypatch.setattr(migrate, "_remove", die_removing_it)
    with pytest.raises(msetup.MoveStopped):
        start(r)

    def asides():
        return [p for p in kv_new.iterdir()
                if p.name.startswith("storyboard%3Av2%3Aproj%3Ab3-older-")]
    assert len(asides()) == 1 and old_file.exists()
    monkeypatch.setattr(migrate, "_remove", real)
    done = start(r)
    assert len(asides()) == 1 and asides()[0].read_text() == older
    assert not old_file.exists()
    said = _said(done)
    assert "already keeps the same" in said and asides()[0].name in said


def test_the_kept_beside_line_is_said_before_the_value_is_brought(r, monkeypatch):
    """The log names the Loom value it keeps beside the new home before bringing it, so a
    start cut short in that step still says where it went."""
    _moved(r)
    cli, kv_new, kv_old = _loom(r)
    assert cli.post("/api/loom/set", json={"key": PROJ + "b4", "value": _loom_text(
        _board("Act four", []))}).get_json()["ok"]
    _older_install_writes(kv_old / _kv_name(PROJ + "b4"), _loom_file(["a", "list"]))
    with pytest.raises(msetup.MoveStopped):
        start(r)
    seen = {}
    real = migrate._bring

    def bring(src, dest, kind, half, vouched=False):
        if "-older-" in os.path.basename(str(dest)):
            seen["said"] = " ".join(line for _l, line in half.report.all_lines())
        return real(src, dest, kind, half, vouched=vouched)
    monkeypatch.setattr(migrate, "_bring", bring)
    start(r)
    assert "Kept loom/kv/" in seen["said"] and "beside" in seen["said"]


def test_a_cut_off_emoji_in_a_clash_never_loses_the_move_s_log(tmp_path):
    """A Loom value can carry a lone UTF-16 surrogate (a cast member named with a cut-off
    emoji). The clash words are plain ASCII, and the log file is written whole whatever a line
    holds -- write_log never raises."""
    words = migrate._clash_words([("member L1", {"name": "Aria \ud83d"})])
    words.encode("utf-8")
    assert "\\ud83d" in words
    rep = migrate.Report()
    rep.item("In loom/kv/x the new home's value was kept; the older copy said: %s", "\ud83d")
    rep.info("The library is tidy.")
    log = tmp_path / "logs" / "moonglade.log"
    rep.write_log(log)
    text = log.read_text(encoding="utf-8")
    assert "the older copy said" in text and "The library is tidy." in text


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


def test_telemetry_counters_add_up_and_jobs_merge_by_unseen_lines(r):
    """The move emptied the older install's telemetry.json, and it counts by load-add-save from
    disk, so what it wrote holds only its own counts since: they add to the new home's. The
    maxima stay at their max, sets and days are unions, a flag is set if either set it, and
    the new home's baselines stay."""
    _moved(r)
    write(r.lib / "_moonglade" / "records" / "telemetry.json",
          {"counters": {"gens": 40, "loom": 3}, "maxima": {"lora_stacked": 3},
           "sets": {"m": ["x"]}, "flags": {"f1": 1}, "days": ["2026-10-07"],
           "day_lists": {"gen_days": ["2026-10-07"]},
           "baselines": {"goods:app-a": ["mark_1"]}})
    _older_install_writes(r.lib / "telemetry.json",
                          {"counters": {"gens": 2, "mirror": 1}, "maxima": {"lora_stacked": 5},
                           "sets": {"m": ["y"]}, "flags": {"f2": 1}, "days": ["2026-10-08"],
                           "day_lists": {"gen_days": ["2026-10-08"]},
                           "baselines": {"goods:app-a": ["mark_1", "mark_9"],
                                         "goods:app-b": ["mark_2"]}})
    _older_install_writes(r.lib / "jobs.jsonl", '{"id": "older-install"}\n')
    _bring_in(r)
    tel = json.loads((r.lib / "_moonglade" / "records" / "telemetry.json").read_text())
    assert tel["counters"] == {"gens": 42, "loom": 3, "mirror": 1}
    assert tel["maxima"] == {"lora_stacked": 5}
    assert sorted(tel["sets"]["m"]) == ["x", "y"]
    assert tel["flags"] == {"f1": 1, "f2": 1}
    assert tel["days"] == ["2026-10-07", "2026-10-08"]
    assert tel["day_lists"] == {"gen_days": ["2026-10-07", "2026-10-08"]}
    assert tel["baselines"] == {"goods:app-a": ["mark_1"], "goods:app-b": ["mark_2"]}
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").read_text().splitlines() == \
        ['{"id": "before-the-move"}', '{"id": "older-install"}']


# ---- telemetry: what the move already took is never counted twice --------------------------------

def _tel(r):
    return json.loads((r.lib / "_moonglade" / "records" / "telemetry.json").read_text())


def _tel_moved(r, gens=40):
    """A library whose first move took telemetry.json holding `gens` (by one rename, as it is
    on one drive), and whose new home has counted on since. Returns the pre-move bytes and
    their time."""
    write_config(r)
    old = write(r.lib / "telemetry.json", {"counters": {"gens": gens, "loom": 2}})
    before, mtime_ns = old.read_bytes(), old.stat().st_mtime_ns
    start(r)
    assert not old.exists() and _tel(r)["counters"] == {"gens": gens, "loom": 2}
    return before, mtime_ns


def _new_home_counts_on(r, **counters):
    p = r.lib / "_moonglade" / "records" / "telemetry.json"
    doc = json.loads(p.read_text())
    doc["counters"].update(counters)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_the_exact_pre_move_telemetry_put_back_with_its_own_time_changes_no_counter(r):
    """A backup restored with its original time: not written since, so nothing stops, and its
    bytes are exactly what the move took -- counted already."""
    before, mtime_ns = _tel_moved(r)
    _new_home_counts_on(r, gens=41)
    put_back = r.lib / "telemetry.json"
    put_back.write_bytes(before)
    os.utime(put_back, ns=(mtime_ns, mtime_ns))
    start(r)
    assert _tel(r)["counters"] == {"gens": 41, "loom": 2}
    assert not put_back.exists()


def test_the_exact_pre_move_telemetry_put_back_later_changes_no_counter(r):
    """The same bytes brought back with a new time (a sync tool): it reads as written since, so
    the start stops once, and the bring-in drops it -- those counts are the new home's
    already. (Before the fix: gens 41 + 40 = 81.)"""
    before, _ns = _tel_moved(r)
    _new_home_counts_on(r, gens=41)
    _older_install_writes(r.lib / "telemetry.json", before)
    done = _bring_in(r)
    assert _tel(r)["counters"] == {"gens": 41, "loom": 2}
    assert not (r.lib / "telemetry.json").exists()
    assert "exactly what the move took" in _said(done)


def test_a_pre_move_telemetry_plus_one_adds_exactly_one(r):
    """An older install that loaded telemetry.json before the move and saved it after, one
    generation later (or a restored backup counted on once): every counter is at least what
    the move took, so only the difference is added. (Before the fix: 45 + 41 = 86.)"""
    _tel_moved(r, gens=40)
    _new_home_counts_on(r, gens=45)
    _older_install_writes(r.lib / "telemetry.json", {"counters": {"gens": 41, "loom": 2}})
    _bring_in(r)
    assert _tel(r)["counters"] == {"gens": 46, "loom": 2}


def test_an_older_install_s_counts_since_the_move_add_as_they_are(r):
    """The move emptied the older install's home, so what it saves holds only its own counts
    since -- less than what the move took -- and they add whole."""
    _tel_moved(r, gens=40)
    _new_home_counts_on(r, gens=45)
    _older_install_writes(r.lib / "telemetry.json", {"counters": {"gens": 2, "mirror": 1}})
    _bring_in(r)
    assert _tel(r)["counters"] == {"gens": 47, "loom": 2, "mirror": 1}


def test_two_identical_later_telemetry_writes_add_twice(r):
    """An older install writes {"gens": 1} after each bring-in emptied its home again: the
    second copy has the very bytes the first fold took, but it is a new count, not the same
    file left behind. (Before the fix the second was removed as "already moved": 42, not 43.)"""
    _tel_moved(r, gens=40)
    _new_home_counts_on(r, gens=41)
    one = json.dumps({"counters": {"gens": 1}})
    _older_install_writes(r.lib / "telemetry.json", one)
    _bring_in(r)
    assert _tel(r)["counters"]["gens"] == 42
    p = write(r.lib / "telemetry.json", one)
    later = time.time() + 600
    os.utime(p, (later, later))
    _bring_in(r)
    assert _tel(r)["counters"]["gens"] == 43


def test_a_fold_cut_short_before_the_old_copy_went_is_not_counted_again(r, monkeypatch):
    """The fold wrote the new home, and the start died before the older copy was removed: the
    next start finds the very same file (bytes, time and size) and only removes it."""
    _tel_moved(r, gens=40)
    _new_home_counts_on(r, gens=41)
    older = _older_install_writes(r.lib / "telemetry.json", {"counters": {"gens": 1}})
    with pytest.raises(msetup.MoveStopped):
        start(r)                                   # told to close it
    real = migrate._remove

    def die_removing_it(p):
        if os.path.normcase(str(p)) == os.path.normcase(str(older)):
            raise migrate._Failed("cut short")
        return real(p)
    monkeypatch.setattr(migrate, "_remove", die_removing_it)
    with pytest.raises(msetup.MoveStopped):
        start(r)
    assert _tel(r)["counters"]["gens"] == 42 and older.exists()
    monkeypatch.setattr(migrate, "_remove", real)
    start(r)
    assert _tel(r)["counters"]["gens"] == 42
    assert not older.exists()


def test_the_new_home_s_telemetry_is_in_the_safety_copy_before_an_additive_fold(r):
    """Adding counts can't be undone by reading the file again, so the new home's own
    telemetry.json goes into that run's safety copy first."""
    import zipfile
    _tel_moved(r, gens=40)
    _new_home_counts_on(r, gens=45)
    _older_install_writes(r.lib / "telemetry.json", {"counters": {"gens": 2}})
    _bring_in(r)
    zips = sorted((r.lib / "_moonglade" / ".snapshot").glob("*.zip"),
                  key=lambda p: p.stat().st_mtime_ns)
    with zipfile.ZipFile(zips[-1]) as zf:
        kept = json.loads(zf.read("_moonglade/records/telemetry.json"))
        older = json.loads(zf.read("telemetry.json"))
    assert kept["counters"]["gens"] == 45 and older["counters"]["gens"] == 2
    assert _tel(r)["counters"]["gens"] == 47


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
