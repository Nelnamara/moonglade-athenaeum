"""Tests for the task-level delete mutation (delete_task_gql), and that the command line
no longer has a delete of its own.

These never hit the network: the GraphQL call is mocked. The point is to lock in the SAFETY
guards (the READ_ONLY refusal, single attempt, no retry) so they can't regress.
"""
import pytest

from moonglade import backup as core


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
        """Defensive only -- the hash ships with a working default, so this guard can fire
        solely if that default is stripped or blanked in config.json. It is NOT a setup
        gate (the gallery's typed DELETE and READ_ONLY are); the message must not claim
        otherwise."""
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "")
        with pytest.raises(core.PixAIError, match="DELETE_TASK_HASH is empty"):
            core.delete_task_gql(mock_session, "123")
        mock_session.post.assert_not_called()

    def test_delete_hash_has_a_working_default(self):
        """The real gates are the gallery's typed DELETE and READ_ONLY. Docs claimed for
        months that a missing hash was a setup gate that stopped deletion from firing -- it
        never was."""
        assert core.DELETE_TASK_HASH and len(core.DELETE_TASK_HASH) == 64

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
# the command line no longer deletes
# ---------------------------------------------------------------------------

class TestNoCommandLineDelete:
    """`--delete-task` (deprecated 2026-09-06) is gone, and so is the `--yes` that only it
    used. The gallery's Delete from PixAI is the one road to deleting from the account; its
    guards (READ_ONLY, localhost-only, the typed DELETE, the read-back before a single-image
    delete) are tested in test_read_only.py, test_api_bulk_json.py and test_delete_image.py."""

    @pytest.mark.parametrize("argv", [
        ["--delete-task", "123"],
        ["--delete-task", "123", "--apply", "--yes"],
        ["--yes"],
    ])
    def test_the_parser_refuses_it_and_nothing_reaches_pixai(self, monkeypatch, capsys, argv):
        import sys
        monkeypatch.setattr(core, "_make_session",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("network!")))
        monkeypatch.setattr(core, "delete_task_gql",
                            lambda *a, **k: pytest.fail("a delete was sent"))
        monkeypatch.setattr(sys, "argv", ["prog", *argv])
        with pytest.raises(SystemExit) as exc:
            core.main()
        assert exc.value.code == 2                       # argparse: unrecognized arguments
        assert "unrecognized arguments" in capsys.readouterr().err
