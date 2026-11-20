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


# --- 3.22 review F1: the status read keeps gql_adhoc's retries, and the poll outlives a bad read --

class _Clock(object):
    """task_reads' `time`, faked: sleep moves the clock, so a poll's deadline is reached in no
    real time."""

    def __init__(self):
        self.now, self.slept = 1000.0, []

    def time(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def _flaky_rest(answers, calls):
    """A _rest_get that plays `answers` in order: an exception is raised, a dict answered."""
    def _get(session, path, params=None, **k):
        calls.append(path)
        a = answers.pop(0) if answers else answers_end[0]
        if isinstance(a, Exception):
            raise a
        return a
    answers_end = [answers[-1]] if answers else [None]
    return _get


def _bad_gateway():
    return core.PixAIRestError("REST GET /task/x -> 502: bad gateway", status=502, body=None)


def test_the_status_read_retries_a_passing_failure(monkeypatch):
    import requests
    clock = _Clock()
    monkeypatch.setattr(task_reads, "time", clock)
    calls = []
    monkeypatch.setattr(core, "_rest_get", _flaky_rest(
        [_bad_gateway(), requests.ReadTimeout("read timed out"), BATCH], calls))
    st = task_reads.generation_status(object(), BATCH["id"])
    assert st["phase"] == "done" and st["paid_credit"] == 3000
    assert len(calls) == 3 and len(clock.slept) == 2


def test_the_status_read_does_not_retry_a_refusal(pixai, monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(task_reads, "time", clock)
    with pytest.raises(core.PixAIRestError):
        task_reads.generation_status(object(), "404404")          # the fixture's 404
    assert len(pixai["calls"]) == 1 and clock.slept == []


def test_the_poll_keeps_polling_past_a_read_that_failed(monkeypatch):
    """A 502 on every attempt of one read (its retries spent) does not end the poll: the next
    read finds the task done, and the poll answers its charge. Only GETs were made."""
    clock = _Clock()
    monkeypatch.setattr(task_reads, "time", clock)
    calls = []
    monkeypatch.setattr(core, "_rest_get", _flaky_rest(
        [_bad_gateway() for _ in range(8)] + [BATCH], calls))
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: pytest.fail("a POST was sent"))
    assert task_reads._poll_task_status(object(), BATCH["id"], 300) == 3000
    assert len(calls) == 9


def test_a_poll_that_never_reads_says_the_task_may_still_be_running(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(task_reads, "time", clock)
    calls = []
    monkeypatch.setattr(core, "_rest_get", _flaky_rest([_bad_gateway()], calls))
    with pytest.raises(core.PixAIError) as e:
        task_reads._poll_task_status(object(), BATCH["id"], 60)
    words = str(e.value)
    assert "MAY STILL BE RUNNING" in words and BATCH["id"] in words
    assert "do not send it again" in words
    assert len(calls) > 1


@pytest.mark.parametrize("bad", ["", "../task/1", "1/media/2", "a b", "x" * 65])
def test_an_id_that_could_leave_its_path_is_never_read(pixai, bad):
    with pytest.raises(core.PixAIError):
        task_reads.generation_status(object(), bad)
    assert pixai["calls"] == []


# --- the rich read's REST fallback: opt-in, degraded, never routes a delete -------------------

def test_the_fallback_is_off_unless_a_caller_asks(pixai):
    """Security review of 67310d6b: every existing caller of task_detail_gql keeps None when
    GraphQL cannot be read -- the deletes, the catalog writers, the collectors -- because the
    REST record lacks the tombstones, the video outputs and the seeds they read."""
    pixai["rest"][BATCH["id"]] = BATCH
    assert task_reads.task_detail_gql(object(), BATCH["id"]) is None
    assert not [c for c in pixai["calls"] if c[0] == "GET"], "the fallback was read unasked"


def test_the_rich_read_falls_back_to_rest_with_parameters_when_asked(pixai):
    pixai["rest"][BATCH["id"]] = BATCH
    t = task_reads.task_detail_gql(object(), BATCH["id"], rest_fallback=True)
    assert t["_rest_fallback"] is True and t["parameters"] == BATCH["parameters"]
    assert t["outputs"] == {"batch": [{"mediaId": m} for m in ("m1", "m2", "m3", "m4")]}
    assert t["paidCredit"] == 3000
    rest_call = [c for c in pixai["calls"] if c[0] == "GET"][0]
    assert rest_call[2] == {"with_parameters": "true"}


def test_the_fallback_is_none_when_rest_fails_too(pixai):
    assert task_reads.task_detail_gql(object(), "404404", rest_fallback=True) is None


def _fallback_of(task, monkeypatch):
    """The fallback record the REST read builds for `task`."""
    monkeypatch.setattr(core, "_rest_get", lambda s, path, params=None, **k: task)
    return task_reads._rest_detail_fallback(object(), task["id"])


@pytest.mark.parametrize("task, target", [
    (LONE, "only"),                                         # looks like a lone image
    (DELETED, "live1"),                                     # a batch member
    (dict(LONE, outputs={"mediaIds": ["poster"], "videoMediaId": "clip"}), "poster"),  # video
], ids=["lone-image", "batch-member", "video-shaped"])
def test_the_router_refuses_a_fallback_record(task, target, monkeypatch):
    rec = _fallback_of(task, monkeypatch)
    assert rec["_rest_fallback"] is True
    route = cloud_delete.route_image_delete(rec, target)
    assert route.plan == "refuse" and route.reason == cloud_delete.REST_FALLBACK_REFUSAL


@pytest.mark.parametrize("confirmed", ["per-image", "whole-task"])
def test_plan_and_confirm_send_nothing_when_the_read_degrades(monkeypatch, confirmed):
    """plan_image_delete and the confirm-time re-read inside delete_image_routed: a read that
    degraded to the REST fallback sends no delete of either kind."""
    rec = _fallback_of(DELETED, monkeypatch)
    monkeypatch.setattr(task_reads, "task_detail_gql", lambda s, t, **k: rec)
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)
    fired = []
    monkeypatch.setattr(cloud_delete, "delete_task", lambda *a: fired.append("task"))
    monkeypatch.setattr(cloud_delete, "delete_batch_media_gql", lambda *a: fired.append("media"))
    if hasattr(cloud_delete, "delete_task_media"):
        monkeypatch.setattr(cloud_delete, "delete_task_media", lambda *a: fired.append("media"))
    assert cloud_delete.plan_image_delete(object(), DELETED["id"], "live1").plan == "refuse"
    plan = cloud_delete.delete_image_routed(object(), DELETED["id"], "live1",
                                            confirmed_plan=confirmed)
    assert plan.plan == "refuse" and fired == []