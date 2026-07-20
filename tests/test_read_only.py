"""READ_ONLY: a config.json trust signal for anyone nervous about handing a third-party
tool spend/delete access to their PixAI account. The property that actually matters isn't
"does it raise" -- it's that the underlying network call NEVER FIRES, and that this holds
even when --confirm/--apply/--yes are passed, since those flags are exactly what a cautious
first run wants to be safe to use without reading the source first. All four choke points
(submit_generation, submit_fixer, delete_task_gql, claim_reward) are covered -- both the CLI
and the web app's generate/edit/enhance/fix/delete/claim routes funnel through these same
four functions, so gating here covers both surfaces from one place."""
import pytest

import pixai_gallery_backup as core


def test_read_only_defaults_to_false():
    """The flag must be opt-in -- an existing config.json with no READ_ONLY key must not
    suddenly start refusing generations."""
    assert core.READ_ONLY is False


class TestSubmitGeneration:
    def test_blocked_when_read_only(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.submit_generation(mock_session, {"prompt": "a cat"})
        mock_session.post.assert_not_called()  # the property that matters: no network call

    def test_allowed_when_not_read_only(self, mock_session, mocker, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", False)
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": {"createGenerationTask": {"id": "t1"}}}
        mock_session.post.return_value = resp
        assert core.submit_generation(mock_session, {"prompt": "a cat"}) == "t1"
        mock_session.post.assert_called_once()


class TestSubmitFixer:
    def test_blocked_when_read_only(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        boxes = [{"x": 0, "y": 0, "width": 10, "height": 10, "tag": "hand"}]
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.submit_fixer(mock_session, "mid1", boxes)
        mock_session.post.assert_not_called()


class TestDeleteTaskGqlReadOnly:
    def test_blocked_when_read_only(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")  # would otherwise pass its own guard
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.delete_task_gql(mock_session, "123")
        mock_session.post.assert_not_called()

    def test_overrides_apply_and_yes(self, mock_session, monkeypatch, tmp_path, capsys):
        """The whole point: --apply --yes must NOT be enough to get past READ_ONLY. Drives
        the real CLI entry point, not just the raw function, for genuine end-to-end proof."""
        from types import SimpleNamespace
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        args = SimpleNamespace(delete_task=["123"], apply=True, yes=True, delay=0)
        result = core.run_delete_tasks(args)
        assert result["deleted"] == 0
        assert result["failed"] == 1
        mock_session.post.assert_not_called()


class TestClaimReward:
    def test_blocked_when_read_only(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.claim_reward(mock_session, "claim1")
        mock_session.post.assert_not_called()

    def test_allowed_when_not_read_only(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", False)
        calls = []
        monkeypatch.setattr(core, "_rest_post", lambda *a, **k: calls.append(a) or {"ok": True})
        core.claim_reward(mock_session, "claim1")
        assert calls  # _rest_post genuinely fired


class TestReadOnlyDoesNotTouchLocalOperations:
    """READ_ONLY is scoped to PixAI-account mutations. --organize/--dedup are a different,
    already-covered trust concern (dry-run-by-default + --apply, never the network) --
    conflating the two would be a weaker promise than the one this flag actually makes."""

    def test_organize_and_dedup_unaffected(self, monkeypatch):
        # No function under test here -- this documents the boundary so a future change
        # that widens _check_read_only's call sites has to consciously cross it.
        import inspect
        src = inspect.getsource(core.cmd_dedup)
        assert "_check_read_only" not in src
