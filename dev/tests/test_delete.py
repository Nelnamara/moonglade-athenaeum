"""Tests for the task-level delete (delete_task: POST /v2/task/{id}/delete, #92), and that the
command line no longer has a delete of its own.

These never hit the network: the session is mocked. The point is to lock in the SAFETY
guards (the READ_ONLY refusal, single attempt, no retry, only {"success": true} counts) so
they can't regress. The full refuse matrix is in test_rest_delete_and_renewal.py.
"""
import pytest
import requests

from moonglade import backup as core


def _post_response(mocker, status_code=200, json_body=None, text=""):
    resp = mocker.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


# ---------------------------------------------------------------------------
# delete_task()
# ---------------------------------------------------------------------------

class TestDeleteTask:
    def test_success_returns_true_after_one_post(self, mock_session, mocker):
        mock_session.post.return_value = _post_response(mocker, json_body={"success": True})
        assert core.delete_task(mock_session, "123") is True
        mock_session.post.assert_called_once()  # single attempt, no retry loop
        mock_session.get.assert_not_called()

    def test_the_wire_is_the_rest_route_with_an_empty_body(self, mock_session, mocker):
        mock_session.post.return_value = _post_response(mocker, json_body={"success": True})
        core.delete_task(mock_session, "123")
        args, kwargs = mock_session.post.call_args
        assert args[0] == core.REST_API_BASE + "/task/123/delete"
        assert kwargs["json"] == {}
        assert "params" not in kwargs                    # no GraphQL operation/u3t params

    def test_a_success_false_is_not_a_delete(self, mock_session, mocker):
        mock_session.post.return_value = _post_response(mocker, json_body={"success": False})
        with pytest.raises(core.PixAIError, match="not deleted"):
            core.delete_task(mock_session, "123")
        mock_session.post.assert_called_once()

    def test_401_raises(self, mock_session, mocker):
        mock_session.post.return_value = _post_response(mocker, status_code=401, json_body={})
        with pytest.raises(core.PixAIError, match="401"):
            core.delete_task(mock_session, "123")
        mock_session.post.assert_called_once()

    def test_a_network_error_is_one_attempt(self, mock_session):
        mock_session.post.side_effect = requests.ConnectionError("boom")
        with pytest.raises(core.PixAIError, match="network error deleting task 123"):
            core.delete_task(mock_session, "123")
        mock_session.post.assert_called_once()

    def test_a_bad_id_sends_nothing(self, mock_session):
        with pytest.raises(core.PixAIError, match="not a PixAI task id"):
            core.delete_task(mock_session, "../graphql")
        mock_session.post.assert_not_called()


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
        monkeypatch.setattr(core, "delete_task",
                            lambda *a, **k: pytest.fail("a delete was sent"))
        monkeypatch.setattr(sys, "argv", ["prog", *argv])
        with pytest.raises(SystemExit) as exc:
            core.main()
        assert exc.value.code == 2                       # argparse: unrecognized arguments
        assert "unrecognized arguments" in capsys.readouterr().err
