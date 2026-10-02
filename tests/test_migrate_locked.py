"""A catalog that is LOCKED when the gallery first migrates it (a --sync holding the write lock
past sqlite's busy timeout) must not be memoized as migrated: before, the new tables were never
created for the life of the process and every collection read failed with "no such table"
(red team 2026-10-01). Now the run stops at the first locked statement, is not memoized, and
the next access completes it."""
import sqlite3

import moonglade_gallery as g


def test_a_locked_catalog_is_migrated_on_the_next_access_not_never(tmp_path):
    db = tmp_path / "catalog.db"
    g.save_catalog(db, [])
    key = g._catalog_key(db)
    con = sqlite3.connect(str(db))
    con.execute("DROP TABLE IF EXISTS smart_collections")
    con.commit()
    con.close()
    g._MIGRATED.discard(key)

    holder = sqlite3.connect(str(db), timeout=0)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        g.migrate(db)
        assert key not in g._MIGRATED, "a locked run was memoized as done"
    finally:
        holder.rollback()
        holder.close()

    g.migrate(db)
    assert key in g._MIGRATED
    con = sqlite3.connect(str(db))
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    con.close()
    assert "smart_collections" in names
