"""Old install and library layouts, built in a test's own folder, for the move's tests
(tests/test_move_*.py, tests/test_setup_prepare.py).

rig() pins every resolver the move uses to a folder of the test's own -- the app folder (the
old place the machine files are brought from, and the folder config.json is in), local/
inside it, a library beside it -- so nothing here can reach the checkout or a real install.
The layouts are the shapes the move must accept (SPEC_3.20_REBUILD.md, S14): 3.17 (D:'s
shape: the pack under its pre-v7 name, serve.txt with host and port, the library's records
at its top), 3.19, and C:'s copy-first 3.20 state (the live copies in local\\ and
_moonglade\\, the old ones left behind and recorded in MOVED.json).

No real file is opened: every config.json here is written by the test.
"""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from moonglade import backup as core
from moonglade import migrate
from moonglade import paths


def rig(tmp_path, monkeypatch):
    app = tmp_path / "app"
    local = app / "local"
    lib = tmp_path / "library"
    app.mkdir()
    lib.mkdir()
    monkeypatch.setattr(paths, "local_dir", lambda: local)
    monkeypatch.setattr(paths, "local_path", lambda name: local / name)
    monkeypatch.setattr(paths, "config_path", lambda: app / "config.json")
    monkeypatch.setattr(core, "_config_path", lambda: app / "config.json")
    monkeypatch.setattr(paths, "library_anchor", lambda: app)
    monkeypatch.setattr(migrate, "old_app_root", lambda: app)
    return SimpleNamespace(app=app, local=local, lib=lib, cfg=app / "config.json")


def write_config(r, **keys):
    doc = {"PIXAI_API_KEY": "sk-test-not-real", "AUTH_SECRET_KEY": "s",
           "AUTH_USERS": [{"username": "Nel", "password_hash": "x"}]}
    doc.update(keys)
    r.cfg.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def read_config(r):
    return json.loads(r.cfg.read_text(encoding="utf-8"))


def write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, (dict, list)):
        text = json.dumps(text)
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return p


def make_db(p, rows=3):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    try:
        con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, label TEXT)")
        con.executemany("INSERT INTO runs (label) VALUES (?)", [("r%d" % i,) for i in range(rows)])
        con.commit()
    finally:
        con.close()
    return p


def db_rows(p):
    con = sqlite3.connect(str(p))
    try:
        return [r[0] for r in con.execute("SELECT label FROM runs ORDER BY id")]
    finally:
        con.close()


KEY_NEL = paths.account_key("Nel")
KEY_NEL_LOWER = paths.account_key("nel")
KEY_GONE = paths.account_key("someone-removed")


def library_records(lib, base=None):
    """The 3.19 records at a library's top (or under `base`, 3.20's _moonglade\\)."""
    base = Path(base) if base is not None else Path(lib)
    write(base / "achievements.json", {"seen": ["a1"], "skin": "moonglade",
                                       "earned_at": {"a1": "2026-09-01"}})
    write(base / "telemetry.json", {"counters": {"gens": 5}, "sets": {"m": ["x"]},
                                    "days": ["2026-09-01"]})
    write(base / "schedule.json", {"enabled": True, "action": "sync", "interval_hours": 6})
    write(base / "train_guard.json", {"basic": {"k1": {"state": "ambiguous", "at": 100.0}},
                                      "retried": {}, "paid": {}})
    write(base / "reconcile_stamp.json", {"reconciled_at": "2026-09-01T00:00:00Z"})
    write(base / "jobs.jsonl", '{"id": "j1"}\n{"id": "j2"}\n')
    write(base / "raw_tasks.jsonl", '{"t": 1}\n')
    make_db(base / "runs.db")


def layout_317(r, logins=("Nel",)):
    """D:'s shape: v3.17. The pack under its pre-v7 name, serve.txt with host and port and no
    library, the library's records and reports at its top, the live shared toolbox presets."""
    write_config(r, AUTH_USERS=[{"username": u, "password_hash": "x"} for u in logins])
    write(r.app / "serve.txt", "--host 0.0.0.0 --port 5757\n")
    write(r.app / "moonglade.dat", b"PACK-317" * 64)
    write(r.app / "moonglade.dat.version", {"version": "6", "sha256": "x"})
    write(r.app / "branding.json", {"mark": "mark_2", "anim": "glow"})
    write(r.app / "mirror_session.json", {"jwt": "token-317"})
    write(r.app / "serve.log", "the launcher's log\n")
    write(r.app / "_container_cache" / "marks" / "mark_2.ico", b"ICO-2")
    library_records(r.lib)
    write(r.lib / "organize_manifest.csv", "old_path,new_path,ts\na.png,2025-01/a.png,t\n")
    write(r.lib / "verify_report.csv", "status,quarantined_file,surviving_keeper\n")
    write(r.lib / "toolbox_presets.json", {"scene-a": {"label": "A", "prompt": "p"}})
    write(r.lib / "account_prefs" / (KEY_NEL + ".json"), {"guide.gallery": "done"})
    write(r.lib / "logs" / "moonglade.log", "the library's log\n")
    write(r.lib / "loom" / "kv" / KEY_NEL / "storyboard%3Av2%3Aproj%3Ab1.json", {"b": 1})
    write(r.lib / "loom" / "_submits" / (KEY_NEL + ".jsonl"), '{"submit": "s1"}\n')
    write(r.lib / "branding.json", {"mark": "old"})
    write(r.lib / "gallery" / "cache" / "_badges" / "a1.png", b"BADGE")
    write(r.lib / "gallery" / "thumbs" / "m1.jpg", b"THUMB")
    write(r.lib / "images" / "a_m1.png", b"PICTURE")
    write(r.lib / "catalog.db", b"CATALOG")


def fingerprint_record(name, path, action="copied"):
    """A 3.20 MOVED.json entry for `name` whose old copy is at `path`, as 3.20 wrote it."""
    fp = migrate._fingerprint_320(path)
    return {"name": name, "source": "x", "dest": "y", "action": action, "time": "t",
            "size": 0, "source_print": fp, "dest_print": fp}


def layout_c_copy_first(r):
    """C:'s shape: the first 3.20 build ran (copy-first). The live copies are in local\\ and the
    library's _moonglade\\; the old copies were left behind, unchanged since, and MOVED.json
    records each one's fingerprint. serve.txt pins `--out pixai_backup --port 5057` while
    config.json's LIBRARY_DIR names another install's library (the exact disagreement)."""
    lib = r.app / "pixai_backup"
    lib.mkdir()
    r.lib = lib
    write_config(r, LIBRARY_DIR=r"D:\Moonglade Athenaeum\pixai_backup", PORT=5000,
                 READ_ONLY=True)
    # the old copies at the app root, then the live ones in local\ (they have since diverged)
    write(r.app / "serve.txt", "--out pixai_backup --port 5057\n")
    write(r.app / "branding.json", {"mark": "mark_1", "anim": "classic"})
    write(r.app / "branding_slots.json", {"banner_main": "old"})
    write(r.app / "serve.log", "the old launcher's log\n")
    write(r.app / "_container_cache" / "marks" / "mark_4.ico", b"ICO-4")
    local_entries = [fingerprint_record(n, r.app / n)
                     for n in ("serve.txt", "branding.json", "branding_slots.json")]
    write(r.local / "serve.txt", "--out pixai_backup --port 5057\n")
    write(r.local / "branding.json", {"mark": "mark_4", "anim": "aurora"})
    write(r.local / "branding_slots.json", {"banner_main": "live"})
    write(r.local / "moonglade.mgpack", b"PACK-320" * 64)
    write(r.local / "mirror_session.json", {"jwt": "token-320"})
    write(r.local / "serve.log", "the 3.20 launcher's log\n")
    write(r.local / "cache" / "marks" / "mark_4.ico", b"ICO-4")
    write(r.local / migrate.OLD_RECORD, {"format": 1, "entries": local_entries})
    # the library: the old copies at its top, frozen; the live ones in _moonglade\
    library_records(lib)
    write(lib / "account_prefs" / (KEY_NEL + ".json"), {"guide.gallery": "old"})
    write(lib / "logs" / "moonglade.log.2026-10-04", "rotated\n")
    write(lib / "logs" / "moonglade.log", "frozen at the copy\n")
    write(lib / "integrity_report.json", {"format": 1})
    lib_entries = [fingerprint_record(n, lib / n) for n in (
        "achievements.json", "telemetry.json", "schedule.json", "reconcile_stamp.json",
        "jobs.jsonl", "raw_tasks.jsonl", "runs.db", "account_prefs", "logs",
        "integrity_report.json")]
    app = lib / "_moonglade"
    library_records(lib, app)
    write(app / "achievements.json", {"seen": ["a1", "a2"], "skin": "dusk",
                                      "earned_at": {"a1": "2026-09-01", "a2": "2026-10-06"}})
    write(app / "jobs.jsonl", '{"id": "j1"}\n{"id": "j2"}\n{"id": "j3"}\n')
    write(app / "account_prefs" / (KEY_NEL + ".json"), {"guide.gallery": "live"})
    write(app / "logs" / "moonglade.log.2026-10-04", "rotated\n")
    write(app / "logs" / "moonglade.log", "the live log\n")
    write(app / "reports" / "integrity_report.json", {"format": 1, "live": True})
    write(app / migrate.OLD_RECORD, {"format": 1, "entries": lib_entries})
    write(app / migrate.OLD_LOCK, "123")
    write(lib / "catalog.db", b"CATALOG")
    write(lib / "images" / "a_m1.png", b"PICTURE")
    return lib
