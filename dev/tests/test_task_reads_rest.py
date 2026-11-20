"""3.22 S3-poll (DESIGN_3.22 2.8): the status read on GET /v2/task/{id}, the failure reason from
GraphQL on a terminal failure, and the rich read's REST fallback -- including the delete routing
off REST's live media set.

The REST answers below follow probes/PROBE_2026-11-19_322.md P1's recorded shapes (the five
tasks' REST `outputs` keys, mediaIds that exclude deleted members and never the composite, one
seed per task, paidQuota equal to paidCredit, no reason on a failed or cancelled task). The ids
are stand-ins. Nothing here touches the network: _rest_get and gql_adhoc are recorded stubs.
"""
import pytest

from moonglade import backup as core
from moonglade import cloud_delete
from moonglade import task_reads

BATCH = {"id": "2074596287000121003", "status": "completed", "taskKind": "t2i",
         "startedAt": "2026-11-18T10:00:01Z", "endAt": "2026-11-18T10:00:20Z",
         "paidQuota": 3000, "priority": 500, "batchSize": 4,
         "outputs": {"mediaIds": ["m1", "m2", "m3", "m4"], "mediaUrls": ["u1", "u2", "u3", "u4"],
                     "seed": "123"},
         "parameters": {"prompts": "a cat", "modelId": "1"}}
DELETED = {"id": "2051316667414496321", "status": "completed", "startedAt": "t", "paidQuota": 0,
           "outputs": {"mediaIds": ["live1", "live2"], "mediaUrls": ["a", "b"], "seed": "9"},
           "parameters": {"prompts": "x"}}
LONE = {"id": "2071336441880993634", "status": "completed", "startedAt": "t", "paidQuota": 3000,
        "outputs": {"mediaIds": ["only"], "mediaUrls": ["a"]}, "parameters": {"chat": {}}}
CANCELLED = {"id": "2073848782784132782", "status": "cancelled", "startedAt": None,
             "paidQuota": 0, "outputs": {"mediaIds": [], "mediaUrls": []}}
FAILED = {"id": "2071275005076105420", "status": "failed", "startedAt": "t", "paidQuota": 65100,
          "outputs": {"mediaIds": [], "mediaUrls": []}}


@pytest.fixture
def pixai(monkeypatch):
    """REST answers by task id; GraphQL answers by document (None -> a refusal)."""
    state = {"rest": {}, "gql_status": {}, "gql_detail_fails": True, "calls": []}

    def _rest_get(session, path, params=None, timeout=30):
        state["calls"].append(("GET", path, params))
        tid = path.rsplit("/", 1)[-1]
        if tid not in state["rest"]:
            raise core.PixAIRestError("REST GET {} -> 404".format(path), status=404,
                                      body={"code": "NOT_FOUND"})
        return state["rest"][tid]

    def _gql(session, document, variables=None, retries=None, timeout=120):
        state["calls"].append(("GQL", document.split("(")[0], variables))
        if document is task_reads._TASK_DETAIL_DOC:
            raise core.graphql_error([{"message": "no", "extensions": {"code": "FORBIDDEN"}}])
        return {"task": state["gql_status"].get(variables["id"], {})}
    monkeypatch.setattr(core, "_rest_get", _rest_get)
    monkeypatch.setattr(core, "gql_adhoc", _gql)
    return state


def test_the_status_read_is_rest_and_maps_paid_quota(pixai):
    pixai["rest"][BATCH["id"]] = BATCH
    st = task_reads.generation_status(object(), BATCH["id"])
    assert st == {"status": "completed", "phase": "done", "paid_credit": 3000, "started": True,
                  "reason": ""}
    assert [c[0] for c in pixai["calls"]] == ["GET"]          # no GraphQL for a success
    assert pixai["calls"][0][1] == "/task/" + BATCH["id"]


def test_a_cancelled_task_reads_its_reason_from_graphql(pixai):
    pixai["rest"][CANCELLED["id"]] = CANCELLED
    pixai["gql_status"][CANCELLED["id"]] = {"status": "cancelled",
                                            "outputs": {"reason": "waiting timeout"}}
    st = task_reads.generation_status(object(), CANCELLED["id"])
    assert st["phase"] == "failed" and st["reason"] == "waiting timeout"
    assert st["started"] is False


def test_a_rest_reason_is_read_first_and_a_failed_graphql_read_is_no_reason(pixai, monkeypatch):
    pixai["rest"][FAILED["id"]] = dict(FAILED, taskStatusMsgI18n={"en": "Provider refused"})
    assert task_reads.generation_status(object(), FAILED["id"])["reason"] == "Provider refused"
    assert [c[0] for c in pixai["calls"]] == ["GET"]
    pixai["rest"][FAILED["id"]] = FAILED
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: (_ for _ in ()).throw(
        core.PixAIError("down")))
    st = task_reads.generation_status(object(), FAILED["id"])
    assert st["phase"] == "failed" and st["reason"] == "" and st["paid_credit"] == 65100


def test_the_poll_reads_rest_until_done(pixai, monkeypatch):
    monkeypatch.setattr(task_reads.time, "sleep", lambda s: None)
    answers = [dict(BATCH, status="waiting", startedAt=None), dict(BATCH, status="running"),
               BATCH]
    monkeypatch.setattr(core, "_rest_get", lambda s, path, params=None, **k: answers.pop(0))
    assert task_reads._poll_task_status(object(), BATCH["id"], 30) == 3000


def test_the_poll_says_pixais_reason_on_a_failure(pixai, monkeypatch):
    pixai["rest"][CANCELLED["id"]] = CANCELLED
    pixai["gql_status"][CANCELLED["id"]] = {"outputs": {"reason": "waiting timeout"}}
    with pytest.raises(core.PixAIError, match="waiting timeout"):
        task_reads._poll_task_status(object(), CANCELLED["id"], 30)


@pytest.mark.parametrize("bad", ["", "../task/1", "1/media/2", "a b", "x" * 65])
def test_an_id_that_could_leave_its_path_is_never_read(pixai, bad):
    with pytest.raises(core.PixAIError):
        task_reads.generation_status(object(), bad)
    assert pixai["calls"] == []


# --- the rich read's REST fallback -------------------------------------------------------------

def test_the_rich_read_falls_back_to_rest_with_parameters(pixai):
    pixai["rest"][BATCH["id"]] = BATCH
    t = task_reads.task_detail_gql(object(), BATCH["id"])
    assert t["_rest_fallback"] is True and t["parameters"] == BATCH["parameters"]
    assert t["outputs"] == {"batch": [{"mediaId": m} for m in ("m1", "m2", "m3", "m4")]}
    assert t["paidCredit"] == 3000
    rest_call = [c for c in pixai["calls"] if c[0] == "GET"][0]
    assert rest_call[2] == {"with_parameters": "true"}


def test_the_fallback_is_none_when_rest_fails_too(pixai):
    assert task_reads.task_detail_gql(object(), "404404") is None


def test_delete_routing_from_rests_live_set(pixai):
    """P1's batch with two deleted members: REST lists the two live ones. A live member routes
    per image; a deleted one (not in the set) is refused; a lone live image is the whole-task
    delete -- the set the site routes on."""
    pixai["rest"][DELETED["id"]] = DELETED
    assert cloud_delete.plan_image_delete(object(), DELETED["id"], "live1").plan == "per-image"
    gone = cloud_delete.plan_image_delete(object(), DELETED["id"], "deleted1")
    assert gone.plan == "refuse"
    pixai["rest"][LONE["id"]] = LONE
    assert cloud_delete.plan_image_delete(object(), LONE["id"], "only").plan == "whole-task"
