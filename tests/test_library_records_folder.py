"""The library's own records move into `<library>/_moonglade/` (3.20.0, "the move", item 2).

moonglade.paths.state_path(out, name) is out/_moonglade/name and reports_path(out, name) is
out/_moonglade/reports/name. A real start (moonglade.gallery's main()) and every command-line
run (`python -m moonglade`) bring a library's old layout across once, through
moonglade.migrate.open_library():

  * COPIED, folders included, the old ones left for one release so 3.19 still works: every
    state record (achievements, telemetry, schedule, the reconcile stamp, jobs, raw tasks,
    runs.db through SQLite's own backup, the per-account folders, logs/, the install-wide
    legacy preset files) and every report (the integrity reports and marks, the audit,
    verify and organize lists, the curation import's undo files);
  * MOVED: train_guard.json, a spend guard that must never exist twice;
  * NEVER TOUCHED: catalog.db, the pictures, YYYY-MM/, images/, videos/, imported/, loom/,
    gallery/, _deleted/, _duplicates/ -- and the library-side branding.json nothing reads.

What was brought across is written down in _moonglade/MOVED.json. A reader asks the new place
and falls back to the old one only while the record is missing there and not recorded.
"""
import ast
import inspect
import json
import logging
import os
import sqlite3
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import integrity
from moonglade import logs as mlog
from moonglade import migrate as mig
from moonglade import paths
from moonglade import runs

STATE_FILES = ("achievements.json", "telemetry.json", "schedule.json",
               "reconcile_stamp.json", "jobs.jsonl", "raw_tasks.jsonl")
STATE_FOLDERS = ("account_prefs", "account_state", "prompt_snippets", "toolbox_presets",
                 "view_presets", "logs")
LEGACY_PRESETS = ("toolbox_presets.json", "prompt_snippets.json", "view_presets.json")
REPORTS = ("integrity_report.csv", "integrity_report.json", "integrity_marks.json",
           "audit_report.csv", "verify_report.csv", "organize_manifest.csv")
SNAPSHOT = "curation_pre_import_20261004-120000.json"
# The library itself: never touched.
UNTOUCHED = ("catalog.db", "2023-10", "2026-07", "images", "videos", "imported", "loom",
             "gallery", "_deleted", "_duplicates", "branding.json")


def _w(p, data=""):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")
    return p


@pytest.fixture
def old_library(tmp_path):
    """A 3.19 library shaped like D:'s: monthly folders from an --organize, its 10 MB undo
    list (small here), a LIVE install-wide toolbox_presets.json beside an empty per-account
    folder, a library-side branding.json nothing reads, and every record at the top."""
    lib = tmp_path / "pixai_backup"
    key = g._account_key("tester")
    # the library itself
    lib.mkdir()
    g.save_catalog(lib / "catalog.db", [{f: "" for f in g.CATALOG_FIELDS} | {
        "media_id": "1", "filename": "2023-10/a_1.png", "created_at": "2023-10-01T00:00:00"}])
    _w(lib / "2023-10" / "a_1.png", b"PNG1")
    _w(lib / "2026-07" / "b_2.png", b"PNG2")
    _w(lib / "images" / "c_3.png", b"PNG3")
    _w(lib / "videos" / "clip_4.mp4", b"MP4")
    _w(lib / "imported" / "ref_5.png", b"PNG5")
    _w(lib / "loom" / "kv" / "x.json", "{}")
    _w(lib / "gallery" / "thumbs" / "1.jpg", b"JPG")
    _w(lib / "_deleted" / "old_6.png", b"PNG6")
    _w(lib / "_duplicates" / "images" / "dupe_1.png", b"PNG1")
    _w(lib / "branding.json", '{"mark": "an old library-side choice"}')
    # the records
    _w(lib / "achievements.json", '{"earned": {}}')
    _w(lib / "telemetry.json", '{"counters": {"organize_runs": 1}}')
    _w(lib / "schedule.json", '{"enabled": false}')
    _w(lib / "train_guard.json", '{"basic": {}}')
    _w(lib / "reconcile_stamp.json", '{"at": "2026-10-01T00:00:00Z"}')
    _w(lib / "jobs.jsonl", '{"job_id": "j1", "status": "done"}\n')
    _w(lib / "raw_tasks.jsonl", '{"id": "t1"}\n')
    db = sqlite3.connect(str(lib / "runs.db"))
    db.execute("CREATE TABLE runs (id TEXT)")
    db.execute("INSERT INTO runs VALUES ('r1')")
    db.commit()
    db.close()
    _w(lib / "account_prefs" / (key + ".json"), '{"theme": "night"}')
    _w(lib / "account_state" / (key + ".json"), '{"poke": 1}')
    _w(lib / "account_state" / (key + ".lock"), "")                # a lock: never copied
    (lib / "prompt_snippets").mkdir()
    (lib / "toolbox_presets").mkdir()                               # EMPTY, as on D:
    _w(lib / "view_presets" / (key + ".json"), "{}")
    _w(lib / "logs" / "moonglade.log", "2026-10-04 an old line\n")
    _w(lib / "logs" / "moonglade.log.2026-10-03", "older\n")
    _w(lib / "toolbox_presets.json", json.dumps(
        {"from-before": {"label": "From Before", "scene_id": "", "prompt": "x",
                         "model_id": "9"}}))
    _w(lib / "prompt_snippets.json", "[]")
    _w(lib / "view_presets.json", "{}")
    _w(lib / "integrity_report.csv", "media_id,problem\n")
    _w(lib / "integrity_report.json", json.dumps(
        {"format": integrity.REPORT_FORMAT, "counts": {"ok": 3},
         "verified_at": "2026-10-04T00:00:00Z"}))
    _w(lib / "integrity_marks.json", '{"m1": "lost"}')
    _w(lib / "integrity_report.lock", "")                           # transient: never copied
    _w(lib / "audit_report.csv", "a,b\n")
    _w(lib / "verify_report.csv", "a,b\n")
    _w(lib / "organize_manifest.csv",
       "old_path,new_path,ts\nimages/a_1.png,2023-10/a_1.png,2026-07-06T00:00:00\n")
    _w(lib / SNAPSHOT, "{}")
    return lib


def _census(lib, names):
    out = {}
    for name in names:
        p = lib / name
        for q in ([p] + sorted(p.rglob("*")) if p.is_dir() else [p]):
            st = q.stat()
            out[str(q.relative_to(lib))] = "dir" if q.is_dir() else (st.st_size, st.st_mtime_ns)
    return out


# ---- where things are ---------------------------------------------------------------------

def test_the_records_folder_and_its_reports(tmp_path):
    assert paths.state_path(tmp_path, "achievements.json") == \
        tmp_path / "_moonglade" / "achievements.json"
    assert paths.reports_path(tmp_path, "audit_report.csv") == \
        tmp_path / "_moonglade" / "reports" / "audit_report.csv"


def test_the_names_are_spelled_once(tmp_path):
    """moonglade.paths owns the lists the migration walks; the lint's own lists in
    tests/test_state_paths.py are a second spelling, and the two must agree."""
    from tests.test_state_paths import REPORT_NAMES, STATE_NAMES
    assert set(paths.STATE_NAMES) == set(STATE_NAMES)
    assert set(paths.REPORT_NAMES) == set(REPORT_NAMES)


# ---- the migration -----------------------------------------------------------------------

def test_the_old_layout_is_copied_into_moonglade(old_library):
    lib = old_library
    out = mig.migrate_library(lib)
    rec = lib / "_moonglade"
    assert not out.failed
    for name in STATE_FILES + LEGACY_PRESETS:
        assert (rec / name).read_bytes() == (lib / name).read_bytes(), name
    for name in REPORTS:
        assert (rec / "reports" / name).read_bytes() == (lib / name).read_bytes(), name
    assert (rec / "reports" / SNAPSHOT).is_file()
    for name in STATE_FOLDERS:
        assert (rec / name).is_dir(), name
    key = g._account_key("tester")
    assert (rec / "account_prefs" / (key + ".json")).read_text() == '{"theme": "night"}'
    assert (rec / "logs" / "moonglade.log").read_text() == "2026-10-04 an old line\n"
    assert (rec / "logs" / "moonglade.log.2026-10-03").is_file()
    assert not list((rec / "toolbox_presets").iterdir())            # empty stays empty
    # locks are never brought across
    assert not (rec / "account_state" / (key + ".lock")).exists()
    assert not (rec / "reports" / "integrity_report.lock").exists()
    # runs.db, by SQLite's own backup: a real database with its rows
    con = sqlite3.connect(str(rec / "runs.db"))
    try:
        assert con.execute("SELECT id FROM runs").fetchall() == [("r1",)]
    finally:
        con.close()


def test_train_guard_is_moved_and_exists_in_exactly_one_place(old_library):
    lib = old_library
    mig.migrate_library(lib, move_guard=True)
    found = [p for p in lib.rglob("train_guard.json")]
    assert found == [lib / "_moonglade" / "train_guard.json"]
    assert json.loads(found[0].read_text()) == {"basic": {}}


def test_the_library_itself_is_never_touched(old_library):
    lib = old_library
    before = _census(lib, UNTOUCHED)
    mig.migrate_library(lib)
    assert _census(lib, UNTOUCHED) == before
    assert not (lib / "_moonglade" / "branding.json").exists()
    assert not (lib / "_moonglade" / "catalog.db").exists()


def test_the_manifest_records_what_moved(old_library):
    lib = old_library
    mig.migrate_library(lib, move_guard=True)
    doc = json.loads((lib / "_moonglade" / "MOVED.json").read_text(encoding="utf-8"))
    by = {e["name"]: e for e in doc["entries"]}
    assert by["train_guard.json"]["action"] == "moved"
    assert by["runs.db"]["action"] == "copied"
    assert by["logs"]["action"] == "copied"
    assert by["logs"]["source"] == "logs" and by["logs"]["dest"] == "_moonglade/logs"
    assert by["organize_manifest.csv"]["dest"] == "_moonglade/reports/organize_manifest.csv"
    assert by["organize_manifest.csv"]["size"] == (lib / "organize_manifest.csv").stat().st_size
    assert all(e["time"].endswith("Z") for e in doc["entries"])
    assert "integrity_report.lock" not in by and "branding.json" not in by


def test_a_second_run_is_a_no_op(old_library):
    lib = old_library
    mig.migrate_library(lib)
    manifest = lib / "_moonglade" / "MOVED.json"
    before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
    tree = _census(lib, [p.name for p in lib.iterdir()])
    again = mig.migrate_library(lib)
    assert not again.done and not again.failed
    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before
    assert _census(lib, [p.name for p in lib.iterdir()]) == tree


def test_downgrade_safety_what_3_19_reads_is_still_there(old_library):
    """Every old record a 3.19 reader needs is still where it was, except the one moved
    on purpose (train_guard.json)."""
    lib = old_library
    mig.migrate_library(lib, move_guard=True)
    for name in STATE_FILES + LEGACY_PRESETS + REPORTS + ("runs.db", SNAPSHOT):
        assert (lib / name).is_file(), name
    for name in STATE_FOLDERS:
        assert (lib / name).is_dir(), name
    assert not (lib / "train_guard.json").exists()


def test_a_new_library_gets_an_empty_records_folder(tmp_path):
    lib = tmp_path / "fresh"
    lib.mkdir()
    out = mig.migrate_library(lib)
    assert not out.done and not out.failed
    assert (lib / "_moonglade" / "reports").is_dir()
    assert json.loads((lib / "_moonglade" / "MOVED.json").read_text())["entries"] == []


def test_no_library_yet_is_left_alone(tmp_path):
    out = mig.migrate_library(tmp_path / "not-there")
    assert not out.done and not out.failed
    assert not (tmp_path / "not-there").exists()


# ---- readers -----------------------------------------------------------------------------

def test_a_reader_with_an_unmigrated_library_still_works(old_library):
    lib = old_library
    assert paths.state_path(lib, "achievements.json") == lib / "achievements.json"
    assert paths.reports_path(lib, "organize_manifest.csv") == lib / "organize_manifest.csv"
    assert integrity.read_summary(lib)["counts"] == {"ok": 3}
    assert runs.RunsStore(lib).path == lib / "runs.db"
    assert mlog.log_path(lib) == lib / "logs" / "moonglade.log"
    assert g.TrainGuard(paths.state_path(lib, "train_guard.json")).path == \
        lib / "train_guard.json"


def test_after_the_migration_readers_use_moonglade(old_library):
    lib = old_library
    mig.migrate_library(lib, move_guard=True)
    rec = lib / "_moonglade"
    assert paths.state_path(lib, "achievements.json") == rec / "achievements.json"
    assert paths.state_path(lib, "train_guard.json") == rec / "train_guard.json"
    assert paths.reports_path(lib, "organize_manifest.csv") == \
        rec / "reports" / "organize_manifest.csv"
    assert integrity.read_summary(lib)["counts"] == {"ok": 3}
    assert runs.RunsStore(lib).path == rec / "runs.db"
    assert mlog.log_path(lib) == rec / "logs" / "moonglade.log"


def test_a_record_the_app_creates_lands_in_moonglade(tmp_path):
    """A library with nothing to bring across: a new record goes straight to _moonglade/,
    whose folder the resolver makes (the library itself must already be there)."""
    lib = tmp_path / "lib"
    lib.mkdir()
    integrity.set_mark(lib, "m1", integrity.MARKS[0])
    assert (lib / "_moonglade" / "reports" / "integrity_marks.json").is_file()
    core._stamp_reconcile(lib, 1, 0)
    assert (lib / "_moonglade" / "reconcile_stamp.json").is_file()
    assert not (tmp_path / "nowhere" / "_moonglade").exists()
    paths.state_path(tmp_path / "nowhere", "telemetry.json")         # no library: no folder
    assert not (tmp_path / "nowhere").exists()


def test_the_legacy_presets_fallback_still_finds_the_live_file_after_the_copy(old_library,
                                                                              monkeypatch,
                                                                              pixai):
    """D:'s per-account toolbox_presets/ is EMPTY and its install-wide toolbox_presets.json
    is LIVE: after the copy the fallback reads the copy in _moonglade/, and the old root copy
    is a leftover."""
    from tests.conftest import login_client
    lib = old_library
    mig.migrate_library(lib)
    cli = login_client(lib)
    assert set(cli.get("/api/presets").get_json()["presets"]) == {"from-before"}
    # proof it is the copy that is read: the old one could be deleted and nothing changes
    (lib / "toolbox_presets.json").rename(lib / "toolbox_presets.json.gone")
    assert set(cli.get("/api/presets").get_json()["presets"]) == {"from-before"}


def test_organize_revert_reads_the_manifest_where_it_now_is(old_library, capsys):
    lib = old_library
    mig.migrate_library(lib)
    core.cmd_undo_organize(SimpleNamespace(out=str(lib), dry_run=True), lib)
    said = capsys.readouterr().out
    assert "Reverting 1 recorded move(s)" in said


def test_organize_revert_falls_back_to_the_old_root_copy(old_library, capsys):
    lib = old_library
    core.cmd_undo_organize(SimpleNamespace(out=str(lib), dry_run=True), lib)
    assert "Reverting 1 recorded move(s)" in capsys.readouterr().out


def test_a_cleared_manifest_is_never_read_again_from_the_old_copy(old_library, capsys):
    """--undo-organize clears its manifest once it has reverted. After the move, the stale
    old copy at the library root must not bring the reverted moves back."""
    lib = old_library
    mig.migrate_library(lib)
    paths.reports_path(lib, "organize_manifest.csv").unlink()
    core.cmd_undo_organize(SimpleNamespace(out=str(lib), dry_run=True), lib)
    assert "nothing to undo" in capsys.readouterr().out


# ---- failure never stops a start ---------------------------------------------------------

def test_a_locked_train_guard_stays_put_and_is_still_read(old_library, monkeypatch):
    lib = old_library
    real = os.replace

    def replace(src, dst):
        if Path(src).name == "train_guard.json":
            raise PermissionError("in use")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", replace)
    out = mig.migrate_library(lib, move_guard=True)
    assert [f[0] for f in out.failed] == ["train_guard.json"]
    assert (lib / "train_guard.json").is_file()
    assert not (lib / "_moonglade" / "train_guard.json").exists()     # still ONE place
    assert paths.state_path(lib, "train_guard.json") == lib / "train_guard.json"
    monkeypatch.setattr(os, "replace", real)
    again = mig.migrate_library(lib, move_guard=True)
    assert [e["name"] for e in again.done] == ["train_guard.json"]
    assert [p for p in lib.rglob("train_guard.json")] == [lib / "_moonglade" / "train_guard.json"]


def test_a_read_only_library_logs_once_and_the_start_carries_on(old_library, monkeypatch,
                                                                caplog):
    lib = old_library
    real_mkdir = Path.mkdir

    def mkdir(self, *a, **k):
        if "_moonglade" in self.parts:
            raise PermissionError("read-only")
        return real_mkdir(self, *a, **k)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    with caplog.at_level(logging.DEBUG, logger="moonglade"):
        out = mig.open_library(lib)                    # the entry points' call: never raises
    assert out.failed
    mine = [r for r in caplog.records if r.name == mig.LOGGER_NAME]
    assert len(mine) == 1 and mine[0].levelno == logging.WARNING
    assert paths.state_path(lib, "achievements.json") == lib / "achievements.json"
    assert integrity.read_summary(lib)["counts"] == {"ok": 3}


def test_open_library_never_raises(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(mig, "migrate_library", boom)
    assert mig.open_library(tmp_path).failed


# ---- the log moves with logs/ ------------------------------------------------------------

@pytest.fixture
def fresh_logging():
    mlog._reset_for_tests()
    yield
    mlog._reset_for_tests()


def test_the_log_is_reopened_in_the_new_logs_folder(old_library, fresh_logging):
    """Logging opens before the library is brought across -- in the old logs/, where the
    unmigrated library still keeps it. open_library() copies logs/ across, re-points the file
    log at _moonglade/logs/, and writes what it did there, once."""
    lib = old_library
    mlog.setup_logging(lib)
    logging.getLogger("moonglade").info("before the move")
    mig.open_library(lib)
    logging.getLogger("moonglade").info("after the move")
    for h in logging.getLogger().handlers:
        h.flush()
    new = (lib / "_moonglade" / "logs" / "moonglade.log").read_text(encoding="utf-8")
    old = (lib / "logs" / "moonglade.log").read_text(encoding="utf-8")
    assert "an old line" in new and "before the move" in new        # the copy carried them
    assert "after the move" in new and "after the move" not in old
    assert "Tidied" in new                                          # the one line, in the file
    handlers = [h for h in logging.getLogger().handlers
                if isinstance(h, logging.FileHandler)]
    assert len(handlers) == 1


def test_reopen_is_a_no_op_without_logging_or_when_already_there(tmp_path, fresh_logging):
    assert mlog.reopen(tmp_path) is False                # not set up: nothing to re-point
    mlog.setup_logging(tmp_path)
    assert mlog.reopen(tmp_path) is False                # already writing there


# ---- the entry points --------------------------------------------------------------------

def _calls(fn):
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    calls = sorted((n.lineno, n.col_offset,
                    getattr(n.func, "attr", None) or getattr(n.func, "id", None))
                   for n in ast.walk(tree) if isinstance(n, ast.Call))
    return [c[2] for c in calls]


def test_a_real_start_opens_the_library_before_the_app_reads_a_record():
    names = _calls(g.main)
    assert "open_library" in names, "main() does not bring the library's records across"
    at = names.index("open_library")
    assert names.index("setup_logging") < at
    assert names.index("port_owner") < at, "a refused start must not move the spend guard"
    assert at < names.index("create_app")


def test_the_command_line_opens_the_library_before_any_command_runs():
    names = _calls(core.main)
    assert "open_library" in names, "the CLI does not bring the library's records across"
    at = names.index("open_library")
    assert names.index("setup_logging") < at
    for first in ("set_telemetry_out", "_ensure_db"):
        if first in names:
            assert at < names.index(first), first


# ---- review round: the spend guard after a round trip to 3.19, and beside the CLI -------

def _guard_files(lib):
    return sorted(str(p.relative_to(lib)).replace("\\", "/") for p in lib.rglob("train_guard.json"))


def test_the_spend_guard_survives_a_round_trip_to_3_19(old_library):
    """3.20 moves the guard; the rollback note says to move it back for 3.19; 3.19 writes it;
    3.20 starts again. MOVED.json already names it -- yet the guard must be read, and moved
    again, from where 3.19 left it, never from an empty new path."""
    lib = old_library
    mig.migrate_library(lib, move_guard=True)                       # 3.20's first start
    assert _guard_files(lib) == ["_moonglade/train_guard.json"]
    os.replace(lib / "_moonglade" / "train_guard.json", lib / "train_guard.json")   # rollback
    (lib / "train_guard.json").write_text('{"basic": {"armed-on-3.19": 1}}', encoding="utf-8")
    # back on 3.20, before its start has run: read where it is
    assert paths.state_path(lib, "train_guard.json") == lib / "train_guard.json"
    mig.migrate_library(lib, move_guard=True)                       # 3.20's next start
    assert _guard_files(lib) == ["_moonglade/train_guard.json"]
    guard = g.TrainGuard(paths.state_path(lib, "train_guard.json"))
    assert guard._load()["basic"] == {"armed-on-3.19": 1}
    assert "train_guard.json" not in [n for _, n in mig.leftovers(lib)]


def test_the_command_line_never_moves_the_spend_guard(old_library):
    """Only the server's start moves the guard, before its TrainGuard exists. A command-line
    run beside a running server copies the other records and leaves the guard alone."""
    lib = old_library
    mig.open_library(lib)                                           # what the CLI calls
    assert _guard_files(lib) == ["train_guard.json"]
    assert paths.state_path(lib, "train_guard.json") == lib / "train_guard.json"
    assert (lib / "_moonglade" / "achievements.json").is_file()     # the rest came across


def test_the_server_reads_the_guard_where_it_is_at_each_use(old_library):
    """The server's guard is asked for its path at each use, so a start that later moves it
    (or a round trip) never leaves the server writing where nobody reads."""
    lib = old_library
    guard = g.TrainGuard(lambda: paths.state_path(lib, "train_guard.json"))
    assert guard.path == lib / "train_guard.json"
    mig.migrate_library(lib, move_guard=True)
    assert guard.path == lib / "_moonglade" / "train_guard.json"
    guard._save({"basic": {"k": 1}, "retried": {}, "paid": {}})
    assert _guard_files(lib) == ["_moonglade/train_guard.json"]


def test_create_app_builds_its_guard_on_a_path_asked_at_each_use():
    tree = ast.parse(textwrap.dedent(inspect.getsource(g.create_app)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "TrainGuard"]
    assert len(calls) == 1 and isinstance(calls[0].args[0], ast.Lambda), \
        "the server's TrainGuard must take a callable, not a path resolved once"


def test_only_the_servers_start_moves_the_guard():
    names = _calls(g.main)
    assert "open_library" in names
    tree = ast.parse(textwrap.dedent(inspect.getsource(g.main)))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "open_library")
    assert {k.arg: ast.unparse(k.value) for k in call.keywords}.get("move_guard") == "True"
    tree = ast.parse(textwrap.dedent(inspect.getsource(core.main)))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "open_library")
    assert "move_guard" not in {k.arg for k in call.keywords}


# ---- review round: a folder is brought across whole or not at all ------------------------

def _refuse_copy_of(monkeypatch, filename):
    real = mig.shutil.copy2

    def copy2(src, dst, *a, **k):
        if Path(src).name == filename:
            raise PermissionError("locked: %s" % src)
        return real(src, dst, *a, **k)
    monkeypatch.setattr(mig.shutil, "copy2", copy2)
    return real


def test_a_locked_file_mid_folder_leaves_the_folder_where_it_was(old_library, monkeypatch):
    """One file in account_prefs/ that cannot be read: the new folder must not appear without
    it (the app would read it, and About would call the old folder -- the only full copy --
    safe to delete). Nothing is recorded, no half copy is left, and the next start retries."""
    lib = old_library
    (lib / "account_prefs" / "second.json").write_text('{"b": 2}', encoding="utf-8")
    real = _refuse_copy_of(monkeypatch, "second.json")
    out = mig.migrate_library(lib)
    assert "account_prefs" in [f[0] for f in out.failed]
    assert not (lib / "_moonglade" / "account_prefs").exists()
    assert not [p for p in (lib / "_moonglade").iterdir() if ".copying-" in p.name]
    assert "account_prefs" not in paths.moved_names(paths.records_manifest(lib))
    assert paths.state_path(lib, "account_prefs") == lib / "account_prefs"
    assert "account_prefs" + os.sep not in [n for _, n in mig.leftovers(lib)]
    monkeypatch.setattr(mig.shutil, "copy2", real)
    mig.migrate_library(lib)
    assert (lib / "_moonglade" / "account_prefs" / "second.json").read_text() == '{"b": 2}'
    assert paths.state_path(lib, "account_prefs") == lib / "_moonglade" / "account_prefs"


def test_an_unreadable_subfolder_aborts_the_folder(old_library, monkeypatch):
    """os.walk skips a folder it cannot list unless told otherwise: the copy would look whole
    and be recorded. It is aborted instead."""
    lib = old_library
    sub = lib / "account_state" / "older"
    sub.mkdir()
    (sub / "kept.json").write_text("{}", encoding="utf-8")
    real_scandir = os.scandir

    def scandir(path="."):
        if Path(path) == sub:
            raise PermissionError("cannot list %s" % path)
        return real_scandir(path)
    monkeypatch.setattr(os, "scandir", scandir)
    out = mig.migrate_library(lib)
    assert "account_state" in [f[0] for f in out.failed]
    assert not (lib / "_moonglade" / "account_state").exists()
    assert "account_state" not in paths.moved_names(paths.records_manifest(lib))


def test_about_lists_only_what_the_migration_recorded(old_library):
    """A new copy the migration did not make (put there by hand, or by a run that died before
    writing MOVED.json) is not enough to call the old one safe to delete."""
    lib = old_library
    (lib / "_moonglade").mkdir()
    (lib / "_moonglade" / "achievements.json").write_text('{"earned": {}}', encoding="utf-8")
    assert "achievements.json" not in [n for _, n in mig.leftovers(lib)]
