"""Lineage for Tsubaki context images (SCOPE_2026-09-26 E3, probe finding EDIT-6).

A Tsubaki.3 / Flash picture made from a reference carries its source ONLY in
`parameters.contextImages` -- no top-level mediaId, no chat block. The owner's seven
2026-09-23 runs have exactly that shape, and source_media_of_task used to file every one of
them as an ORIGINAL, so Image Details' LINEAGE panel stayed empty. --backfill-lineage then
stamped `lineage_checked` on them -- the "confirmed original" marker every later run skips --
so the fixed reader alone could never reach them. A one-time repair in _MIGRATIONS clears
that stamp on MMDIT26B rows with no source.

The shapes below are the owner's runs with the prompt text redacted to a placeholder (the
ids, sizes and flags are the wire's own). Fully offline."""
import sqlite3
import types

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, load_catalog, migrate, save_catalog

T3 = "2024383379556065549"          # Tsubaki.3
FLASH = "2050048243034896798"       # Tsubaki.3 Flash
SRC_A = "769013897379130822"
SRC_B = "769014882321308565"


def _context_run(*context_ids, model=T3):
    """One of the owner's context-image runs, prompts redacted."""
    return {
        "id": "2059314466822193797",
        "outputs": {"extra": None, "mediaId": "769015153457132526", "seed": 1,
                    "width": 1632, "height": 912},
        "parameters": {
            "priority": 1000, "width": 1632, "height": 912,
            "prompts": "<prompt>", "inferenceProfile": "pro",
            "qualityTag": {"prefix": "", "suffix": ""},
            "promptHelper": {"enable": True, "creativity": "medium",
                             "forcePromptHelperDetectionSide": "server"},
            "controlNets": [], "contextImages": list(context_ids),
            "isPrivate": False, "enablePreview": False, "hidePrompts": False,
            "modelId": model, "extra": {"naturalPrompts": "<natural prompt>"},
        },
    }


def test_a_context_image_run_names_its_source():
    assert core.source_media_of_task(_context_run(SRC_A)) == (SRC_A, "derived")


def test_with_two_context_images_the_first_is_the_source():
    assert core.source_media_of_task(_context_run(SRC_A, SRC_B)) == (SRC_A, "derived")


def test_the_existing_shapes_still_win_over_context_images():
    """contextImages is read AFTER every existing check: a shape that already names its
    source keeps its own kind."""
    t = _context_run(SRC_A)
    t["parameters"]["mediaId"] = "999"
    t["parameters"]["upscale"] = 2
    assert core.source_media_of_task(t) == ("999", "upscale")


def test_empty_or_blank_context_images_are_still_an_original():
    for ctx in ([], [""], None):
        t = _context_run()
        t["parameters"]["contextImages"] = ctx
        assert core.source_media_of_task(t) == (None, None)


def test_create_time_collection_files_the_lineage():
    fm = core.extract_full_meta(_context_run(SRC_B, SRC_A))
    assert fm["source_media_id"] == SRC_B and fm["derive_kind"] == "derived"


# --------------------------------------------------------------- the repair

def _row(media_id, task_id, model_id, **kw):
    r = {f: "" for f in CATALOG_FIELDS}
    r.update(media_id=media_id, task_id=task_id, model_id=model_id,
             filename=media_id + ".png", **kw)
    return r


def _pre_release_catalog(tmp_path, rows):
    """A catalog as the owner's install holds it BEFORE this release: rows already stamped
    by an earlier --backfill-lineage, and no record of the repair having run."""
    db = tmp_path / "catalog.db"
    save_catalog(db, rows)
    con = sqlite3.connect(str(db))
    con.execute("DROP TABLE IF EXISTS catalog_repairs")
    con.commit()
    con.close()
    return db


def _by_media(db):
    return {r["media_id"]: r for r in load_catalog(db)}


def test_the_repair_unstamps_sourceless_tsubaki3_rows_once(tmp_path):
    db = _pre_release_catalog(tmp_path, [
        _row("m1", "t1", T3, lineage_checked="1"),                  # stamped, no source
        _row("m2", "t2", FLASH, lineage_checked="1"),               # Flash too
        _row("m3", "t3", T3, lineage_checked="1", source_media_id="s", derive_kind="edit"),
        _row("m4", "t4", "1983308862240288769", lineage_checked="1"),   # Tsubaki.2: not ours
    ])
    migrate(db, force=True)                    # the first open under the new release
    rows = _by_media(db)
    assert rows["m1"]["lineage_checked"] == "" and rows["m2"]["lineage_checked"] == ""
    assert rows["m3"]["lineage_checked"] == "1"          # already has a source: untouched
    assert rows["m4"]["lineage_checked"] == "1"          # another architecture: untouched

    # ONCE: a later process start must not clear a stamp the fixed backfill wrote since.
    con = sqlite3.connect(str(db))
    con.execute("UPDATE catalog SET lineage_checked = '1' WHERE media_id = 'm1'")
    con.commit()
    con.close()
    migrate(db, force=True)
    assert _by_media(db)["m1"]["lineage_checked"] == "1"


def test_a_fresh_catalog_records_the_repair_and_never_runs_it_on_later_rows(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row("m1", "t1", T3)])
    save_catalog(db, [_row("m1", "t1", T3, lineage_checked="1")])
    migrate(db, force=True)
    assert _by_media(db)["m1"]["lineage_checked"] == "1"


def test_the_backfill_rereads_the_owners_runs_after_the_repair(monkeypatch, tmp_path):
    """End to end on the owner's shapes: the stamped context run is re-read and gains its
    source; the stamped plain Tsubaki.3 original is re-read once, re-stamped, and left alone
    by every run after."""
    db = _pre_release_catalog(tmp_path, [
        _row("m_ctx", "t_ctx", T3, lineage_checked="1"),
        _row("m_plain", "t_plain", T3, lineage_checked="1"),
    ])
    migrate(db, force=True)

    fetched = []

    def detail(session, tid, **k):
        fetched.append(tid)
        if tid == "t_ctx":
            return _context_run(SRC_A)
        t = _context_run()
        t["parameters"].pop("contextImages")
        return t

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", detail)
    args = types.SimpleNamespace(out=str(tmp_path), token=None, workers=1, delay=0.0,
                                 progress=None)
    core.run_backfill_lineage(args)
    rows = _by_media(db)
    assert sorted(fetched) == ["t_ctx", "t_plain"]
    assert rows["m_ctx"]["source_media_id"] == SRC_A
    assert rows["m_ctx"]["derive_kind"] == "derived"
    assert rows["m_plain"]["source_media_id"] == ""
    assert rows["m_plain"]["lineage_checked"] == "1"

    # The next process start and the next backfill fetch nothing again.
    migrate(db, force=True)
    del fetched[:]
    core.run_backfill_lineage(args)
    assert fetched == []


def _markers(db):
    con = sqlite3.connect(str(db))
    try:
        return [r[0] for r in con.execute("SELECT name FROM catalog_repairs")]
    finally:
        con.close()


def test_a_repair_that_failed_is_not_marked_done_and_runs_next_time(tmp_path, monkeypatch):
    """migrate() swallows every OperationalError, so a repair UPDATE that hit a locked file
    must not be followed by its marker -- the marker is conditional on the repair's own
    postcondition. The next process then runs it."""
    import moonglade_gallery as g
    db = _pre_release_catalog(tmp_path, [_row("m1", "t1", T3, lineage_checked="1")])
    real_connect = g.sqlite3.connect

    class _LockedOnce:
        """A connection whose repair UPDATE fails the way a busy D: catalog does."""
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *a):
            if sql.startswith("UPDATE catalog SET lineage_checked"):
                raise sqlite3.OperationalError("database is locked")
            return self._con.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._con, name)

    monkeypatch.setattr(g.sqlite3, "connect", lambda *a, **k: _LockedOnce(real_connect(*a, **k)))
    migrate(db, force=True)
    monkeypatch.setattr(g.sqlite3, "connect", real_connect)
    assert _markers(db) == []                               # not recorded as done...
    assert _by_media(db)["m1"]["lineage_checked"] == "1"    # ...because it did not run

    migrate(db, force=True)                                 # the next process start
    assert _markers(db) == ["lineage-context-images"]
    assert _by_media(db)["m1"]["lineage_checked"] == ""
