"""Issue #33 -- batch identity: PixAI's own output number, recovered from getTaskById
outputs.batch (an ORDERED array of {mediaId, seed, extra}, one per output; its index IS
the <n> in the site's own from-PixAI-<taskId>-<n> download names). Pins:
  * the batch_index / batch_size columns exist on new AND migrated catalogs;
  * the extract resolves each row's OWN index + size from the batch array, and stays
    blank (never guessed) when there is no batch array or the media id is not in it;
  * /api/siblings orders members by batch_index when EVERY member has one -- media_id
    order can swap outputs -- and falls back to media_id order when any member lacks it;
  * deletion honesty: a missing sibling leaves a true GAP -- the survivors keep PixAI's
    original numbers, nothing is ever renumbered.
"""
import sqlite3

import moonglade_backup as core
import moonglade_gallery as G


def _seed(tmp_path, rows):
    from moonglade_gallery import CATALOG_FIELDS, save_catalog
    (tmp_path / "2026-08").mkdir(parents=True, exist_ok=True)
    full = []
    for r in rows:
        name = "2026-08/pic_%s.png" % r["media_id"]
        (tmp_path / name).write_bytes(b"\x00" * 16)
        full.append({f: "" for f in CATALOG_FIELDS} | {
            "filename": name, "created_at": "2026-08-23T01:02:03Z"} | r)
    save_catalog(tmp_path / "catalog.db", full)


def _client(tmp_path):
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    return login_test_client(create_app(tmp_path))


# ---- schema: both columns, new DB and migrated DB ------------------------------------

def test_new_catalog_has_batch_identity_columns(tmp_path):
    assert "batch_index" in G.CATALOG_FIELDS and "batch_size" in G.CATALOG_FIELDS
    _seed(tmp_path, [{"media_id": "1", "task_id": "T1"}])
    con = sqlite3.connect(tmp_path / "catalog.db")
    cols = {r[1] for r in con.execute("PRAGMA table_info(catalog)")}
    con.close()
    assert {"batch_index", "batch_size"} <= cols, sorted(cols)


def test_migration_adds_batch_identity_to_an_old_catalog(tmp_path):
    """A pre-#33 catalog gains both columns on connect (the ALTER TABLE migrations),
    defaulting to '' -- 'not a batch output', same as every other column here."""
    db = tmp_path / "catalog.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE catalog (media_id TEXT PRIMARY KEY, task_id TEXT)")
    con.execute("INSERT INTO catalog VALUES ('m1', 'T1')")
    con.commit()
    con.close()
    rows = G.load_catalog(db)     # _connect runs _MIGRATIONS
    assert rows[0]["batch_index"] == "" and rows[0]["batch_size"] == ""
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(catalog)")}
    con.close()
    assert {"batch_index", "batch_size"} <= cols, sorted(cols)


# ---- the extract: per-row index from outputs.batch, never guessed --------------------

def _batch_task(mids):
    return {
        "parameters": {"prompts": "a moonlit grove", "modelId": "m1"},
        "outputs": {
            "seed": 7,
            "batch": [{"mediaId": m, "seed": 1000 + i, "extra": {}}
                      for i, m in enumerate(mids)],
        },
    }


def test_extract_resolves_each_rows_own_index_and_size():
    mids = ["mA", "mB", "mC", "mD"]
    fm = core.extract_full_meta(_batch_task(mids))
    # task-level defaults stay blank: the index is a per-OUTPUT fact
    assert fm["batch_index"] == "" and fm["batch_size"] == ""
    for i, mid in enumerate(mids):
        row = core._with_batch_position(fm, mid)
        assert row["batch_index"] == str(i), (mid, row["batch_index"])
        assert row["batch_size"] == "4"
    # and _merge_full carries both onto the row (they are _FULL_META_FIELDS members)
    merged = core._merge_full(core._with_batch_position(fm, "mC"), {})
    assert merged["batch_index"] == "2" and merged["batch_size"] == "4"
    # the shared cached dict is never mutated by a row's resolution
    assert fm["batch_index"] == "" and fm["batch_size"] == ""


def test_task_without_a_batch_array_stays_blank():
    """Edits, upscales, videos, imports: no outputs.batch -> both '' -- 'not a batch
    output', NEVER inferred from media_id order."""
    fm = core.extract_full_meta({"parameters": {"prompts": "x"}, "outputs": {"seed": 2}})
    assert fm["_batch"] is None
    row = core._with_batch_position(fm, "m0")
    assert row["batch_index"] == "" and row["batch_size"] == ""
    merged = core._merge_full(row, {})
    assert merged["batch_index"] == "" and merged["batch_size"] == ""


def test_media_id_not_in_the_batch_is_never_guessed():
    fm = core.extract_full_meta(_batch_task(["mA", "mB"]))
    row = core._with_batch_position(fm, "stranger")
    assert row["batch_index"] == "" and row["batch_size"] == ""


# ---- /api/siblings ordering -----------------------------------------------------------

def test_siblings_orders_by_batch_index_when_all_members_have_it(tmp_path):
    # media_id order (901..904) DISAGREES with the site's batch order -- batch wins
    _seed(tmp_path, [
        {"media_id": "901", "task_id": "T1", "batch_index": "1", "batch_size": "4"},
        {"media_id": "902", "task_id": "T1", "batch_index": "3", "batch_size": "4"},
        {"media_id": "903", "task_id": "T1", "batch_index": "0", "batch_size": "4"},
        {"media_id": "904", "task_id": "T1", "batch_index": "2", "batch_size": "4"},
    ])
    cli = _client(tmp_path)
    r = cli.post("/api/siblings", json={"task_ids": ["T1"]})
    assert r.status_code == 200, r.get_data(as_text=True)
    by = r.get_json()["by_task"]
    assert [m["media_id"] for m in by["T1"]] == ["903", "901", "904", "902"]
    assert [m["batch_index"] for m in by["T1"]] == [0, 1, 2, 3]


def test_siblings_falls_back_to_media_id_when_any_member_lacks_an_index(tmp_path):
    _seed(tmp_path, [
        {"media_id": "911", "task_id": "T2", "batch_index": "1", "batch_size": "3"},
        {"media_id": "912", "task_id": "T2"},                       # no index: import/edit
        {"media_id": "913", "task_id": "T2", "batch_index": "0", "batch_size": "3"},
    ])
    cli = _client(tmp_path)
    by = cli.post("/api/siblings", json={"task_ids": ["T2"]}).get_json()["by_task"]
    # today's media_id order, NOT a half-sort; the indexless member reports null
    assert [m["media_id"] for m in by["T2"]] == ["911", "912", "913"]
    assert [m["batch_index"] for m in by["T2"]] == [1, None, 0]


def test_deleted_sibling_leaves_a_true_gap_no_renumber(tmp_path):
    """A 4-batch whose index-1 member is gone from the catalog: the remaining 3 come
    back with PixAI's ORIGINAL numbers (0, 2, 3). The index is the site's permanent
    fact -- a gap is true, and renumbering would break the from-PixAI-<task>-<n>
    correspondence with the owner's real downloads."""
    _seed(tmp_path, [
        {"media_id": "921", "task_id": "T3", "batch_index": "0", "batch_size": "4"},
        {"media_id": "922", "task_id": "T3", "batch_index": "2", "batch_size": "4"},
        {"media_id": "923", "task_id": "T3", "batch_index": "3", "batch_size": "4"},
    ])
    cli = _client(tmp_path)
    by = cli.post("/api/siblings", json={"task_ids": ["T3"]}).get_json()["by_task"]
    assert [m["batch_index"] for m in by["T3"]] == [0, 2, 3]
    assert [m["media_id"] for m in by["T3"]] == ["921", "922", "923"]
