"""3.22 S3-delete (DESIGN_3.22 2.9): the per-image delete rides PixAI's REST route,
POST /v2/task/{id}/media/{mediaId}/delete, through rest_post on the API key.

The success shape is an ASSUMPTION (the contract strips the route's output), and it must fail
safe: only {"success": true} is a delete; anything else is "not deleted" (T-F13). READ_ONLY and
both ids are checked before anything is sent (mutations 9, 17). Nothing here touches the
network: a recording session stands in under the real PixAIClient.rest_post.
"""
import ast
import inspect
import json
import textwrap

import pytest
import requests

from moonglade import backup as core
from moonglade import cloud_delete
from tests.conftest import _REAL_REST_POST


class _Answer:
    def __init__(self, status=200, body=None, not_json=False):
        self.status_code, self._body, self._not_json = status, body, not_json
        self.text, self.headers = json.dumps(body) if body is not None else "", {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        if self._not_json:
            raise requests.exceptions.JSONDecodeError("x", "y", 0)
        return self._body


class _Session:
    def __init__(self, answer=None, raises=None):
        self.posts, self._a, self._raises, self.headers = [], answer, raises, {}

    def post(self, url, **kw):
        self.posts.append((url, kw))
        if self._raises is not None:
            raise self._raises
        return self._a


@pytest.fixture(autouse=True)
def _real_rest_post(monkeypatch):
    monkeypatch.setattr(core, "_rest_post", _REAL_REST_POST)
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)


def test_one_post_to_the_media_route_with_an_empty_body():
    s = _Session(_Answer(200, {"success": True}))
    assert cloud_delete.delete_task_media(s, "2051316667414496321", "live1") is True
    (url, kw), = s.posts
    assert url == core.REST_API_BASE + "/task/2051316667414496321/media/live1/delete"
    assert kw["json"] == {} and kw["allow_redirects"] is False


@pytest.mark.parametrize("answer", [
    _Answer(200, {}), _Answer(200, {"success": False}), _Answer(200, {"success": "true"}),
    _Answer(200, {"ok": True}), _Answer(200, None, not_json=True), _Answer(204, None, not_json=True),
    _Answer(403, {"code": "FORBIDDEN"}), _Answer(500, {"code": "X"}), _Answer(307, {"success": True}),
])
def test_anything_but_success_true_reads_not_deleted(answer):
    s = _Session(answer)
    with pytest.raises(core.PixAIError):
        cloud_delete.delete_task_media(s, "T1", "M1")
    assert len(s.posts) == 1


@pytest.mark.parametrize("exc", [requests.ReadTimeout("slow"), requests.ConnectionError("gone")])
def test_a_lost_answer_reads_not_deleted_after_one_post(exc):
    s = _Session(raises=exc)
    with pytest.raises(core.PixAIError, match="not deleted"):
        cloud_delete.delete_task_media(s, "T1", "M1")
    assert len(s.posts) == 1


@pytest.mark.parametrize("tid, mid", [("", "M1"), ("T1", ""), ("T1", "../x"), ("T/1", "M1"),
                                      ("T1", "M1/delete"), ("T 1", "M1"), ("T1", "M" * 65)])
def test_an_id_that_could_leave_its_segment_is_refused_unsent(tid, mid):
    s = _Session(_Answer(200, {"success": True}))
    with pytest.raises(core.PixAIError, match="Nothing was sent"):
        cloud_delete.delete_task_media(s, tid, mid)
    assert s.posts == []


def test_read_only_refuses_before_anything(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)
    s = _Session(_Answer(200, {"success": True}))
    with pytest.raises(core.PixAIError, match="READ_ONLY"):
        cloud_delete.delete_task_media(s, "T1", "M1")
    assert s.posts == []


def test_the_router_fires_the_rest_media_delete_for_a_batch_member(monkeypatch):
    task = {"outputs": {"mediaId": "GRID", "batch": [{"mediaId": "a"}, {"mediaId": "b"}]}}
    monkeypatch.setattr(cloud_delete._task_reads, "task_detail_gql", lambda s, t, **k: task)
    fired = []
    monkeypatch.setattr(cloud_delete, "delete_task_media",
                        lambda s, t, m: fired.append(("media", t, m)) or True)
    monkeypatch.setattr(cloud_delete, "delete_task", lambda s, t: fired.append(("task", t)))
    monkeypatch.setattr(cloud_delete, "delete_batch_media_gql",
                        lambda *a: pytest.fail("the GraphQL per-image delete was sent"))
    plan = cloud_delete.delete_image_routed(object(), "T1", "a", confirmed_plan="per-image")
    assert plan.plan == "per-image" and fired == [("media", "T1", "a")]


def test_the_media_delete_has_one_send_and_no_loop():
    tree = ast.parse(textwrap.dedent(inspect.getsource(cloud_delete.delete_task_media)))
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While, ast.ListComp,
                                                            ast.GeneratorExp))]
    sends = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("rest_post", "post", "put", "patch", "mutate", "query")]
    assert sends == ["rest_post"]
