"""--backfill-lineage: an errored fetch must NOT be stamped lineage_checked.

Regression for the 2026-08-07 branch-review high finding: _parallel_map yields
(item, None) after a worker exception (it calls on_error and still yields), and the
apply loop used to fold that None into ("", "") -- indistinguishable from a fetch
that CONFIRMED an original -- and persist lineage_checked='1'. Because done_tasks
skips any row carrying that marker, one transient network error permanently
excluded the task from every future run with no way back short of manual SQL.

Fully mocked; no network, no disk beyond tmp."""
import types

import pytest

from moonglade_gallery import CATALOG_FIELDS, load_catalog, save_catalog

import moonglade_backup as core


def _args(tmp_path):
    return types.SimpleNamespace(out=str(tmp_path), token=None, workers=1,
                                 delay=0.0, progress=None)


def _seed(tmp_path, task_ids):
    db = tmp_path / "catalog.db"          # save_catalog creates the db itself
    rows = []
    for i, tid in enumerate(task_ids):
        row = {f: "" for f in CATALOG_FIELDS}
        row.update({"media_id": "m%d" % i, "task_id": tid, "filename": "f%d.png" % i})
        rows.append(row)
    save_catalog(db, rows)
    return db


def _run(monkeypatch, tmp_path, detail_fn):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda session, tid: detail_fn(tid))
    core.run_backfill_lineage(_args(tmp_path))
    return {r["task_id"]: r for r in load_catalog(tmp_path / "catalog.db")}


def test_errored_task_is_not_stamped_checked_and_retries_next_run(monkeypatch, tmp_path):
    _seed(tmp_path, ["t_ok", "t_boom"])

    def detail(tid):
        if tid == "t_boom":
            raise core.PixAIError("rate limited")
        return {"task": {"parameters": {}}}          # a real fetch, no source: original

    by_task = _run(monkeypatch, tmp_path, detail)
    # The successful no-source fetch IS a confirmed original -> stamped.
    assert by_task["t_ok"]["lineage_checked"] == "1"
    # The errored one must stay unstamped -- eligible for the next run.
    assert not by_task["t_boom"].get("lineage_checked")

    # Second run: only the errored task is refetched, and on success it files normally.
    fetched = []

    def detail2(tid):
        fetched.append(tid)
        return {"task": {"parameters": {"image": {"mediaId": "src9"}},
                         "taskType": "edit"}}

    monkeypatch.setattr(core, "task_detail_gql", lambda session, tid: detail2(tid))
    core.run_backfill_lineage(_args(tmp_path))
    assert fetched == ["t_boom"]                      # t_ok was NOT refetched
    by_task = {r["task_id"]: r for r in load_catalog(tmp_path / "catalog.db")}
    assert by_task["t_boom"]["lineage_checked"] == "1"


def test_confirmed_original_is_still_stamped_and_never_refetched(monkeypatch, tmp_path):
    """The fix must not regress the marker's whole point: a REAL fetch that finds no
    source is a confirmed original, stamped once, skipped forever after."""
    _seed(tmp_path, ["t_orig"])
    calls = []

    def detail(tid):
        calls.append(tid)
        return {"task": {"parameters": {}}}

    by_task = _run(monkeypatch, tmp_path, detail)
    assert by_task["t_orig"]["lineage_checked"] == "1"
    core.run_backfill_lineage(_args(tmp_path))        # second run
    assert calls == ["t_orig"]                        # fetched exactly once, ever
