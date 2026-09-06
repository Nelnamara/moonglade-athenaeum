"""READ_ONLY: a config.json trust signal for anyone nervous about handing a third-party
tool spend/delete access to their PixAI account. The property that actually matters isn't
"does it raise" -- it's that the underlying network call NEVER FIRES, and that this holds
even when --confirm/--apply/--yes are passed, since those flags are exactly what a cautious
first run wants to be safe to use without reading the source first.

This file covers the four WEB choke points -- submit_generation, submit_fixer,
delete_task_gql, claim_reward -- that the web app's generate/edit/fix/delete/claim
routes all funnel through. The CLI's generation entry points (run_generate,
run_generate_video, run_reference_video, run_edit_image) build their OWN
createGenerationTask call instead of calling through these choke points and, until 2026-07-21, none of them checked
READ_ONLY at all -- see tests/test_read_only_cli_paths.py for that half."""
import pytest

import moonglade_backup as core


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

    def test_overrides_apply_and_yes(self, pixai, monkeypatch, tmp_path, capsys):
        """The whole point: --apply --yes must NOT be enough to get past READ_ONLY. Drives
        the real CLI entry point, not just the raw function, for genuine end-to-end proof."""
        from types import SimpleNamespace
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        args = SimpleNamespace(delete_task=["123"], apply=True, yes=True, delay=0)
        result = core.run_delete_tasks(args)
        assert result["deleted"] == 0
        assert result["failed"] == 1
        # Nothing reached PixAI at all -- the fake records every verb, and READ_ONLY
        # refuses before the delete mutation is ever built.
        assert pixai.calls == []


class TestRoutedImageDeleteReadOnly:
    """The per-image delete picks between the two mutations above by READING the task first
    (2026-09-06). READ_ONLY has to refuse before even that read, so a read-only install makes
    no network call at all for a delete -- and it has to hold on BOTH branches, since the
    branch is chosen after the guard would otherwise have run."""

    @pytest.mark.parametrize("outputs, branch", [
        ({"mediaId": "GRID", "batch": [{"mediaId": "m0"}, {"mediaId": "m1"}]}, "per-image"),
        ({"mediaId": "solo1"}, "whole-task"),
    ])
    def test_both_branches_blocked_before_any_network_call(
            self, mock_session, monkeypatch, outputs, branch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "DELETE_TASK_HASH", "deadbeef")
        reads = []
        monkeypatch.setattr(core, "task_detail_gql",
                            lambda *a, **k: reads.append(1) or {"outputs": outputs})
        target = "m0" if branch == "per-image" else "solo1"
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.delete_image_routed(mock_session, "T1", target)
        mock_session.post.assert_not_called()
        assert reads == [], (
            "it read the task from PixAI before refusing -- READ_ONLY must stop the delete "
            "before any call at all")

    def test_the_guard_is_the_first_statement(self):
        """Placement, not just presence: a guard that ran after the read would already have
        made a network call, and one that ran after the routing would have to be repeated on
        every branch that gets added later."""
        import ast
        import inspect
        import textwrap
        fn = ast.parse(textwrap.dedent(
            inspect.getsource(core.delete_image_routed))).body[0]
        body = [n for n in fn.body if not (isinstance(n, ast.Expr)
                                           and isinstance(n.value, ast.Constant))]
        first = body[0]
        assert (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and getattr(first.value.func, "id", "") == "_check_read_only"), (
            "_check_read_only is not the first thing delete_image_routed does")


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


class TestTrainingAndArtworkMutationsReadOnly:
    """The account-mutating paths added AFTER this file's original four choke points:
    LoRA training (spends real credits once the free-training quota is gone) and the
    artwork publish/edit/delete surface (mutates your PUBLIC profile). Each names
    _check_read_only as its first line, and until this test existed that guard was pinned
    only by a source-grep (test_spend_no_retry.SPEND_PATHS) -- deleting the line would still
    have passed the suite. The property asserted is the one the rest of this file makes: the
    network call NEVER FIRES under READ_ONLY. Their single-attempt behaviour is pinned
    separately in tests/test_spend_no_retry.py."""
    def test_submit_training_blocked(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        # _check_read_only runs before validate_training, so even wholly-invalid args must
        # be refused at the guard, not fall through to a validation error.
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.submit_training(mock_session, "base1", ["m1"], "Title", "trig", "style")
        mock_session.post.assert_not_called()

    def test_publish_artwork_blocked(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.publish_artwork_from_task(mock_session, "task1")
        mock_session.post.assert_not_called()

    def test_update_artwork_blocked(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.update_artwork(mock_session, "art1", title="new title")
        mock_session.post.assert_not_called()

    def test_delete_artwork_blocked(self, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.delete_artwork(mock_session, "art1")
        mock_session.post.assert_not_called()


class TestReadOnlyDoesNotTouchLocalOperations:
    """READ_ONLY is scoped to PixAI-account mutations. --organize/--dedup are a different,
    already-covered trust concern (dry-run-by-default + --apply, never the network) --
    conflating the two would be a weaker promise than the one this flag actually makes."""
    def test_organize_and_dedup_unaffected(self, monkeypatch):
        # No function under test here -- this documents the boundary so a future change
        # that widens _check_read_only's call sites has to consciously cross it. Both
        # halves of the class's own name are asserted -- the test used to only look at
        # cmd_dedup, so cmd_organize (equally named in the docstring and the test's own
        # name) could grow a _check_read_only call with nothing here to notice.
        import inspect
        src = inspect.getsource(core.cmd_dedup)
        assert "_check_read_only" not in src
        organize_src = inspect.getsource(core.cmd_organize)
        assert "_check_read_only" not in organize_src
