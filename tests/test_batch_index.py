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


# ---- PixAI's own tombstone: a member deleted on their side (2026-09-06) ---------------

_GONE = "2026-09-06T11:22:33.000Z"


def _batch_task_with_deletions(mids, deleted=()):
    """The same shape, with `deletedAt` on the members PixAI has dropped. Read off the
    owner's own tasks: a deleted member KEEPS its place in outputs.batch and gains that one
    key; untouched members carry no such key at all."""
    task = _batch_task(mids)
    for entry in task["outputs"]["batch"]:
        if entry["mediaId"] in deleted:
            entry["deletedAt"] = _GONE
    task["outputs"]["mediaId"] = "GRID-COMBINED"      # the combined preview picture
    return task


def test_a_deleted_member_is_not_one_of_the_tasks_images():
    """The resurrection bug this closes: `_task_image_media` is what a pull, a re-collect
    and a --sync enumerate a task's outputs with. Left as it was, every re-sync would list
    an image PixAI had deleted and download it straight back into the library."""
    task = _batch_task_with_deletions(["mA", "mB", "mC", "mD"], deleted=("mB", "mD"))
    got = [mid for mid, _seed in core._task_image_media(task["outputs"])]
    assert got == ["mA", "mC"], "a deleted member came back as one of the task's images"


def test_a_batch_with_every_member_deleted_yields_nothing():
    """And in particular does NOT fall back to outputs.mediaId, which on a batch task is
    the combined preview picture rather than one of the images."""
    task = _batch_task_with_deletions(["mA", "mB"], deleted=("mA", "mB"))
    assert core._task_image_media(task["outputs"]) == []


def test_survivors_keep_pixais_original_numbers_when_a_sibling_is_deleted():
    """The #33 invariant, now against PixAI's own tombstone rather than a missing catalog
    row: nothing is renumbered and the size does not shrink. The site's
    from-PixAI-<taskId>-<n> download names are the reason -- they never change either."""
    task = _batch_task_with_deletions(["mA", "mB", "mC", "mD"], deleted=("mB",))
    batch = task["outputs"]["batch"]
    assert core.batch_position(batch, "mC") == ("2", "4"), "a survivor was renumbered"
    assert core.batch_position(batch, "mD") == ("3", "4")


def test_a_deleted_member_reports_no_position():
    """It is not one of the task's live outputs any more, so it has no live output number
    to report -- blank, the same answer as 'not a batch output'."""
    task = _batch_task_with_deletions(["mA", "mB"], deleted=("mB",))
    assert core.batch_position(task["outputs"]["batch"], "mB") == ("", "")


def _answers(monkeypatch, task):
    """The live read answers `task`. task_media_index reads the task before it counts, and
    nothing here goes near the network."""
    monkeypatch.setattr(core, "task_detail_gql", lambda session, tid, **kw: task)
    return object()


def test_the_publish_index_is_pixais_raw_slot_not_a_count_of_survivors(monkeypatch):
    """`task_media_index` is what fills `mediaIndex` on the publish mutation, so it has to
    mean the same thing PixAI means: the RAW position in outputs.batch, with a deleted
    member still occupying its slot -- exactly what `batch_position` reports above.

    Counting only the live members shifts every image after a deletion down one. On this
    batch that publishes mB's picture when the owner picked mC's -- the wrong picture, on
    their public profile, silently. Not a recoverable mistake."""
    session = _answers(monkeypatch,
                       _batch_task_with_deletions(["mA", "mB", "mC"], deleted=("mA",)))
    assert core.task_media_index(session, "T1", "mC") == 2, (
        "the publish index was counted over the survivors, not PixAI's own slots")
    assert core.task_media_index(session, "T1", "mB") == 1


def test_publishing_an_image_pixai_has_deleted_is_refused(monkeypatch):
    """A deleted member has no live output number, so there is no honest index to publish it
    at -- and the caller treats None as fatal rather than guessing one. The same answer
    covers an id the batch does not list and the batch's own combined preview picture."""
    session = _answers(monkeypatch,
                       _batch_task_with_deletions(["mA", "mB", "mC"], deleted=("mA",)))
    assert core.task_media_index(session, "T1", "mA") is None
    assert core.task_media_index(session, "T1", "stranger") is None
    assert core.task_media_index(session, "T1", "GRID-COMBINED") is None


def test_a_task_with_no_batch_still_publishes_its_lone_image_at_zero(monkeypatch):
    """Single-image generations, edits and upscales have no batch array at all -- the image
    IS outputs.mediaId, and its index is 0, as it always was."""
    session = _answers(monkeypatch, {"outputs": {"mediaId": "solo", "seed": "1"}})
    assert core.task_media_index(session, "T1", "solo") == 0
    assert core.task_media_index(session, "T1", "other") is None


def test_the_row_of_a_deleted_member_gets_the_deleted_stamp():
    """So a library that already holds the image says out loud that PixAI no longer does.
    --backfill-full-meta walks EXISTING catalog rows task by task, which is the pass that
    reaches a row whose image was deleted from PixAI's website."""
    fm = core.extract_full_meta(
        _batch_task_with_deletions(["mA", "mB"], deleted=("mB",)))
    assert core._with_batch_position(fm, "mB")["cloud_deleted_at"] == _GONE
    assert core._with_batch_position(fm, "mA")["cloud_deleted_at"] == "", (
        "a live sibling was marked as deleted on PixAI")
    merged = core._merge_full(core._with_batch_position(fm, "mB"), {})
    assert merged["cloud_deleted_at"] == _GONE, (
        "the stamp never reaches the catalog row -- it is not carried by _merge_full")
    assert fm.get("cloud_deleted_at", "") == "", (
        "the per-task cached meta was mutated by one row's resolution")
