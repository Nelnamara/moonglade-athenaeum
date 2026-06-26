"""Tests for the delete-task feature (delete_task_gql + run_delete_tasks).

These never hit the network: the GraphQL call is mocked, and run_delete_tasks is
driven with a SimpleNamespace args object. The point is to lock in the SAFETY
guards (dry-run default, confirmation, single-attempt) so they can't regress.
"""
from types import SimpleNamespace

import pytest

import pixai_gallery_backup as core


def _post_response(mocker, status_code=200, json_body=None, text="", ssl_error=False):
    resp = mocker.MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


# ---------------------------------------------------------------------------
# delete_task_gql()
# ---------------------------------------------------------------------------

class TestDeleteTaskGql:
    def test_success_returns_payload(self, mock_session, mocker, monkeypatch):
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        mock_session.post.return_value = _post_response(
            mocker, json_body={"data": {"deleteGenerationTask": True}})
        assert core.delete_task_gql(mock_session, "123") is True
        mock_session.post.assert_called_once()  # single attempt, no retry loop

    def test_missing_hash_raises_before_any_call(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "")
        with pytest.raises(core.PixAIError, match="DELETE_TASK_HASH missing"):
            core.delete_task_gql(mock_session, "123")
        mock_session.post.assert_not_called()

    def test_persisted_query_not_found(self, mock_session, mocker, monkeypatch):
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        mock_session.post.return_value = _post_response(
            mocker, json_body={"errors": [{"message": "PersistedQueryNotFound"}]})
        with pytest.raises(core.PixAIError, match="hash not recognized"):
            core.delete_task_gql(mock_session, "123")

    def test_graphql_error_raises(self, mock_session, mocker, monkeypatch):
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        mock_session.post.return_value = _post_response(
            mocker, json_body={"errors": [{"message": "not your task"}]})
        with pytest.raises(core.PixAIError, match="GraphQL error deleting task"):
            core.delete_task_gql(mock_session, "123")

    def test_401_raises(self, mock_session, mocker, monkeypatch):
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        mock_session.post.return_value = _post_response(
            mocker, status_code=401, json_body={})
        with pytest.raises(core.PixAIError, match="401"):
            core.delete_task_gql(mock_session, "123")

    def test_uses_post_not_get(self, mock_session, mocker, monkeypatch):
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        mock_session.post.return_value = _post_response(
            mocker, json_body={"data": {"deleteGenerationTask": True}})
        core.delete_task_gql(mock_session, "123")
        mock_session.post.assert_called_once()
        mock_session.get.assert_not_called()
        # taskId is carried in the JSON body variables.
        _, kwargs = mock_session.post.call_args
        assert kwargs["json"]["variables"] == {"taskId": "123"}


# ---------------------------------------------------------------------------
# run_delete_tasks() -- the safety guards
# ---------------------------------------------------------------------------

class TestRunDeleteTasks:
    def test_no_ids_raises(self):
        args = SimpleNamespace(delete_task=[], apply=False, yes=False)
        with pytest.raises(core.PixAIError, match="No task ids"):
            core.run_delete_tasks(args)

    def test_dry_run_deletes_nothing(self, monkeypatch):
        # _make_session/delete must NOT be reached in a dry run.
        monkeypatch.setattr(core, "_make_session",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!")))
        args = SimpleNamespace(delete_task=["1", "2"], apply=False, yes=False)
        out = core.run_delete_tasks(args)
        assert out == {"targeted": 2, "deleted": 0, "failed": 0, "dry_run": True}

    def test_dedupes_ids(self, monkeypatch):
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: None)
        args = SimpleNamespace(delete_task=["7", "7", "8"], apply=False, yes=False)
        out = core.run_delete_tasks(args)
        assert out["targeted"] == 2  # duplicate "7" collapsed

    def test_apply_without_yes_on_non_tty_refuses(self, monkeypatch):
        # pytest's stdin is not a tty, so confirmation can't be obtained.
        monkeypatch.setattr(core, "_make_session",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!")))
        args = SimpleNamespace(delete_task=["1"], apply=True, yes=False, token=None)
        with pytest.raises(core.PixAIError, match="interactive confirmation"):
            core.run_delete_tasks(args)

    def test_apply_with_yes_deletes_each(self, monkeypatch):
        calls = []
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: "SESSION")
        monkeypatch.setattr(core, "delete_task_gql",
                            lambda session, tid: calls.append(tid) or True)
        args = SimpleNamespace(delete_task=["10", "11"], apply=True, yes=True,
                               token=None, delay=0)
        out = core.run_delete_tasks(args)
        assert calls == ["10", "11"]
        assert out == {"targeted": 2, "deleted": 2, "failed": 0}

    def test_apply_counts_failures(self, monkeypatch):
        def _boom(session, tid):
            if tid == "bad":
                raise core.PixAIError("nope")
            return None
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: "SESSION")
        monkeypatch.setattr(core, "delete_task_gql", _boom)
        args = SimpleNamespace(delete_task=["ok", "bad"], apply=True, yes=True,
                               token=None, delay=0)
        out = core.run_delete_tasks(args)
        assert out == {"targeted": 2, "deleted": 1, "failed": 1}

    def test_null_return_counts_as_deleted(self, monkeypatch):
        # deleteGenerationTask is a void mutation: it returns null on a SUCCESSFUL
        # delete (confirmed against a real task). A clean return -- even None --
        # means the task was deleted, so it must count as a deletion, not a no-op.
        monkeypatch.setattr(core, "_make_session", lambda *a, **k: "SESSION")
        monkeypatch.setattr(core, "delete_task_gql", lambda session, tid: None)
        args = SimpleNamespace(delete_task=["real-task"], apply=True, yes=True,
                               token=None, delay=0)
        out = core.run_delete_tasks(args)
        assert out == {"targeted": 1, "deleted": 1, "failed": 0}
