"""A catalog that is LOCKED when the gallery first migrates it (a --sync holding the write lock
past sqlite's busy timeout) must not be memoized as migrated: before, the new tables were never
created for the life of the process and every collection read failed with "no such table"
(red team 2026-10-01). Now the run stops at the first locked statement, is not memoized, and
a later access completes it.

A locked attempt also starts a short BACK-OFF (#58): until it runs out, every catalog access
skips the migration instead of waiting out sqlite's busy timeout again -- and so do the request
threads that were queued behind the locked attempt, which used to wait their own timeout one
after another."""
import sqlite3
import threading
import time

from moonglade import gallery as g


def _fresh_unmigrated(tmp_path):
    """A catalog missing one migrated table, and not memoized as migrated."""
    db = tmp_path / "catalog.db"
    g.save_catalog(db, [])
    key = g._catalog_key(db)
    con = sqlite3.connect(str(db))
    con.execute("DROP TABLE IF EXISTS smart_collections")
    con.commit()
    con.close()
    g._MIGRATED.discard(key)
    g._MIGRATE_RETRY_AT.pop(key, None)
    return db, key


def _tables(db):
    con = sqlite3.connect(str(db))
    try:
        return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    finally:
        con.close()


class _Holder:
    """Another process's write lock on the catalog, the way a running --sync holds it."""
    def __init__(self, db):
        self.con = sqlite3.connect(str(db), timeout=0)
        self.con.execute("BEGIN EXCLUSIVE")

    def release(self):
        self.con.rollback()
        self.con.close()


def _count_connects(monkeypatch, db):
    """Count every connection opened on this catalog from here on."""
    real = g.sqlite3.connect
    seen = []

    def counting(path, *a, **k):
        if str(path) == str(db):
            seen.append(path)
        return real(path, *a, **k)

    monkeypatch.setattr(g.sqlite3, "connect", counting)
    return seen


def test_a_locked_catalog_is_migrated_on_a_later_access_not_never(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MIGRATE_BUSY_TIMEOUT_S", 0.2)
    db, key = _fresh_unmigrated(tmp_path)
    holder = _Holder(db)
    try:
        g.migrate(db)
        assert key not in g._MIGRATED, "a locked run was memoized as done"
        assert key in g._MIGRATE_RETRY_AT, "a locked run started no back-off"
    finally:
        holder.release()

    g._MIGRATE_RETRY_AT[key] = 0.0          # the back-off has run out
    g.migrate(db)
    assert key in g._MIGRATED
    assert "smart_collections" in _tables(db)


def test_inside_the_back_off_a_second_access_opens_no_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MIGRATE_BUSY_TIMEOUT_S", 0.2)
    db, key = _fresh_unmigrated(tmp_path)
    holder = _Holder(db)
    try:
        g.migrate(db)
        seen = _count_connects(monkeypatch, db)
        g.migrate(db)
        g.migrate(db)
        assert seen == [], "an access inside the back-off retried the migration"
        assert key not in g._MIGRATED
    finally:
        holder.release()


def test_after_the_back_off_it_retries_completes_and_forgets_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MIGRATE_BUSY_TIMEOUT_S", 0.2)
    db, key = _fresh_unmigrated(tmp_path)
    holder = _Holder(db)
    try:
        g.migrate(db)
    finally:
        holder.release()
    g._MIGRATE_RETRY_AT[key] = 0.0
    seen = _count_connects(monkeypatch, db)
    g.migrate(db)
    assert len(seen) == 1
    assert key in g._MIGRATED
    assert key not in g._MIGRATE_RETRY_AT
    assert "smart_collections" in _tables(db)


def test_force_ignores_the_back_off(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MIGRATE_BUSY_TIMEOUT_S", 0.2)
    db, key = _fresh_unmigrated(tmp_path)
    holder = _Holder(db)
    try:
        g.migrate(db)
    finally:
        holder.release()
    assert key in g._MIGRATE_RETRY_AT          # still inside the window...
    g.migrate(db, force=True)                  # ...and force runs it anyway
    assert key in g._MIGRATED
    assert key not in g._MIGRATE_RETRY_AT
    assert "smart_collections" in _tables(db)


def _one_locked_attempt_s(tmp_path):
    """How long ONE locked attempt really waits here. sqlite's busy handler sleeps in
    whole steps on some builds (a second at a time on this Windows Python), so a 0.3 s
    timeout can wait close to a second: the bound below is measured, not assumed."""
    db, _ = _fresh_unmigrated(tmp_path / "calibrate")
    holder = _Holder(db)
    try:
        start = time.monotonic()
        g.migrate(db)
        return time.monotonic() - start
    finally:
        holder.release()


def test_threads_queued_behind_a_locked_attempt_do_not_each_wait_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "MIGRATE_BUSY_TIMEOUT_S", 0.3)
    (tmp_path / "calibrate").mkdir()
    one = _one_locked_attempt_s(tmp_path)
    db, key = _fresh_unmigrated(tmp_path)
    holder = _Holder(db)
    seen = _count_connects(monkeypatch, db)
    try:
        start = time.monotonic()
        threads = [threading.Thread(target=g.migrate, args=(db,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - start
    finally:
        holder.release()
    assert len(seen) == 1, f"{len(seen)} connections: queued threads retried the migration"
    assert elapsed < 2 * one, f"four threads took {elapsed:.2f}s; one locked attempt takes {one:.2f}s"
    assert key not in g._MIGRATED


def test_a_clean_migration_leaves_no_back_off_entry(tmp_path):
    db, key = _fresh_unmigrated(tmp_path)
    g.migrate(db)
    assert key in g._MIGRATED
    assert key not in g._MIGRATE_RETRY_AT
