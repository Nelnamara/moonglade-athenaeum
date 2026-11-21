"""3.22 review F4 (DESIGN_3.22 2.8): collect's --full-meta and the full-meta backfill read the
task through the REST fallback when GraphQL task(id) cannot be read; the per-image delete never
does. Nothing here touches the network: _rest_get and gql_adhoc are stubs."""
import inspect

import pytest

from moonglade import backup as core
from moonglade import cloud_delete
from moonglade import task_reads
from moonglade import full_meta as full_meta_mod

TASK = {"id": "2074596287000121003", "status": "completed", "startedAt": "t", "paidQuota": 3000,
        "outputs": {"mediaIds": ["m2", "m4"], "mediaUrls": ["u2", "u4"], "seed": "123"},
        "parameters": {"prompts": "a cat", "modelId": "1"}}


@pytest.fixture
def refused_graphql(monkeypatch):
    def _gql(session, document, variables=None, retries=None, timeout=120):
        raise core.graphql_error([{"message": "no", "extensions": {"code": "FORBIDDEN"}}])
    monkeypatch.setattr(core, "gql_adhoc", _gql)
    monkeypatch.setattr(core, "_rest_get", lambda s, path, params=None, **k: TASK)


def test_the_full_meta_read_takes_the_rest_record_when_graphql_is_refused(refused_graphql):
    task = full_meta_mod._task_for_full_meta(object(), TASK["id"])
    assert task and task["_rest_fallback"] is True
    fm = full_meta_mod.extract_full_meta(task)
    assert fm["prompt_full"] == "a cat" and fm["model_id"] == "1"
    assert fm["seed"] == ""                                 # per-image seeds stay unknown


def test_a_fallback_record_never_renumbers_the_survivors(refused_graphql):
    """The REST batch lists only the LIVE members, so m4 would read as index 1 of 2 though
    PixAI numbers it 3 of 4. A degraded record parks no batch, so no position is written."""
    fm = full_meta_mod.extract_full_meta(full_meta_mod._task_for_full_meta(object(), TASK["id"]))
    assert fm["_batch"] is None
    row = full_meta_mod._with_batch_position(fm, "m4")
    assert not row.get("batch_index") and not row.get("batch_size")


def test_the_three_full_meta_readers_use_the_fallback_read():
    for fn in (core.run_backfill_full_meta, core.run_download):
        assert "_task_for_full_meta(session, tid)" in inspect.getsource(fn), fn.__name__
    assert inspect.getsource(core.run_download).count("_task_for_full_meta(session, tid)") == 2


def test_deletes_and_the_plain_read_never_take_the_fallback(refused_graphql):
    assert task_reads.task_detail_gql(object(), TASK["id"]) is None
    assert cloud_delete.plan_image_delete(object(), TASK["id"], "m2").plan == "refuse"
    src = inspect.getsource(cloud_delete)
    assert "rest_fallback=True" not in src
